"""Audit mutations without secret values."""
from sqlalchemy import select
from netmon.infra.db import AuditLog
from .common import date, paginate, row_dict


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if any(s in k.lower() for s in ("password", "token", "secret", "community")) else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class AuditService:
    def __init__(self, db):
        self.db = db

    def log(self, user, action, target, detail=None):
        actor = user or {}
        with self.db.session() as s:
            row = AuditLog(user_id=actor.get("id"), username=actor.get("username", "system"),
                           action=action, target=str(target), detail=redact(detail or {}))
            s.add(row)
            s.flush()
            return row_dict(row)

    def query(self, user_id=None, action=None, target=None, from_=None, to=None, page=1):
        with self.db.session() as s:
            q = select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
            for col, val in ((AuditLog.user_id, user_id), (AuditLog.action, action), (AuditLog.target, target)):
                if val is not None:
                    q = q.where(col == val)
            if from_:
                q = q.where(AuditLog.ts >= date(from_))
            if to:
                q = q.where(AuditLog.ts <= date(to))
            return paginate([row_dict(r) for r in s.scalars(q)], page)
