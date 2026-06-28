FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install specific versions aligned with the host environment to prevent PyArrow crashes
RUN pip install --no-cache-dir pandas==2.3.3 fastparquet==2026.5.0 redis==8.0.0 numpy==2.4.6

# Copy simulator script
COPY simulator /app/simulator

# Execute simulator
CMD ["python", "simulator/stream_simulator.py"]