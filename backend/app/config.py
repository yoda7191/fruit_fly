"""Settings, read once from environment variables.

Model and data
    FRUIT_FLY_CIRCUIT_DIR      folder with mb_neurons.csv + mb_edges.csv   (data/synthetic)
    FRUIT_FLY_DOOR_DIR         folder with the DoOR tables                (data/raw/door)
    FRUIT_FLY_PARAMS_FILE      JSON of default model parameters, e.g. the output of
                           `python -m fruit_fly.validation --calibrate --params-out ...` (unset)

Storage and jobs
    FRUIT_FLY_DATABASE_URL     SQLAlchemy URL of the experiment database
                           (sqlite:///data/fruit_fly.db; e.g. postgresql+psycopg://user:pw@host/db)
    FRUIT_FLY_STORAGE_DIR      where spike recordings are written         (data/runs)
    FRUIT_FLY_SPIKE_STORE      "local" (FRUIT_FLY_STORAGE_DIR) or "s3"     (local)
    FRUIT_FLY_S3_BUCKET        bucket for spike recordings with "s3"
    FRUIT_FLY_S3_PREFIX        key prefix inside the bucket                (runs/)
    FRUIT_FLY_S3_ENDPOINT      S3-compatible endpoint, e.g. MinIO http://minio:9000 (unset = AWS)
                           credentials: the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    FRUIT_FLY_QUEUE            "thread": run experiments inside the API process (default)
                           "redis":  put them on a Redis queue for `python -m backend.app.worker`
    FRUIT_FLY_REDIS_URL        Redis connection for the "redis" queue      (redis://localhost:6379/0)
    FRUIT_FLY_MAX_WORKERS      experiments running at once in "thread" mode (2)
    FRUIT_FLY_MAX_PENDING      queued + running experiments allowed before 429 (50)
    FRUIT_FLY_MAX_EXPERIMENTS  finished single experiments kept; older ones are deleted (200)
    FRUIT_FLY_MAX_SWEEP_SIZE   experiments one sweep may create           (100)
    FRUIT_FLY_JOB_TIMEOUT_S    longest a single experiment may run in "redis" mode (3600)

Access
    FRUIT_FLY_REQUIRE_API_KEY  1: submitting and deleting need an X-API-Key header (0)
                           (keys: python -m backend.app.apikeys create NAME)
    FRUIT_FLY_RATE_LIMIT       experiments one client may start per minute; 0 = no limit (0)
                           (per key, or per client address when keys aren't required)
    FRUIT_FLY_PROXY_HOPS       behind N reverse proxies, the client address is the N-th entry of
                           X-Forwarded-For counted from the right, the one the outermost of
                           *your* proxies added (0: use the connection's address). Entries
                           further left were sent by the client and can be forged.  (0)

Logging
    FRUIT_FLY_LOG_FORMAT       "text" or "json" (one JSON object per line, for log collectors) (text)
    FRUIT_FLY_LOG_LEVEL        DEBUG, INFO, WARNING, ...                  (INFO)

Web
    FRUIT_FLY_CORS_ORIGINS     comma-separated origins allowed to call the API
                           (http://localhost:5173,http://127.0.0.1:5173)
    FRUIT_FLY_STATIC_DIR       built frontend (frontend/dist) to serve at /; unset = API only

Relative paths are resolved against the repository root, so the server can be
started from any working directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


def _path(env_name: str, default: str) -> Path:
    p = Path(os.environ.get(env_name, default))
    return p if p.is_absolute() else REPO_ROOT / p


def _int(env_name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ValueError(f"{env_name} must be an integer, got {raw!r}") from e
    if value < minimum:
        raise ValueError(f"{env_name} must be >= {minimum}, got {value}")
    return value


def _bool(env_name: str, default: bool = False) -> bool:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    if raw.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if raw.strip().lower() in ("0", "false", "no", "off", ""):
        return False
    raise ValueError(f"{env_name} must be 1/0, true/false, yes/no or on/off, got {raw!r}")


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@dataclass(frozen=True)
class Settings:
    circuit_dir: Path
    door_dir: Path
    max_workers: int = 2
    max_experiments: int = 200
    cors_origins: tuple[str, ...] = tuple(DEFAULT_CORS.split(","))
    static_dir: Path | None = None
    params_file: Path | None = None
    database_url: str = ""                # "" -> SQLite file in storage_dir's parent
    storage_dir: Path | None = None       # None -> REPO_ROOT/data/runs
    queue: str = "thread"
    redis_url: str = "redis://localhost:6379/0"
    max_pending: int = 50
    max_sweep_size: int = 100
    job_timeout_s: int = 3600
    spike_store: str = "local"
    s3_bucket: str = ""
    s3_prefix: str = "runs/"
    s3_endpoint: str | None = None
    require_api_key: bool = False
    rate_limit: int = 0                   # experiments per minute per client; 0 = off
    proxy_hops: int = 0
    log_format: str = "text"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.log_format not in ("text", "json"):
            raise ValueError(f"FRUIT_FLY_LOG_FORMAT must be 'text' or 'json', got {self.log_format!r}")
        if self.queue not in ("thread", "redis"):
            raise ValueError(f"FRUIT_FLY_QUEUE must be 'thread' or 'redis', got {self.queue!r}")
        if self.spike_store not in ("local", "s3"):
            raise ValueError(f"FRUIT_FLY_SPIKE_STORE must be 'local' or 's3', got {self.spike_store!r}")
        if self.spike_store == "s3" and not self.s3_bucket:
            raise ValueError("FRUIT_FLY_SPIKE_STORE=s3 needs FRUIT_FLY_S3_BUCKET")

    @property
    def runs_dir(self) -> Path:
        return self.storage_dir or REPO_ROOT / "data" / "runs"

    @property
    def db_url(self) -> str:
        return self.database_url or sqlite_url(self.runs_dir.parent / "fruit_fly.db")

    @classmethod
    def from_env(cls) -> "Settings":
        origins = os.environ.get("FRUIT_FLY_CORS_ORIGINS", DEFAULT_CORS)
        return cls(
            circuit_dir=_path("FRUIT_FLY_CIRCUIT_DIR", "data/synthetic"),
            door_dir=_path("FRUIT_FLY_DOOR_DIR", "data/raw/door"),
            max_workers=_int("FRUIT_FLY_MAX_WORKERS", 2),
            max_experiments=_int("FRUIT_FLY_MAX_EXPERIMENTS", 200),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            static_dir=_path("FRUIT_FLY_STATIC_DIR", "") if os.environ.get("FRUIT_FLY_STATIC_DIR") else None,
            params_file=_path("FRUIT_FLY_PARAMS_FILE", "") if os.environ.get("FRUIT_FLY_PARAMS_FILE") else None,
            database_url=os.environ.get("FRUIT_FLY_DATABASE_URL", ""),
            storage_dir=_path("FRUIT_FLY_STORAGE_DIR", "data/runs"),
            queue=os.environ.get("FRUIT_FLY_QUEUE", "thread"),
            redis_url=os.environ.get("FRUIT_FLY_REDIS_URL", "redis://localhost:6379/0"),
            max_pending=_int("FRUIT_FLY_MAX_PENDING", 50),
            max_sweep_size=_int("FRUIT_FLY_MAX_SWEEP_SIZE", 100),
            job_timeout_s=_int("FRUIT_FLY_JOB_TIMEOUT_S", 3600, minimum=10),
            spike_store=os.environ.get("FRUIT_FLY_SPIKE_STORE", "local"),
            s3_bucket=os.environ.get("FRUIT_FLY_S3_BUCKET", ""),
            s3_prefix=os.environ.get("FRUIT_FLY_S3_PREFIX", "runs/"),
            s3_endpoint=os.environ.get("FRUIT_FLY_S3_ENDPOINT") or None,
            require_api_key=_bool("FRUIT_FLY_REQUIRE_API_KEY"),
            rate_limit=_int("FRUIT_FLY_RATE_LIMIT", 0, minimum=0),
            proxy_hops=_int("FRUIT_FLY_PROXY_HOPS", 0, minimum=0),
            log_format=os.environ.get("FRUIT_FLY_LOG_FORMAT", "text"),
            log_level=os.environ.get("FRUIT_FLY_LOG_LEVEL", "INFO"),
        )