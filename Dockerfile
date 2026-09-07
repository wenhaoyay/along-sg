FROM node:24-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_PUBLIC_API_BASE_URL=""
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app ./backend/app
COPY backend/scripts/prepare_beta_data.py ./backend/scripts/prepare_beta_data.py
COPY backend/data/singapore-osm-pois.json ./backend/data/singapore-osm-pois.json
COPY --from=frontend-build /build/frontend/out ./frontend/out
ENV PYTHONPATH=/app/backend SERVE_FRONTEND_DIR=/app/frontend/out DATABASE_PATH=/data/errands.db ANALYTICS_DATABASE_PATH=/data/analytics.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["sh", "-c", "python backend/scripts/prepare_beta_data.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
