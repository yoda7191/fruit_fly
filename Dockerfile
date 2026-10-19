# syntax=docker/dockerfile:1
#
# fruit_fly: one image for the API (+ web app) and for queue workers.
#
#   docker build -t fruit_fly .
#   docker run --rm -p 8000:8000 fruit_fly          -> http://localhost:8000
#       (single container: SQLite database, experiments run inside the API)
#   docker compose up --build                   -> PostgreSQL + Redis + API + workers
#   docker build --build-arg CIRCUIT=flywire -t fruit_fly .
#       (the real FlyWire circuit: downloads ~270 MB of tables and ~400 MB of neuron
#        skeletons at build time, extracts the circuit and builds the 3D anatomy files;
#        FlyWire data is CC BY-NC 4.0, see README "Data and credits")
#
# Four build stages; only the last one ends up in the image:
#   frontend  Node: build the web app (frontend/dist)
#   core      C++ toolchain: run the C++ unit tests, build the fruit_fly Python wheel
#   data      synthetic test circuit + DoOR odour tables (+ the FlyWire circuit)
#   runtime   slim Python: wheel + backend + built frontend + data, non-root

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=22
# Circuit the server loads: "synthetic" (small test circuit) or "flywire" (the real one).
ARG CIRCUIT=synthetic
# User id the server runs as (Hugging Face Spaces runs containers as 1000).
ARG APP_UID=10001

# ------------------------------------------------------------------ frontend
FROM node:${NODE_VERSION}-slim AS frontend
WORKDIR /src/frontend
# Dependencies first, so this layer is cached until the lockfile changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------ core
FROM python:${PYTHON_VERSION}-slim AS core
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CMakeLists.txt pyproject.toml ./
COPY core/ core/
COPY fruit_fly/ fruit_fly/
COPY tests/ tests/
# Fail the build if the C++ unit tests fail.
RUN cmake -S . -B build-tests -DFRUIT_FLY_BUILD_CLI=OFF \
 && cmake --build build-tests -j"$(nproc)" \
 && ./build-tests/test_unit
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

# ------------------------------------------------------------------ data
FROM python:${PYTHON_VERSION}-slim AS data
ARG CIRCUIT
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY scripts/make_synthetic_mb.py scripts/download_door.sh scripts/
RUN python scripts/make_synthetic_mb.py data/synthetic \
 && bash scripts/download_door.sh data/raw/door
# Real circuit: download FlyWire, extract the mushroom body circuit, build the brain
# regions and neuron shapes for the 3D view, and drop the raw downloads.
COPY scripts/download_data.sh scripts/extract_mb_circuit.py scripts/known_*.csv \
     scripts/download_skeletons.py scripts/build_anatomy.py scripts/
RUN if [ "$CIRCUIT" = "flywire" ]; then \
      pip install --no-cache-dir pandas \
      && bash scripts/download_data.sh data/raw \
      && python scripts/extract_mb_circuit.py --raw data/raw --out data/flywire \
      && python scripts/download_skeletons.py --neurons data/flywire/mb_neurons.csv --out data/raw/skeletons \
      && python scripts/build_anatomy.py --circuit data/flywire --skeletons data/raw/skeletons \
           --neuropils data/raw/neuropils.zip \
      && test -s data/flywire/mb_morphology.bin \
      && test -s data/flywire/mb_morphology.bin.gz \
      && test -s data/flywire/brain_regions.json \
      && test -s data/flywire/brain_regions.json.gz \
      && rm -rf data/raw/*.csv.gz data/raw/skeletons data/raw/neuropils.zip; \
    elif [ "$CIRCUIT" != "synthetic" ]; then \
      echo "CIRCUIT must be synthetic or flywire, got $CIRCUIT" >&2; exit 1; \
    fi

# ------------------------------------------------------------------ runtime
FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY --from=core /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl -r backend/requirements.txt \
 && rm -rf /tmp/wheels

COPY backend/ backend/
COPY --from=frontend /src/frontend/dist frontend/dist
COPY --from=data /src/data data
# Default model parameters per circuit (FlyWire: calibrated by the validation suite).
COPY deploy/params/ params/

# Database and spike recordings live here; mount a volume to keep them.
ARG APP_UID
ARG CIRCUIT
RUN useradd --create-home --uid ${APP_UID} fruit_fly \
 && mkdir -p /var/lib/fruit_fly/runs \
 && chown -R fruit_fly /var/lib/fruit_fly
VOLUME /var/lib/fruit_fly
USER fruit_fly

# Point FRUIT_FLY_CIRCUIT_DIR at a mounted volume to serve the real FlyWire circuit.
ENV FRUIT_FLY_CIRCUIT_DIR=/app/data/${CIRCUIT} \
    FRUIT_FLY_PARAMS_FILE=/app/params/${CIRCUIT}.json \
    FRUIT_FLY_DOOR_DIR=/app/data/raw/door \
    FRUIT_FLY_STATIC_DIR=/app/frontend/dist \
    FRUIT_FLY_STORAGE_DIR=/var/lib/fruit_fly/runs \
    FRUIT_FLY_DATABASE_URL=sqlite:////var/lib/fruit_fly/fruit_fly.db \
    FRUIT_FLY_MAX_WORKERS=2 \
    FRUIT_FLY_LOG_FORMAT=json

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# One API process is enough: simulation runs in worker threads (FRUIT_FLY_QUEUE=thread)
# or in separate worker containers (FRUIT_FLY_QUEUE=redis, command: python -m backend.app.worker).
# The app writes its own access log (JSON, with request ids), so uvicorn's is off.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]