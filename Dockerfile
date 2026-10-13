# Multi-stage build: compile the TanStack/React frontend.
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build && test -f dist/client/index.html

# CPU-only Python runtime for Render and compatible container hosts.
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PORT=10000
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch>=2.2.0" \
    && python -m pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY reports/ ./reports/
COPY --from=frontend-build /app/ui/dist ./ui/dist

EXPOSE 10000
CMD ["sh", "-c", "python -m uvicorn src.context_compressor.service.api:app --host 0.0.0.0 --port ${PORT:-10000}"]
