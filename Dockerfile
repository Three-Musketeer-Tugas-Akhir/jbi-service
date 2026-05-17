# ============================================================
# JBI Detection & Segmentation API — Dockerfile (CPU)
# ============================================================
# For GPU support: docker build -f Dockerfile.gpu .
# ============================================================

# --- Stage 1: Build dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system deps needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install into a virtualenv
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# --- Stage 2: Runtime ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code and entry points
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY scripts/ ./scripts/
COPY run.py .

# Create storage directories
RUN mkdir -p storage/uploads storage/outputs model_weights

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Start via run.py (reads ENVIRONMENT from .env / env vars)
CMD ["python", "run.py"]
