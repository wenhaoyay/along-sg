# Base images are pinned to exact version tags. Pinning digests as well
# (`image:tag@sha256:...`) would make rebuilds byte-for-byte identical, but
# these tags are re-pushed with OS security patches, which a digest would
# then miss until bumped by hand - so it is left out on purpose.
FROM node:24.22.1-alpine3.24 AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_PUBLIC_API_BASE_URL=""
RUN npm run build

FROM python:3.12.15-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.lock ./backend/requirements.lock
RUN python -m pip install --no-cache-dir -r backend/requirements.lock
RUN groupadd --system --gid 10001 along \
    && useradd --system --uid 10001 --gid along --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin along
COPY backend/app ./backend/app
COPY backend/scripts/ingest_osm_pois.py ./backend/scripts/ingest_osm_pois.py
# Package the tracked static backend data as one bounded set. .dockerignore
# excludes local/generated SQLite artefacts so persistent databases and WAL
# files are never copied into the image by this directory-level COPY.
COPY backend/data ./backend/data
# The catalogue is built here, at image build time, from the bundled OSM
# capture: the container needs no persistent disk, starts with every outlet
# on its first request, and each deploy serves exactly the data it was built
# with. Only /app/data is writable by the app user (SQLite needs the
# directory for its journal).
RUN mkdir -p /app/data \
    && python backend/scripts/ingest_osm_pois.py \
        --input backend/data/singapore-osm-pois.json --database /app/data/errands.db \
    && chown -R along:along /app/data
COPY --from=frontend-build /build/frontend/out ./frontend/out
# FORWARDED_ALLOW_IPS: uvicorn takes the client address from X-Forwarded-For
# only when the connection comes from one of these (the platform's proxy, on
# a private network), reading the header from the right, so a client cannot
# choose its own address for the rate limiter by sending the header itself.
ENV PYTHONPATH=/app/backend \
    SERVE_FRONTEND_DIR=/app/frontend/out \
    DATABASE_PATH=/app/data/errands.db \
    ANALYTICS_DATABASE_PATH=/app/data/analytics.db \
    FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
USER along
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
# One worker: rate limits and caches are per process, and a free instance
# has a fraction of one CPU.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers"]
