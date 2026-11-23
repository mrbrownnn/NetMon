"""Environment configuration. Stable explicit keys required; never written to disk."""
import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


def normalize_db_url(url: str) -> str:
    """Railway/Heroku give postgres:// or postgresql://; route both to the installed psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def sqlite_parent(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)


class Settings:
    def __init__(self):
        load_dotenv()
        production = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT_ID") or os.getenv("NETMON_ENV") == "production")
        if production:
            missing = [k for k in ("SECRET_KEY", "FERNET_KEY", "ADMIN_PASSWORD") if not os.getenv(k)]
            if missing:
                raise ValueError("Production requires stable environment values: " + ", ".join(missing))
            if len(os.environ["SECRET_KEY"]) < 32 or len(os.environ["ADMIN_PASSWORD"]) < 12 or os.environ["ADMIN_PASSWORD"].lower() in ("admin123", "changeme12345", "password12345"):
                raise ValueError("Production requires SECRET_KEY >= 32 characters and strong ADMIN_PASSWORD >= 12 characters")
        missing = [k for k in ("SECRET_KEY", "FERNET_KEY") if not os.getenv(k)]
        if missing:
            raise ValueError("Stable environment keys required: " + ", ".join(missing))
        self.SECRET_KEY = os.environ["SECRET_KEY"]
        self.FERNET_KEY = os.environ["FERNET_KEY"]
        Fernet(self.FERNET_KEY.encode())
        self.DATABASE_URL = normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///netmon.db"))
        self.ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
        self.ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
        # GNS3 2.2 server URL (e.g. http://127.0.0.1:3080) or "demo" for the built-in fake lab; empty = disabled.
        self.GNS3_URL = os.getenv("GNS3_URL", "").strip()
        sqlite_parent(self.DATABASE_URL)
