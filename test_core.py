#!/usr/bin/env python3
"""
Unit test untuk fungsi-fungsi inti PRATYAKSA
Jalankan: ENV=development python test_core.py
"""
import sys
import os
import numpy as np

# Pastikan environment development terdeteksi
os.environ.setdefault("ENV", "development")
os.environ.setdefault("PRATYAKSA_API_KEYS", "test-key")

# Tambahkan root proyek ke sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.app import (
    resolve_risk,
    enforce_hierarchy,
    DigitalTwin,
    DriftDetector,
    FITUR_KOLOM,
    LABEL_NAMES,
    WARNING_THRESH,
    CRITICAL_THRESH
)


def test_resolve_risk():
    """Uji resolusi konflik XGBoost vs LSTM"""
    # Kasus 1: agreement — kedua model prediksi NORMAL
    r = resolve_risk(0, 100)
    assert r["final_class"] == 0
    assert r["model_agreement"] == True
    print("  ✅ resolve_risk — agreement NORMAL")

    # Kasus 2: agreement — kedua model prediksi CRITICAL
    r = resolve_risk(2, 10)
    assert r["final_class"] == 2
    assert r["model_agreement"] == True
    print("  ✅ resolve_risk — agreement CRITICAL")

    # Kasus 3: disagreement — XGB NORMAL, LSTM CRITICAL → resolved CRITICAL
    r = resolve_risk(0, 10)
    assert r["final_class"] == 2
    assert r["model_agreement"] == False
    print("  ✅ resolve_risk — disagreement resolved to worst")

    # Kasus 4: disagreement — XGB WARNING, LSTM NORMAL → resolved WARNING
    r = resolve_risk(1, 100)
    assert r["final_class"] == 1
    assert r["model_agreement"] == False
    print("  ✅ resolve_risk — disagreement XGB worse")


def test_enforce_hierarchy():
    """Uji enforcement hierarki RUL"""
    preds = {
        'RUL_pump_seal_main': 50,
        'RUL_hydraulic_pump': 30,
        'RUL_hydraulic_system': 100
    }
    h = enforce_hierarchy(preds)
    # Part tidak boleh > component
    assert h['RUL_pump_seal_main'] <= h['RUL_hydraulic_pump']
    # Component tidak boleh > system
    assert h['RUL_hydraulic_pump'] <= h['RUL_hydraulic_system']
    print("  ✅ enforce_hierarchy — hierarchy maintained")


def test_digital_twin():
    """Uji Digital Twin physics models"""
    dt = DigitalTwin()
    # Buat dummy features (37 zeros, indeks sesuai FITUR_KOLOM)
    features = [0.0] * len(FITUR_KOLOM)
    # Set beberapa nilai spesifik
    # payload_tonnage, road_grade_pct, haul_distance_km, vibration_z_g, hydraulic_main_pump_pressure_bar
    # Cari indeksnya
    feat_idx = {name: i for i, name in enumerate(FITUR_KOLOM)}
    features[feat_idx['payload_tonnage']] = 40
    features[feat_idx['road_grade_pct']] = 5
    features[feat_idx['haul_distance_km']] = 3
    features[feat_idx['vibration_z_g']] = 4.5
    features[feat_idx['hydraulic_main_pump_pressure_bar']] = 250

    cross = dt.cross_check(features, 'haul_truck')
    assert 'brake_twin_rul' in cross
    assert 'bearing_twin_rul' in cross
    assert 'hydraulic_twin_rul' in cross

    # Bearing dengan vibration 4.5 harusnya 12 jam
    assert cross['bearing_twin_rul'] == 12.0
    print("  ✅ DigitalTwin — cross_check OK")


def test_drift_detector():
    """Uji Drift Detector"""
    dd = DriftDetector(
        baseline_mean=[0.0] * len(FITUR_KOLOM),
        baseline_std=[1.0] * len(FITUR_KOLOM),
        threshold=3.0
    )
    # Data normal — tidak ada drift
    normal = np.random.randn(10, len(FITUR_KOLOM))
    result = dd.check(normal)
    assert not result['drift_detected']
    print("  ✅ DriftDetector — no drift detected")

    # Data dengan drift (mean = 5)
    drifted = np.random.randn(10, len(FITUR_KOLOM)) + 5.0
    result = dd.check(drifted)
    assert result['drift_detected']
    assert result['n_drifted'] > 0
    print("  ✅ DriftDetector — drift detected")


if __name__ == "__main__":
    print("🔍 PRATYAKSA Core Logic Unit Tests\n")
    test_resolve_risk()
    test_enforce_hierarchy()
    test_digital_twin()
    test_drift_detector()
    print("\n✅ Semua unit test lulus!")