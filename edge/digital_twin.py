import json
from datetime import datetime
from pathlib import Path

class DigitalTwin:
    def __init__(self, meta_path=None):
        if meta_path is None:
            base = Path(__file__).resolve().parent.parent
            meta_path = base / "artifacts" / "artifact_deploy_meta.json"
        with open(meta_path) as f:
            self.meta = json.load(f)
        self.FITUR_KOLOM = self.meta["FITUR_KOLOM"]
        self.state = {
            "last_update": None,
            "health_score": 100,
            "alert_level": "normal"
        }

    def update(self, risk_score: float):
        self.state["last_update"] = datetime.utcnow().isoformat()
        self.state["health_score"] = max(0, 100 - risk_score * 10)
        if risk_score >= 0.8:
            self.state["alert_level"] = "critical"
        elif risk_score >= 0.5:
            self.state["alert_level"] = "warning"
        else:
            self.state["alert_level"] = "normal"
        return self.state.copy()

    def estimate_brake_rul(self, payload, grade, distance, cumulative_work=0.0):
        max_work = 800.0
        remaining = max(0.0, max_work - cumulative_work)
        work_rate = payload * grade * distance if (payload and grade and distance) else 1.0
        if work_rate < 1e-6:
            return max_work
        return min(remaining / work_rate, max_work)

    def estimate_bearing_rul(self, vibration_z):
        if vibration_z >= 5.0:
            return 0.0
        elif vibration_z >= 3.2:
            return 12.0
        elif vibration_z >= 1.4:
            return 72.0
        else:
            return 500.0

    def estimate_hydraulic_rul(self, pressure, nominal=280.0):
        drop = max(0.0, nominal - pressure)
        if drop > 80:
            return 0.0
        return (80 - drop) * 50 / 80

    def cross_check(self, raw_features: list) -> dict:
        feat_idx = {name: i for i, name in enumerate(self.FITUR_KOLOM)}
        def _get(name, default=0.0):
            idx = feat_idx.get(name)
            return raw_features[idx] if idx is not None else default
        return {
            "brake_twin_rul": self.estimate_brake_rul(
                _get('payload_tonnage'), _get('road_grade_pct'), _get('haul_distance_km')
            ),
            "bearing_twin_rul": self.estimate_bearing_rul(_get('vibration_z_g')),
            "hydraulic_twin_rul": self.estimate_hydraulic_rul(
                _get('hydraulic_main_pump_pressure_bar', 280.0)
            ),
        }