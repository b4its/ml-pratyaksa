# PRATYAKSA API — Panduan Konsumsi Data

Dokumen ini untuk **teman** yang ingin mengambil data prediktif maintenance dari server PRATYAKSA. Tidak perlu clone repo — cukup akses via HTTP.

---

## 📡 Koneksi Dasar

| Item | Nilai |
|------|-------|
| **API URL** | `http://192.168.1.90:6000` |
| **API Key** | `dev-key-pratyaksa` |
| **Header Auth** | `X-API-Key` |
| **Interval Data** | Setiap **5 detik** (real-time) |
| **Jumlah Asset** | 6 unit alat berat |

---

## 🔐 Autentikasi

Semua endpoint **wajib** header `X-API-Key` **kecuali** `/health` dan `/metrics`.

```
X-API-Key: dev-key-pratyaksa
```

> ⚠️ Jika lupa kirim header → response `401` / `403`.

---

## 📋 Daftar Endpoint

### GET — Tidak Perlu Auth

| Endpoint | Fungsi |
|----------|--------|
| `GET /health` | Cek koneksi & status server |

### GET — Perlu Auth

| Endpoint | Fungsi |
|----------|--------|
| `GET /features` | Daftar semua sensor (37 fitur) |
| `GET /fleet` | Status real-time semua alat |
| `GET /result/{asset_id}` | Detail prediksi per alat |
| `GET /openapi.json` | Spek OpenAPI (untuk generate code) |
| `GET /metrics` | Metrik Prometheus |

### POST — Perlu Auth

| Endpoint | Fungsi |
|----------|--------|
| `POST /predict` | Kirim data sensor → dapat prediksi |
| `POST /workorder` | Buat rekomendasi work order |
| `POST /reload-models` | Reload model tanpa restart |

---

## 🚀 Contoh Curl

### 1. Cek Koneksi

```bash
curl http://192.168.1.90:6000/health
```

Response:
```json
{
  "status": "ok",
  "redis": "ok",
  "postgres": "ok",
  "experts_loaded": ["bulldozer","haul_truck","excavator","wheel_loader"],
  "model_version": "2.0.0"
}
```

---

### 2. Status Semua Alat (Fleet)

```bash
curl http://192.168.1.90:6000/fleet \
  -H "X-API-Key: dev-key-pratyaksa"
```

Response:
```json
{
  "fleet": [
    {
      "asset_id": "WA600-001",
      "equipment_type": "wheel_loader",
      "risk_level": "NORMAL",
      "lstm_rul_hours": 316.2,
      "rul_uncertainty": 29.3,
      "model_agreement": true,
      "drift_detected": false,
      "processed_at": 1782582644.29
    }
  ],
  "total": 6
}
```

> 🔄 **Polling endpoint ini tiap 5 detik** untuk dashboard real-time.

---

### 3. Detail Per Alat

```bash
curl http://192.168.1.90:6000/result/WA600-001 \
  -H "X-API-Key: dev-key-pratyaksa"
```

Asset ID yang tersedia:
| Asset ID | Tipe |
|----------|------|
| `WA600-001` | wheel_loader |
| `HD785-001` | haul_truck |
| `HD785-002` | haul_truck |
| `D155-001` | bulldozer |
| `PC2000-001` | excavator |
| `DT-001` | haul_truck (dari POST /predict) |

---

### 4. Prediksi Kerusakan (POST)

```bash
curl -X POST http://192.168.1.90:6000/predict \
  -H "X-API-Key: dev-key-pratyaksa" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "DT-001",
    "equipment_type": "haul_truck",
    "timestamp": "2026-06-28T12:00:00Z",
    "features": [0.5,0.3,0.8,0.2,0.6,0.4,0.7,0.1,0.9,0.3,0.5,0.7,0.2,0.8,0.4,0.6,0.3,0.9,0.1,0.5,0.7,0.4,0.2,0.8,0.6,0.3,0.5,0.9,0.7,0.1,0.4,0.6,0.5,0.3,0.8,0.2,0.6]
  }'
```

> ⚠️ `features[]` harus berisi **tepat 37 angka** (float).

---

### 5. Buat Work Order

```bash
curl -X POST "http://192.168.1.90:6000/workorder?component=brake&risk_score=0.85" \
  -H "X-API-Key: dev-key-pratyaksa"
```

Parameter:
- `component` — `brake`, `hydraulic`, `engine`, `transmission`
- `risk_score` — ambang batas (0.0 – 1.0)

---

### 6. Daftar Sensor

