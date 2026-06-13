# ══════════════════════════════════════════════════════════════════════════════
# AMFI v4 — Multi-stage Dockerfile
#   Stage 1 (frontend-builder) : Node 24 → vite build → /app/dist
#   Stage 2 (runtime)          : Python 3.11-slim → FastAPI backend
#                                 + copies /app/dist from stage 1
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Build React / Vite frontend ──────────────────────────────────────
FROM node:24-slim AS frontend-builder

WORKDIR /build

# Cache node_modules layer separately from src changes
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline

# Copy source and build
COPY frontend/ ./
RUN npm run build
# Output: /build/dist

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    openssh-client \
    ansible \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — cached unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Copy built frontend from stage 1 into the expected location
COPY --from=frontend-builder /build/dist ./frontend/dist

# Create data directory for SQLite persistence
RUN mkdir -p /data && chmod 777 /data

# Environment defaults (override via docker run -e or compose env_file)
ENV DATABASE_URL="sqlite+aiosqlite:////data/amfi_v4.db" \
    API_HOST="0.0.0.0" \
    API_PORT="8000"

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "run.py"]
