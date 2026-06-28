FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system dependencies (sebagai root)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (sebagai root)
COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Buat user dan grup non-root
RUN addgroup --system appgroup && adduser --system --group appuser

# Copy kode aplikasi
COPY bot/ /app/bot/

# Ubah kepemilikan folder ke appuser
RUN chown -R appuser:appgroup /app

# Pindah ke user non-root
USER appuser

CMD ["python", "bot/bot.py"]