```bash
curl http://192.168.1.90:6000/features \
  -H "X-API-Key: dev-key-pratyaksa"
```

---

### 7. Spek OpenAPI (buat generate client code)

```bash
curl http://192.168.1.90:6000/openapi.json \
  -H "X-API-Key: dev-key-pratyaksa"
```

Bisa di-parse Rust dengan crate `progenitor` atau `openapi-generator`.

---

## 🦀 Integrasi Rust + Nuxt.js

### Arsitektur

```
┌──────────────────────┐   setiap 5 detik   ┌──────────────────┐
│  PRATYAKSA API       │◄──────────────────│  Rust Middleware   │
│  192.168.1.90:6000   │   polling fleet     │  (cache + proxy)  │
└──────────────────────┘                    └────────┬─────────┘
                                                     │
                                                     ▼
                                            ┌──────────────────┐
                                            │  Nuxt.js Frontend │
                                            │  (dashboard)     │
                                            └──────────────────┘
```

### Rust — Polling tiap 5 detik

```rust
use reqwest::Client;
use tokio::time::{interval, Duration};
use std::collections::HashMap;

const URL: &str = "http://192.168.1.90:6000";
const KEY: &str = "dev-key-pratyaksa";
const HEADER: &str = "X-API-Key";

async fn poll_fleet(client: &Client) -> Result<Value, reqwest::Error> {
    let resp = client
        .get(format!("{}/fleet", URL))
        .header(HEADER, KEY)
        .send()
        .await?;
    resp.json::<Value>().await
}

#[tokio::main]
async fn main() {
    let client = Client::new();
    let mut tick = interval(Duration::from_secs(5));
    loop {
        tick.tick().await;
        match poll_fleet(&client).await {
            Ok(data) => { /* update cache */ }
            Err(e) => eprintln!("Polling error: {}", e),
        }
    }
}
```

### Nuxt.js — Ambil dari Rust sendiri

```javascript
// composables/usePratyaksa.js
export const usePratyaksa = () => {
  const fleet = ref([])

  const fetchFleet = async () => {
    fleet.value = await $fetch('/api/fleet') // dari Rust, bukan langsung
  }

  onMounted(() => {
    fetchFleet()
    setInterval(fetchFleet, 5000)
  })

  return { fleet }
}
```

---

## 📊 Field Penting buat Dashboard

### Dari `/fleet`

| Field | Tipe | Kegunaan |
|-------|------|----------|
| `asset_id` | string | Nama alat |
| `equipment_type` | string | Tipe alat |
| `risk_level` | string | `NORMAL` / `WARNING` / `CRITICAL` |
| `lstm_rul_hours` | float | Sisa umur pakai (jam) |
| `rul_uncertainty` | float | Error margin RUL |
| `model_agreement` | bool | XGBoost vs LSTM cocok? |
| `drift_detected` | bool | Apakah sensor mulai drift? |

### Dari `/result/{asset_id}` (tambahan)

| Field | Tipe | Kegunaan |
|-------|------|----------|
| `xgb_anomaly_class` | int | 0=NORMAL, 1=WARNING, 2=CRITICAL |
| `digital_twin` | object | Simulasi komponen (brake, bearing, hydraulic) |
| `drift_status.drifted_features` | array | Sensor yang mengalami drift |
| `latency_ms` | float | Waktu proses prediksi |

---

## ⚠️ Troubleshooting

| Gejala | Penyebab | Solusi |
|--------|----------|--------|
| `ERR_UNSAFE_PORT` | Browser blokir port 6000 | Pakai Firefox, atau ganti port API |
| `Connection refused` | Server mati / beda jaringan | Cek `ping 192.168.1.90` |
| `401 Unauthorized` | Header key salah/lupa | Kasih `-H "X-API-Key: dev-key-pratyaksa"` |
| `curl: (3) URL rejected` | Terminal salah copy | Tulis dalam **satu baris**, jangan pakai `\` |
| Timeout | Firewall / proxy | Cek `telnet 192.168.1.90 6000` |

---

## ✅ Quick Checklist

- [ ] Bisa `ping 192.168.1.90`
- [ ] `curl http://192.168.1.90:6000/health` → `{"status":"ok"}`
- [ ] `curl http://192.168.1.90:6000/fleet -H "X-API-Key: dev-key-pratyaksa"` → daftar asset
- [ ] Buat Rust middleware polling tiap 5 detik
- [ ] Nuxt.js ambil dari Rust, bukan langsung

---

> **PRATYAKSA v2.0.0** — AIoT Predictive Maintenance
