"""User management and FR-02 login throttling."""
import math
from datetime import datetime, timedelta
from threading import RLock

from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash
from netmon.infra.db import User
from .common import require, row_dict
from .errors import AuthError, ValidationError


def public(user):
    return row_dict(user, ("password_hash",))


class AuthService:
    def __init__(self, db, audit):
        self.db, self.audit = db, audit
        self.lock_ = RLock()
        self.dummy_hash = generate_password_hash("not-a-real-password", method="pbkdf2:sha256")

    def seed_admin(self, username, password):
        with self.db.session() as s:
            empty = s.scalar(select(User.id).limit(1)) is None
        if empty:
            return self.create(username, password, "admin")

    def login(self, username, password, actor=None):
        error = None
        with self.lock_, self.db.session() as s:
            u = s.scalar(select(User).where(User.username == username))
            now = datetime.now()
            if u is None:
                check_password_hash(self.dummy_hash, password)
                error = AuthError()
            elif u.is_locked or (u.locked_until and u.locked_until > now):
                seconds = max(1, math.ceil((u.locked_until - now).total_seconds())) if u.locked_until else 0
                error = AuthError("locked", seconds)
            else:
                if u.locked_until:
                    u.failed_attempts, u.locked_until = 0, None
                if not check_password_hash(u.password_hash, password):
                    u.failed_attempts += 1
                    if u.failed_attempts >= 5:
                        u.locked_until = now + timedelta(minutes=5)
                        error = AuthError("locked", 300)
                    else:
                        error = AuthError()
                else:
                    u.failed_attempts, u.locked_until, u.last_login = 0, None, now
            result = public(u) if u else None
        self.audit.log(result or actor, "login_failed" if error else "login", "auth", {"kind": error.kind} if error else {})
        if error:
            raise error
        return result

    def users(self):
        with self.db.session() as s:
            return [public(u) for u in s.scalars(select(User).order_by(User.username))]

    def get(self, user_id):
        with self.db.session() as s:
            return public(require(s, User, user_id))

    def create(self, username, password, role="viewer", actor=None):
        username = str(username).strip()
        if not username or not password:
            raise ValidationError({"username": "Tên và mật khẩu không được trống"})
        self._role(role)
        with self.db.session() as s:
            if s.scalar(select(User.id).where(User.username == username)):
                raise ValidationError({"username": "Tên đã tồn tại"})
            u = User(username=username, password_hash=generate_password_hash(password, method="pbkdf2:sha256"), role=role)
            s.add(u)
            s.flush()
            result = public(u)
        self.audit.log(actor, "user_create", result["id"])
        return result

    def _role(self, role):
        if role not in ("admin", "operator", "viewer"):
            raise ValidationError({"role": "Vai trò không hợp lệ"})

    def _guard_admin(self, session, user):
        if user.role == "admin" and not user.is_locked:
            other = session.scalar(select(User.id).where(User.role == "admin", User.is_locked.is_(False), User.id != user.id).limit(1))
            if other is None:
                raise ValidationError({"user": "Phải giữ ít nhất một quản trị viên không bị khóa"})

    def _update(self, user_id, values, action, actor):
        with self.db.session() as s:
            u = require(s, User, user_id)
            if values.get("is_locked") or ("role" in values and values["role"] != "admin"):
                if actor and actor.get("id") == user_id and u.role == "admin":
                    raise ValidationError({"user": "Không thể tự khóa hoặc hạ quyền chính mình"})
                self._guard_admin(s, u)
            for k, v in values.items():
                setattr(u, k, v)
            result = public(u)
        self.audit.log(actor, action, user_id)
        return result

    def set_role(self, user_id, role, actor=None):
        self._role(role)
        return self._update(user_id, {"role": role}, "user_role", actor)

    def lock(self, user_id, actor=None):
        return self._update(user_id, {"is_locked": True}, "user_lock", actor)

    def unlock(self, user_id, actor=None):
        return self._update(user_id, {"is_locked": False, "locked_until": None, "failed_attempts": 0}, "user_unlock", actor)

    def reset_password(self, user_id, password, actor=None):
        if not password:
            raise ValidationError({"password": "Mật khẩu không được trống"})
        return self._update(user_id, {"password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
            "failed_attempts": 0, "locked_until": None}, "user_password_reset", actor)

    def change_password(self, user_id, old_password, new_password, actor=None):
        with self.db.session() as s:
            if not check_password_hash(require(s, User, user_id).password_hash, old_password):
                raise AuthError()
        result = self.reset_password(user_id, new_password, actor)
        return result

    def delete(self, user_id, actor=None):
        with self.db.session() as s:
            user = require(s, User, user_id)
            if actor and actor.get("id") == user_id:
                raise ValidationError({"user": "Không thể tự xóa chính mình"})
            self._guard_admin(s, user)
            s.delete(user)
        self.audit.log(actor, "user_delete", user_id)
        return {"ok": True}
