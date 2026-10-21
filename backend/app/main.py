"""FastAPI application.

Run from the repository root:
    uvicorn backend.app.main:app --reload
Then open http://127.0.0.1:8000/docs for interactive API documentation.

With FRUIT_FLY_STATIC_DIR pointing at a built frontend (frontend/dist), the same
server also serves the web app at /, which is how the Docker image runs.

Experiments are stored in a database (FRUIT_FLY_DATABASE_URL) and run either in
this process (FRUIT_FLY_QUEUE=thread, the default) or by separate worker
processes reading a Redis queue (FRUIT_FLY_QUEUE=redis; see worker.py).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from . import logs
from .config import Settings
from .events import LocalBus, RedisBus
from .jobs import JobQueue, RedisQueue, ThreadQueue
from .db import make_sessionmaker
from .model import ModelStore
from .metrics import Metrics, install as install_metrics
from .ratelimit import make_rate_limiter
from .routers import circuit, experiments, odours, protocols, sweeps
from .services import create_job_service

log = logging.getLogger("fruit_fly.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logs.configure(settings.log_format, settings.log_level)
        # Load once; every request shares these read-only objects.
        store = ModelStore(settings)
        in_process = settings.queue == "thread"
        jobs, engine = create_job_service(settings, store if in_process else None, metrics=metrics)
        queue: JobQueue = (ThreadQueue(jobs.execute, settings.max_workers) if in_process
                           else RedisQueue(settings.redis_url, settings.job_timeout_s))
        jobs.queue = queue
        jobs.events = LocalBus() if in_process else RedisBus(settings.redis_url)
        if in_process:
            requeued, failed = jobs.recover_after_restart()
            if requeued or failed:
                log.warning("after restart: %d experiments re-queued, %d marked failed", requeued, failed)
        else:
            # Queued jobs survive in Redis; only experiments whose worker died need cleaning up.
            stale = jobs.fail_stale(settings.job_timeout_s)
            if stale:
                log.warning("%d experiments exceeded the job timeout and were marked failed", stale)
        app.state.settings = settings
        app.state.store = store
        app.state.jobs = jobs
        app.state.queue = queue
        app.state.events = jobs.events
        app.state.engine = engine
        app.state.sessions = make_sessionmaker(engine)
        app.state.rate_limiter = make_rate_limiter(settings.rate_limit, settings.queue, settings.redis_url)
        metrics.watch_database(app.state.sessions, storage_dir=settings.runs_dir)
        yield
        queue.shutdown()
        jobs.events.close()
        engine.dispose()

    app = FastAPI(
        title="fruit_fly API",
        version="0.2.0",
        description="Connectome-constrained model of olfactory conditioning in the "
                    "Drosophila mushroom body.",
        lifespan=lifespan,
    )
    metrics = Metrics()
    app.state.metrics = metrics
    install_metrics(app, metrics)
    # Around the routes and metrics, so every log line written for a request carries its id.
    app.add_middleware(logs.RequestIdMiddleware)
    # Spike and neuron tables are large, repetitive JSON: gzip shrinks them several-fold.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.get("/api/health", tags=["meta"])
    def health():
        store: ModelStore = app.state.store
        queue_ok = True
        if isinstance(app.state.queue, RedisQueue):
            try:
                queue_ok = app.state.queue.ping()
            except Exception:
                queue_ok = False
        return {"status": "ok" if queue_ok else "degraded", "neurons": len(store.network),
                "odours_loaded": store.has_odours, "queue": settings.queue, "queue_ok": queue_ok,
                "database": app.state.engine.dialect.name,
                "auth_required": settings.require_api_key, "rate_limit_per_min": settings.rate_limit}

    app.include_router(circuit.router)
    app.include_router(odours.router)
    app.include_router(experiments.router)
    app.include_router(protocols.router)
    app.include_router(sweeps.router)

    if settings.static_dir is not None:
        mount_frontend(app, settings.static_dir)
    return app


def mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend. Must be registered after the API routes,
    because its catch-all route would otherwise shadow them."""
    root = static_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"{index} not found; build the frontend with `npm run build`")

    # HEAD too: link checkers, CDNs and `curl -I` use it; FastAPI's @app.get alone answers 405.
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")   # unknown API route
        target = (root / path).resolve()
        # Refuse anything outside the frontend folder (e.g. /../backend/app/config.py).
        if path and target.is_relative_to(root) and target.is_file():
            # Vite puts a content hash in asset file names, so they never change.
            immutable = target.parent == root / "assets"
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        # Anything else is a page of the app: always revalidate index.html.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()