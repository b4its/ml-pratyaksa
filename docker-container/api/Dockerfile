# ===== PRATYAKSA API Dockerfile (fixed: user permission, healthcheck) =====
FROM python:3.11-slim

WORKDIR /app

# AUDIT FIX: Install system deps as root first
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api /app/api
COPY schema_config.json .

# AUDIT FIX: Create non-root user after installation
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 6000

# Healthcheck (AUDIT H6)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:6000/health || exit 1

# Execute from the /app root, calling the app module inside the api directory
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "6000", "--workers", "1"]