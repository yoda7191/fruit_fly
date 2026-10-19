"""Database: experiments and sweeps (SQLAlchemy 2.0; SQLite or PostgreSQL).

Results are stored as JSON documents: they are always read and written whole,
and their shape is already defined by schemas.ExperimentResult. Columns that
are filtered or sorted on (status, sweep, time) are real columns with indexes.
Spike recordings are too large for rows and live in files (spikes.py).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import (JSON, DateTime, Float, ForeignKey, Integer, String, Text,
                        TypeDecorator, create_engine, event, false, inspect, text)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

log = logging.getLogger("fruit_fly.db")


PENDING = ("queued", "running")
FINISHED = ("done", "failed", "cancelled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC in Python.

    PostgreSQL stores time zones; SQLite does not and hands back naive
    datetimes, which the API would send without a "Z" and browsers would then
    read as local time. Normalising here makes both databases behave the same.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware UTC (db.utcnow())")
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class SweepRow(Base):
    __tablename__ = "sweeps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    parameter: Mapped[str] = mapped_column(String(64))
    values: Mapped[list] = mapped_column(JSON)
    repeats: Mapped[int] = mapped_column(Integer)
    base_request: Mapped[dict] = mapped_column(JSON)
    owner: Mapped[str | None] = mapped_column(String(80), default=None)     # migration 0005

    experiments: Mapped[list["ExperimentRow"]] = relationship(
        back_populates="sweep", cascade="all, delete-orphan", passive_deletes=True)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sweep_id: Mapped[str | None] = mapped_column(
        ForeignKey("sweeps.id", ondelete="CASCADE"), index=True, default=None)
    sweep_value: Mapped[float | None] = mapped_column(Float, default=None)
    # Non-numeric sweep values, e.g. the lesion a lesion scan applied ("MBON01",
    # "none"). Added in migration 0002.
    sweep_label: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    request: Mapped[dict] = mapped_column(JSON)
    store_spikes: Mapped[bool] = mapped_column(default=True)
    progress_done: Mapped[int | None] = mapped_column(Integer, default=None)
    progress_total: Mapped[int | None] = mapped_column(Integer, default=None)
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # Added in migration 0004: see that migration for what each is for.
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default=false())
    request_key: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    request_id: Mapped[str | None] = mapped_column(String(64), default=None)
    owner: Mapped[str | None] = mapped_column(String(80), default=None)     # migration 0005: who submitted it

    sweep: Mapped[SweepRow | None] = relationship(back_populates="experiments")

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


class ApiKeyRow(Base):
    """An API key, stored only as its SHA-256 hash (the key itself is shown once,
    when created). Added in migration 0003."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):     # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")     # readers don't block the writer
            cur.execute("PRAGMA foreign_keys=ON")      # enforce ON DELETE CASCADE
            cur.close()
        return engine
    return create_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: Engine) -> sessionmaker:
    # expire_on_commit=False: rows stay readable after the session closes.
    return sessionmaker(engine, expire_on_commit=False)


# Any fixed number: every fruit_fly process takes the same lock.
_SCHEMA_LOCK_KEY = 872_615_001

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
# Databases created before migrations existed (by Base.metadata.create_all)
# have exactly this revision's schema.
INITIAL_REVISION = "0001"


def migrate(connection: Connection) -> None:
    """Bring the schema to the newest migration, inside the caller's transaction."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" not in tables and {"experiments", "sweeps"} <= tables:
        log.info("database predates migrations; marking it as revision %s", INITIAL_REVISION)
        command.stamp(cfg, INITIAL_REVISION)
    command.upgrade(cfg, "head")


def drop_db(engine: Engine) -> None:
    """Delete every table, including Alembic's record of the schema version.
    (Dropping only the app's tables would leave alembic_version saying the
    schema is current, and init_db would then not recreate them.) For tests."""
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def init_db(engine: Engine) -> None:
    """Create or upgrade the schema by running the Alembic migrations.

    The API and every worker call this at startup, often at the same moment.
    In PostgreSQL the processes take turns under a transaction-scoped advisory
    lock: the first runs any pending migrations, the others then find nothing
    to do. SQLite serialises writers itself; a retry covers lock timeouts.
    """
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK_KEY})
            migrate(conn)                                 # lock released at commit
        return
    for attempt in range(5):
        try:
            with engine.begin() as conn:
                migrate(conn)
            return
        except DBAPIError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))