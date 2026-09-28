# Multi-stage build for Market Data Service (Lean Production Image)

# Build arguments
ARG VERSION=0.3.6

# Stage 1: Builder
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
RUN pip install --upgrade pip wheel && \
    pip install --no-cache-dir -r requirements.txt


# Stage 2: Runtime (Lean)
FROM python:3.12-slim

WORKDIR /app

# Build arguments available in runtime stage
ARG VERSION=0.3.6
LABEL version="${VERSION}"
LABEL description="Market Data Service - Timezone-aware, bootstrap integrated"

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code and symbol list
COPY app ./app
COPY overlap.txt ./

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check using Python (no curl dependency)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
