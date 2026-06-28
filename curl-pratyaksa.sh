#!/bin/bash
# PRATYAKSA API — curl commands for Rust + Nuxt.js dashboard
# Ganti IP jika berbeda
URL="http://192.168.1.90:6000"
KEY="dev-key-pratyaksa"
HEADER="X-API-Key: $KEY"

echo "============================================"
echo "  PRATYAKSA API — COPY PASTE CURL"
echo "============================================"
echo ""

# ===================== GET (tanpa auth) =====================

echo "=== 1. Health Check (tanpa key) ==="
echo "curl $URL/health"
echo ""

echo "=== 2. Prometheus Metrics (tanpa key) ==="
echo "curl $URL/metrics"
echo ""

# ===================== GET (dengan auth) =====================

echo "=== 3. Daftar Sensor ==="
echo "curl $URL/features -H \"$HEADER\""
echo ""

echo "=== 4. Status Semua Alat (Fleet) ==="
echo "curl $URL/fleet -H \"$HEADER\""
echo ""

echo "=== 5. Detail Per Asset ==="
for asset in WA600-001 HD785-001 D155-001 HD785-002 PC2000-001; do
    echo "curl $URL/result/$asset -H \"$HEADER\""
done
echo ""

echo "=== 6. OpenAPI Spek ==="
echo "curl $URL/openapi.json -H \"$HEADER\""
echo ""

# ===================== POST (dengan auth) =====================

echo "=== 7. Prediksi Kerusakan ==="
echo 'curl -X POST '$URL'/predict \'
echo '  -H "'$HEADER'" \'
echo '  -H "Content-Type: application/json" \'
echo '  -d '\''{'
echo '    "asset_id": "DT-001",'
echo '    "equipment_type": "haul_truck",'
echo '    "timestamp": "2026-06-28T12:00:00Z",'
echo '    "features": [0.5,0.3,0.8,0.2,0.6,0.4,0.7,0.1,0.9,0.3,0.5,0.7,0.2,0.8,0.4,0.6,0.3,0.9,0.1,0.5,0.7,0.4,0.2,0.8,0.6,0.3,0.5,0.9,0.7,0.1,0.4,0.6,0.5,0.3,0.8,0.2,0.6]'
echo '  }'\'''
echo ""

echo "=== 8. Buat Work Order ==="
echo 'curl -X POST "'$URL'/workorder?component=brake&risk_score=0.85" \'
echo '  -H "'$HEADER'"'
echo ""

echo "=== 9. Reload Model ==="
echo 'curl -X POST '$URL'/reload-models -H "'$HEADER'"'
echo ""

echo "============================================"
echo "  NOTES:"
echo "  - Polling /fleet tiap 5 detik untuk dashboard"
echo "  - /health cek koneksi, no key needed"
echo "  - POST /predict butuh 37 angka di features[]"
echo "  - Semua GET endpoint ⬆ bisa dipanggil mandiri"
echo "============================================"
