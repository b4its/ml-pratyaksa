#!/bin/sh
# PRATYAKSA API Tester — jalankan dari dalam container api-tester
API="${API_URL:-http://api:6000}"
KEY="${API_KEY:-dev-key-pratyaksa}"

echo "╔══════════════════════════════════════════════╗"
echo "║        PRATYAKSA API TESTER                  ║"
echo "╠══════════════════════════════════════════════╣"
echo "║ API: $API"
echo "║ KEY: $KEY"
echo "╚══════════════════════════════════════════════╝"
echo ""

case "${1:-help}" in
  health)
    echo "── Health Check ──"
    curl -s "$API/health" | jq .
    ;;

  features)
    echo "── Daftar Sensor ──"
    curl -s -H "X-API-Key: $KEY" "$API/features" | jq .
    ;;

  fleet)
    echo "── Status Semua Alat ──"
    curl -s -H "X-API-Key: $KEY" "$API/fleet" | jq .
    ;;

  result)
    asset="${2:-HD785-001}"
    echo "── Detail Asset: $asset ──"
    curl -s -H "X-API-Key: $KEY" "$API/result/$asset" | jq .
    ;;

  predict)
    asset="${2:-DT-001}"
    etype="${3:-haul_truck}"
    echo "── Prediksi: $asset ($etype) ──"
    curl -s -X POST "$API/predict" \
      -H "X-API-Key: $KEY" \
      -H "Content-Type: application/json" \
      -d "{
        \"asset_id\": \"$asset\",
        \"equipment_type\": \"$etype\",
        \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
        \"features\": [0.5,0.3,0.8,0.2,0.6,0.4,0.7,0.1,0.9,0.3,0.5,0.7,0.2,0.8,0.4,0.6,0.3,0.9,0.1,0.5,0.7,0.4,0.2,0.8,0.6,0.3,0.5,0.9,0.7,0.1,0.4,0.6,0.5,0.3,0.8,0.2,0.6]
      }" | jq .
    ;;

  workorder)
    component="${2:-brake}"
    risk="${3:-0.85}"
    echo "── Buat Work Order: $component (risk=$risk) ──"
    curl -s -X POST "$API/workorder?component=$component&risk_score=$risk" \
      -H "X-API-Key: $KEY" | jq .
    ;;

  explain)
    pid="${2:-latest}"
    echo "── SHAP Explanation: $pid ──"
    curl -s -H "X-API-Key: $KEY" "$API/explain/$pid" | jq .
    ;;

  reload)
    echo "── Reload Model ──"
    curl -s -X POST "$API/reload-models" -H "X-API-Key: $KEY" | jq .
    ;;

  metrics)
    echo "── Prometheus Metrics ──"
    curl -s "$API/metrics"
    ;;

  watch)
    interval="${2:-5}"
    endpoint="${3:-fleet}"
    echo "── Polling /$endpoint setiap ${interval}s ──"
    echo "Press Ctrl+C to stop"
    echo ""
    while true; do
      echo "--- $(date -u +%H:%M:%S) ---"
      curl -s -H "X-API-Key: $KEY" "$API/$endpoint" | jq -c .
      sleep "$interval"
    done
    ;;

  help|*)
    echo "Penggunaan: api-test.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  health                   Health check"
    echo "  features                 Daftar sensor"
    echo "  fleet                    Status semua alat"
    echo "  result [asset_id]        Detail asset (default: HD785-001)"
    echo "  predict [id] [type]      Prediksi kerusakan"
    echo "  workorder [comp] [risk]  Buat work order"
    echo "  explain [prediction_id]  SHAP explanation"
    echo "  reload                   Reload model"
    echo "  metrics                  Prometheus metrics"
    echo "  watch [interval] [ep]    Polling endpoint tiap N detik"
    echo ""
    echo "Contoh:"
    echo "  api-test.sh fleet"
    echo "  api-test.sh result D155-001"
    echo "  api-test.sh watch 3 fleet"
    ;;
esac
