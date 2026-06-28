import joblib
import numpy as np
import json
from pathlib import Path

class EdgePreprocessor:
    def __init__(self, scaler_path=None):
        if scaler_path is None:
            base = Path(__file__).resolve().parent.parent
            scaler_path = base / "artifacts" / "artifact_scaler.pkl"
        self.scaler = joblib.load(str(scaler_path))

        meta_path = Path(__file__).resolve().parent.parent / "artifacts" / "artifact_deploy_meta.json"
        with open(meta_path) as f:
            meta = json.load(f)
        self.feature_names = meta["FITUR_KOLOM"]
        self.n_features = len(self.feature_names)

    def transform(self, raw_data: dict) -> np.ndarray:
        feat_list = [raw_data.get(name, 0.0) for name in self.feature_names]
        X = np.array(feat_list).reshape(1, -1)
        return self.scaler.transform(X).astype(np.float32)