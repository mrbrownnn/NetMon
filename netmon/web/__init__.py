"""Flask JSON API and same-origin React application."""
import hashlib
import hmac
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_socketio import SocketIO, join_room
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import select
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

socketio = SocketIO(async_mode="threading")
csrf = CSRFProtect()


def create_app(test_config=None):
    from netmon.infra.config import Settings
    from netmon.infra.db import User
    from netmon.services.facade import NetMonService
    from netmon.domain.gns3 import Gns3Error
    from netmon.services.errors import AuthError, ValidationError
    settings = Settings()
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(SECRET_KEY=settings.SECRET_KEY, FERNET_KEY=settings.FERNET_KEY,
        DATABASE_URL=settings.DATABASE_URL, START_SCHEDULER=True,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT_ID")),
        FRONTEND_DIST=str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    app.config.update(test_config or {})
    if "start_scheduler" in app.config:
        app.config["START_SCHEDULER"] = app.config["start_scheduler"]
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT_ID"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    def fingerprints():
        # Password-hash fingerprint per active user; changes on password change/reset, revoking old sessions.
        with app.extensions["netmon"].db.session() as s:
            rows = s.execute(select(User.id, User.password_hash, User.is_locked, User.locked_until)).all()
        now = datetime.now()
        return {r.id: hashlib.sha256(r.password_hash.encode()).hexdigest()[:16]
                for r in rows if not r.is_locked and not (r.locked_until and r.locked_until > now)}

    def fingerprint(uid):
        return fingerprints().get(uid)

    app.fingerprint = fingerprint

    def active_user():
        uid = session.get("user_id")
        if uid is None:
            return None
        fp = fingerprint(uid)
        if fp is None or not hmac.compare_digest(fp, session.get("pw", "")):
            session.clear()
            return None
        return app.extensions["netmon"].auth.get(uid)

    @app.before_request
    def load_user():
        g.user = active_user()
        if (request.path == "/api" or request.path.startswith("/api/")) and (request.url_rule is None or request.endpoint == "spa"):
            return jsonify(error="Not found", message="Not found"), 404
        public = request.path in ("/api/auth/session", "/api/auth/login")
        if request.path.startswith("/api/") and not public and not g.user:
            return jsonify(error="Authentication required", message="Authentication required"), 401

    csrf.init_app(app)
    socketio.init_app(app)

    def publish(event, payload):
        # Rooms keyed by user+fingerprint: locked users and sockets from pre-password-change sessions get nothing.
        for uid, fp in fingerprints().items():
            socketio.emit(event, payload, namespace="/ws/status", to=f"user:{uid}:{fp}")

    service = NetMonService.create(app.config["DATABASE_URL"], app.config["FERNET_KEY"],
        publish, start_scheduler=False)
    app.extensions["netmon"] = service
    if os.getenv("NETMON_DEMO") == "1":  # ponytail: demo seed; unset before go-live
        from netmon.demo import seed
        seed(service)
    if app.config["START_SCHEDULER"]:
        service.monitor.start()

    @socketio.on("connect", namespace="/ws/status")
    def ws_connect(auth=None):
        user = active_user()
        if not user:
            return False
        join_room(f"user:{user['id']}:{session['pw']}")
        join_room(f"session:{session['sid']}")

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return jsonify(error="CSRF validation failed", message="CSRF validation failed", errors={"csrf_token": error.description}), 400

    @app.errorhandler(ValidationError)
    def validation_error(error):
        return jsonify(error="Validation failed", message="Validation failed", errors=error.field_errors), 400

    @app.errorhandler(AuthError)
    def auth_error(error):
        return jsonify(error=str(error), message=str(error), locked_seconds=error.locked_seconds), 423 if error.kind == "locked" else 401

    @app.errorhandler(KeyError)
    def missing_resource(error):
        return jsonify(error="Resource not found", message="Resource not found"), 404

    @app.errorhandler(ValueError)
    @app.errorhandler(TypeError)
    def invalid_value(error):
        # Domain/service messages are user-facing text without secrets.
        message = str(error) or "Invalid request"
        return jsonify(error=message, message=message, errors={"request": message}), 400

    @app.errorhandler(Gns3Error)
    def gns3_error(error):
        return jsonify(error=str(error), message=str(error)), 502

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.name, message=error.description), error.code

    from .routes.api import api
    app.register_blueprint(api)

    @app.get("/healthz")
    def health():
        return jsonify(ok=True)

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if path == "api" or path.startswith("api/"):
            return jsonify(error="Not found", message="Not found"), 404
        dist = Path(app.config["FRONTEND_DIST"])
        if not (dist / "index.html").is_file():
            return jsonify(error="Frontend build missing", message="Build React frontend with npm run build in frontend/."), 503
        if path and (dist / path).is_file():
            return send_from_directory(dist, path)
        if path.startswith("assets/"):
            return jsonify(error="Not found", message="Not found"), 404
        return send_from_directory(dist, "index.html")

    return app
