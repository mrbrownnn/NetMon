"""SQLAlchemy 2 persistence, one scoped session per thread."""
from contextlib import contextmanager
from datetime import datetime
from threading import RLock

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import normalize_db_url, sqlite_parent


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(default="viewer")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    ip: Mapped[str] = mapped_column(String(15), unique=True)
    mac: Mapped[str] = mapped_column(default="")
    device_type: Mapped[str] = mapped_column(default="pc")
    vendor: Mapped[str] = mapped_column(default="")
    location: Mapped[str] = mapped_column(default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    protocol: Mapped[str] = mapped_column(default="ssh")
    port: Mapped[int] = mapped_column(default=22)
    username: Mapped[str] = mapped_column(default="")
    password_enc: Mapped[str] = mapped_column(Text)
    driver: Mapped[str] = mapped_column(default="vyos")


class Sensor(Base):
    __tablename__ = "sensors"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(default="")
    target: Mapped[str] = mapped_column(default="")
    sensor_type: Mapped[str] = mapped_column()
    interval: Mapped[int] = mapped_column(default=30)
    timeout: Mapped[float] = mapped_column(Float, default=5)
    warning_threshold: Mapped[float | None] = mapped_column(Float)
    down_after: Mapped[int] = mapped_column(default=3)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(default="UNKNOWN")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)


class CheckResult(Base):
    __tablename__ = "check_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensors.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column()
    value: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (Index("ix_check_results_sensor_ts", "sensor_id", "ts"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    sensor_id: Mapped[int | None] = mapped_column(ForeignKey("sensors.id", ondelete="SET NULL"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    device_name: Mapped[str] = mapped_column(default="")
    sensor_name: Mapped[str] = mapped_column(default="")
    level: Mapped[str] = mapped_column()
    state: Mapped[str] = mapped_column(default="OPEN")
    message: Mapped[str] = mapped_column(Text, default="")
    old_status: Mapped[str] = mapped_column(default="UNKNOWN")
    new_status: Mapped[str] = mapped_column(default="UNKNOWN")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ack_by: Mapped[str | None] = mapped_column()
    ack_note: Mapped[str] = mapped_column(Text, default="")
    ack_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class ConfigBackup(Base):
    __tablename__ = "config_backups"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    content: Mapped[str] = mapped_column(Text)


class ConfigChange(Base):
    __tablename__ = "config_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    command_type: Mapped[str] = mapped_column()
    params: Mapped[dict] = mapped_column(JSON)
    forward_cmds: Mapped[list] = mapped_column(JSON)
    undo_cmds: Mapped[list] = mapped_column(JSON)
    output: Mapped[str] = mapped_column(Text, default="")
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(default="system")
    action: Mapped[str] = mapped_column()
    target: Mapped[str] = mapped_column()
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class NotifierChannel(Base):
    __tablename__ = "notifier_channels"
    name: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_test_result: Mapped[str | None] = mapped_column(Text)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime)


class Database:
    def __init__(self, url: str):
        url = normalize_db_url(url)
        sqlite_parent(url)
        opts = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            opts["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url.endswith(":memory:") or url in ("sqlite://", "sqlite:///"):
                opts["poolclass"] = StaticPool
        self.engine = create_engine(url, **opts)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def pragmas(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        self.sessions = scoped_session(sessionmaker(bind=self.engine, expire_on_commit=False))
        # StaticPool shares one SQLite connection; serialize transactions across threads.
        self.lock = RLock()

    @contextmanager
    def session(self):
        with self.lock:
            session = self.sessions()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                self.sessions.remove()

    def init_db(self):
        Base.metadata.create_all(self.engine)

    def close(self):
        self.sessions.remove()
        self.engine.dispose()


def init_db(db: Database):
    db.init_db()
