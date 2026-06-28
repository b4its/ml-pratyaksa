# Setup Guide — PRATYAKSA from Scratch

Panduan untuk **developer yang baru pertama kali clone** repository ini dan ingin menjalankan seluruh stack dari nol hingga testing endpoint.

---

## Daftar Isi

- [Prasyarat](#prasyarat)
- [Fase 1 — Clone & Environment](#fase-1--clone--environment)
- [Fase 2 — Build & Start Docker Stack](#fase-2--build--start-docker-stack)
- [Fase 3 — Fix Data Directory Ownership](#fase-3--fix-data-directory-ownership)
- [Fase 4 — Build & Start Dev Container](#fase-4--build--start-dev-container)
- [Fase 5 — Generate Dataset & Scaler](#fase-5--generate-dataset--scaler)
- [Fase 6 — Generate LSTM Model Artifacts](#fase-6--generate-lstm-model-artifacts)
- [Fase 7 — Restart API & Start Simulator](#fase-7--restart-api--start-simulator)
- [Fase 8 — Testing Endpoint](#fase-8--testing-endpoint)
- [Akses Layanan](#akses-layanan)
- [Troubleshooting](#troubleshooting)
- [Arsitektur File](#arsitektur-file)

---

## Prasyarat

- **Docker** + **Docker Compose** (plugin)
- **Git**
- **Port tersedia:** 6000, 6001, 6050, 6080, 6090, 6883, 8888

Cek:

```bash
docker --version && docker compose version
```

---

## Fase 1 — Clone & Environment

```bash
git clone https://github.com/virgiawanprima/pratyaksa.git
cd pratyaksa
cp .env.example .env
```

Edit `.env` — isi minimal:

```env
POSTGRES_PASSWORD=pratyaksa_secret
PRATYAKSA_API_KEYS=dev-key-pratyaksa
```

`TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` opsional.

---

## Fase 2 — Build & Start Docker Stack

```bash
docker compose up -d
```

Tunggu ~30 detik, cek status:

```bash
docker compose ps
```

**Hasil yang diharapkan:**

| Container | Status | Keterangan |
|-----------|--------|------------|
| `pratyaksa-redis` | `Up (healthy)` | ✅ |
| `pratyaksa-postgres` | `Up (healthy)` | ✅ |
| `pratyaksa-mlflow` | `Up` | ✅ |
| `pratyaksa-prometheus` | `Up (healthy)` | ✅ |
| `pratyaksa-grafana` | `Up (healthy)` | ✅ |
| `mosquitto` | `Up (healthy)` | ✅ |
| `pratyaksa-bridge` | `Up` | ✅ |
| `pratyaksa-api` | `Restarting` | ⚠️ **Normal** — restart terus karena artifact belum ada |
| `pratyaksa-airflow-*` | `starting` | ⏳ Wajar, butuh ~30 detik |

> **Jangan khawatir** dengan `pratyaksa-api` yang restart. Ini akan diperbaiki setelah artifact di-generate.

```bash
# Verifikasi service dasar sudah jalan
docker compose ps | grep -c -E "(redis|postgres|grafana|prometheus|mosquitto|bridge).*Up"
# Output: 6
```

---

## Fase 3 — Fix Data Directory Ownership

**PENTING:** Setelah `docker compose up` pertama, direktori `data/` akan dibuat oleh Docker sebagai **root**. Akibatnya user di dev container tidak bisa menulis dataset ke direktori tersebut.

```bash
# Cek kepemilikan
ls -la data/ | head -3
# Jika milik root: drwxr-xr-x root root ...

# Fix kepemilikan
sudo chown -R $USER:$USER data/
```

Verifikasi:

```bash
ls -la data/ | head -3
# Output: drwxr-xr-x vxm vxm ...
```

---

## Fase 4 — Build & Start Dev Container

Container `pratyaksa-dev` digunakan untuk menjalankan notebook Jupyter dan generate artifact.

### Build

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml build dev
```

Proses build ~5 menit (menginstall tensorflow, keras, xgboost, jupyterlab, dll).

### Start

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d dev
```

Verifikasi:

```bash
docker compose ps | grep dev
# Output: pratyaksa-dev ... Up ...
```

---

## Fase 5 — Generate Dataset & Scaler

Notebook `data_pipeline.ipynb` mensintesis data sensor 30 unit alat berat (~148rb baris).

### 5a. Jalankan Jupyter Lab

```bash
docker exec -it pratyaksa-dev jupyter lab \
  --ip=0.0.0.0 --no-browser --allow-root --port=8888
```

Output akan menampilkan URL dengan token:

```
http://127.0.0.1:8888/lab?token=abc123...
```

Buka URL tersebut di browser.

### 5b. Run Notebook

1. Navigasi ke `notebooks/data_pipeline.ipynb`
2. Klik **Run → Run All Cells**
3. Proses ~3 menit

### 5c. Hasil

Setelah selesai, file baru akan muncul:

| File | Ukuran | Fungsi |
|------|--------|--------|
| `data/dataset_pratyaksa_noisy.parquet` | ~35 MB | Dataset lengkap 30 unit |
| `data/dataset_pratyaksa_pilot.parquet` | ~600 KB | Subset 5 unit (untuk demo/simulator) |
| `artifacts/artifact_scaler.pkl` | ~1.5 KB | StandardScaler 37 fitur |
| `artifacts/artifact_split.json` | ~2 KB | Metadata split |
| `artifacts/split_{train,val,test}.parquet` | ~35 MB | Split dataset |
| `artifacts/sample_weights.npy` | ~460 KB | Sample weights |
| `artifacts/*.npy` | ~410 MB | Tensor LSTM |

> File `.parquet`, `.pkl`, `.keras`, `.npy` tidak ter-track git (di `.gitignore`). Harus digenerate ulang setiap clone.

---

## Fase 6 — Generate LSTM Model Artifacts

Dibutuhkan 4 file LSTM expert (`artifact_lstm_*.keras`) agar API bisa berfungsi penuh.

### Opsi A: Generate Dummy (5 detik) ⭐ Rekomendasi

Cocok untuk testing dan development. Buat file `generate_artifacts.py` di root proyek dengan isi berikut:

```python
import joblib
import numpy as np
from pathlib import Path
from sklearn.preprocessing import StandardScaler
import tensorflow as tf
from keras import Model
from keras.layers import LSTM, Dense, Dropout, BatchNormalization
from keras.saving import save_model, register_keras_serializable

ART = Path("artifacts")
N_FEATURES = 37
TIME_STEPS = 20
EXPERT_TYPES = ["bulldozer", "haul_truck", "excavator", "wheel_loader"]

if not (ART / "artifact_scaler.pkl").exists():
    scaler = StandardScaler()
    scaler.fit(np.random.randn(100, N_FEATURES))
    joblib.dump(scaler, ART / "artifact_scaler.pkl")
    print("[OK] artifact_scaler.pkl")
else:
    print("[SKIP] artifact_scaler.pkl already exists")

@register_keras_serializable()
def asymmetric_loss(y_true, y_pred):
    error = y_pred - y_true
    abs_err = tf.abs(error)
    critical = tf.cast(y_true < 100.0, tf.float32)
    safe = tf.cast(y_true > 200.0, tf.float32)
    overpred = tf.cast(error > 0, tf.float32)
    factor = (1.0 + 19.0 * critical * overpred + 4.0 * safe * (1 - overpred))
    return tf.reduce_mean(factor * abs_err)

@register_keras_serializable()
class PRATYAKSAExpert(Model):
    def __init__(self, time_steps=20, n_features=37, **kwargs):
        super().__init__(**kwargs)
        self.time_steps = time_steps
        self.n_features = n_features
        self.lstm1 = LSTM(128, return_sequences=True)
        self.bn1 = BatchNormalization()
        self.drop1 = Dropout(0.3)
        self.lstm2 = LSTM(64, return_sequences=True)
        self.bn2 = BatchNormalization()
        self.drop2 = Dropout(0.2)
        self.lstm3 = LSTM(32, return_sequences=False)
        self.drop3 = Dropout(0.2)
        self.dense_shared = Dense(16, activation="relu")
        self.mc_dropout = Dropout(0.1)
        self.head_rul = Dense(1, activation="linear", name="RUL_hours")

    def call(self, inputs, training=False, mc_sample=False):
        x = self.lstm1(inputs)
        x = self.bn1(x, training=training)
        x = self.drop1(x, training=training)
        x = self.lstm2(x)
        x = self.bn2(x, training=training)
        x = self.drop2(x, training=training)
        x = self.lstm3(x)
        x = self.drop3(x, training=training)
        x = self.dense_shared(x)
        x = self.mc_dropout(x, training=(training or mc_sample))
        return {"RUL_hours": self.head_rul(x)}

    def get_config(self):
        return {"time_steps": self.time_steps, "n_features": self.n_features}

    @classmethod
    def from_config(cls, config):
        return cls(**config)

for etype in EXPERT_TYPES:
    path = ART / f"artifact_lstm_{etype}.keras"
    if path.exists():
        print(f"[SKIP] {path.name} already exists")
        continue
    model = PRATYAKSAExpert(TIME_STEPS, N_FEATURES)
    dummy_in = np.random.randn(1, TIME_STEPS, N_FEATURES).astype(np.float32)
    model(dummy_in)
    model.compile(optimizer="adam", loss=asymmetric_loss)
    model.save(str(path))
    print(f"[OK] {path.name}")
```

Jalankan script di **dalam dev container**:

```bash
docker exec pratyaksa-dev python /workspace/generate_artifacts.py
```

### Opsi B: Full Training (30 menit)

Di Jupyter Lab, buka `notebooks/model_pipeline.ipynb` → **Run → Run All Cells**.

Proses:
1. **Cell 3** — Training XGBoost classifier
2. **Cell 4** — SHAP explainability analysis
3. **Cell 5** — MoE sequence preparation per equipment type
4. **Cell 6** — Training 4 LSTM experts (100 epoch each)
5. **Cell 7** — Export deploy metadata & drift baseline

Hasil logging otomatis ke **MLflow** di `http://localhost:6050`.

### Verifikasi

```bash
ls -la artifacts/ | grep -E "scaler|lstm"
# Output:
# -rw-r--r-- artifact_scaler.pkl
# -rw-r--r-- artifact_lstm_bulldozer.keras
# -rw-r--r-- artifact_lstm_haul_truck.keras
# -rw-r--r-- artifact_lstm_excavator.keras
# -rw-r--r-- artifact_lstm_wheel_loader.keras
```

---

## Fase 7 — Restart API & Start Simulator

```bash
# Restart API dengan artifact baru
docker compose restart api

# Tunggu API sehat (~10 detik)
sleep 10
docker compose ps | grep api
# Output: pratyaksa-api ... Up (healthy) ...

# Jalankan simulator (dev profile)
docker compose --profile dev up -d simulator

# Cek log simulator
docker logs pratyaksa-simulator --tail 5
# Output: [INFO] Streaming ... -> Redis Streams
```

---

## Fase 8 — Testing Endpoint

### 8a. Health Check (public)

```bash
curl localhost:6000/health | python3 -m json.tool
```

**Response:**
```json
{
    "status": "ok",
    "redis": "ok",
    "postgres": "ok",
    "experts_loaded": ["bulldozer", "haul_truck", "excavator", "wheel_loader"],
    "model_version": "2.0.0"
}
```

### 8b. Lihat Daftar 37 Fitur

```bash
curl -s localhost:6000/features -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool | head -20
```

**Response:**
```json
{
    "features": [
        {"index": 0, "name": "engine_rpm", "group": "engine"},
        {"index": 1, "name": "engine_load_pct", "group": "engine"},
        ...
    ],
    "total": 37
}
```

### 8c. Prediksi Manual

Kirim sensor reading untuk **bulldozer** (37 fitur):

```bash
curl -s -X POST localhost:6000/predict \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key-pratyaksa" \
  -d '{
    "asset_id": "D155-001",
    "equipment_type": "bulldozer",
    "timestamp": "2026-06-29T12:00:00Z",
    "features": [850,65,82,110,72,90,105,3200,1200,3.5,1.2,380,42,25,97,105,4.2,1.8,150,35,68,0.72,0.03,0.25,12.5,8.2,1.04,320,280,12,10,0.98,0.92,2.1,50,0.02,0.15]
  }' | python3 -m json.tool
```

**Response:**
```json
{
    "prediction_id": "...",
    "asset_id": "D155-001",
    "equipment_type": "bulldozer",
    "xgb_anomaly_class": 0,
    "xgb_anomaly_label": "NORMAL",
    "lstm_rul_hours": 4250.5,
    "rul_uncertainty": 320.2,
    "risk_level": "NORMAL",
    "risk_class": 0,
    "model_agreement": true,
    "lstm_hydraulic_system": 4100.0,
    "lstm_hydraulic_pump": 4300.0,
    "lstm_pump_seal": 3900.0,
    "lstm_brake_system": 3800.0,
    "lstm_brake_caliper": 4000.0,
    "lstm_brake_pad": 3500.0,
    "lstm_steering_system": 4500.0,
    "digital_twin": {...},
    "drift_status": {...},
    "latency_ms": 45.2
}
```

> **Catatan:** Angka RUL dan komponen tergantung model. Jika pakai dummy, akan berbeda dari full training.

### 8d. Cek Hasil Terakhir Asset

```bash
curl -s localhost:6000/result/D155-001 -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool
```

### 8e. Fleet Status (setelah simulator berjalan beberapa saat)

```bash
curl -s localhost:6000/fleet -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool
```

**Response (setelah simulator streaming):**
```json
{
    "fleet": [
        {
            "asset_id": "D155-001",
            "equipment_type": "bulldozer",
            "risk_level": "NORMAL",
            "lstm_rul_hours": 4250.5,
            "rul_uncertainty": 320.2,
            "model_agreement": true,
            "drift_detected": false,
            "processed_at": "2026-06-29T12:00:05Z"
        },
        ...
    ],
    "total": 5
}
```

### 8f. SHAP Explain

Gunakan `prediction_id` dari response prediksi:

```bash
curl -s localhost:6000/explain/<PREDICTION_ID> \
  -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool
```

**Response:**
```json
{
    "prediction_id": "...",
    "waterfall": "<base64-encoded PNG>"
}
```

### 8g. Work Order Recommendation

```bash
curl -s -X POST "localhost:6000/workorder?component=brake_system&risk_score=0.85" \
  -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool
```

**Response (jika risk > 0.7):**
```json
{
    "status": "created",
    "recommendation": {
        "risk_score": 0.85,
        "component": "brake_system",
        "parts": [...],
        "estimated_total_cost": 12500000,
        "action": "Replace brake pads and inspect caliper",
        "comparison": "..."
    }
}
```

### 8h. Reload Models (hot-swap tanpa restart)

```bash
curl -s -X POST localhost:6000/reload-models \
  -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool
```

**Response:**
```json
{
    "status": "success",
    "message": "Models hot-swapped successfully."
}
```

### 8i. Swagger UI

Buka di browser: http://localhost:6000/docs

---

## Akses Layanan

| Layanan | URL | Kredensial |
|---------|-----|------------|
| **FastAPI Docs** | http://localhost:6000/docs | — |
| **FastAPI OpenAPI** | http://localhost:6000/openapi.json | — |
| **Grafana** | http://localhost:6001 | `admin` / `pratyaksa2026` |
| **MLflow** | http://localhost:6050 | — |
| **Airflow** | http://localhost:6080 | — |
| **Prometheus** | http://localhost:6090 | — |
| **Jupyter Lab** | http://localhost:8888 | token dari log |

---

## Troubleshooting

### API restart terus

```
docker logs pratyaksa-api --tail 20
```

**Cek:** Apakah error `FileNotFoundError: artifact_scaler.pkl`?

**Solusi:** Generate ulang artifact (Fase 5 + Fase 6).

### Health status "degraded"

```json
{"status": "degraded", "experts_loaded": []}
```

**Penyebab:** LSTM expert models belum ada atau corrupt.

**Solusi:** Generate ulang file `.keras` (Fase 6).

### `/fleet` kosong

```json
{"fleet": [], "total": 0}
```

**Penyebab:** Simulator belum jalan.

**Solusi:** `docker compose --profile dev up -d simulator`, tunggu 10 detik.

### Permission denied di `data/`

```
touch: cannot touch '/workspace/data/test_write': Permission denied
```

**Penyebab:** Direktori `data/` milik root.

**Solusi:** `sudo chown -R $USER:$USER data/` (Fase 3).

### Build dev container gagal

```
E: Unable to locate package docker-compose-v2
```

**Solusi:** Pastikan `docker-container/dev/Dockerfile` tidak menyertakan `docker.io` dan `docker-compose-v2` di apt install.

### Can't connect to Redis/Postgres

**Penyebab:** Servis belum siap saat API mulai.

**Solusi:** `depends_on: condition: service_healthy` akan otomatis menunggu. Cek log:

```bash
docker compose logs postgres --tail 5
docker compose logs redis --tail 5
```

---

## Cheat Sheet — Perintah Cepat

```bash
# Start all services
docker compose up -d

# Fix data ownership (setelah first up)
sudo chown -R $USER:$USER data/

# Start dev container
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d dev

# Jupyter Lab
docker exec -it pratyaksa-dev jupyter lab --ip=0.0.0.0 --no-browser --allow-root --port=8888

# Generate artifacts (di dev container)
docker exec pratyaksa-dev python /workspace/generate_artifacts.py

# Restart API
docker compose restart api

# Start simulator
docker compose --profile dev up -d simulator

# Check logs
docker compose logs api --tail 20
docker compose logs simulator --tail 20

# Health check
curl localhost:6000/health

# Prediksi
curl -s -X POST localhost:6000/predict \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key-pratyaksa" \
  -d '{"asset_id":"D155-001","equipment_type":"bulldozer","timestamp":"2026-06-29T12:00:00Z","features":[850,65,82,110,72,90,105,3200,1200,3.5,1.2,380,42,25,97,105,4.2,1.8,150,35,68,0.72,0.03,0.25,12.5,8.2,1.04,320,280,12,10,0.98,0.92,2.1,50,0.02,0.15]}' | python3 -m json.tool

# Fleet
curl -s localhost:6000/fleet -H "X-API-Key: dev-key-pratyaksa" | python3 -m json.tool

# Stop everything
docker compose down
```
