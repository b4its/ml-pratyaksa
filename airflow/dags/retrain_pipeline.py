"""
PRATYAKSA MLOps: Automated Weekly Retraining Pipeline v2.1
- Menggunakan PRATYAKSAExpert asli
- Menyimpan model dengan nama yang sesuai
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

# Airflow
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.http.operators.http import SimpleHttpOperator

# Keras 3
from keras import Model
from keras.layers import LSTM, Dense, Dropout, BatchNormalization
from keras.saving import load_model, save_model, register_keras_serializable

ARTIFACTS_DIR = Path("/opt/airflow/artifacts")
TEMP_DIR = Path("/tmp")
logger = logging.getLogger("airflow.task")

default_args = {
    "owner": "mlops_team",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


# ─── PRATYAKSA Expert (sama persis dengan api/app.py) ───
@register_keras_serializable()
class PRATYAKSAExpert(Model):
    def __init__(self, time_steps, n_features, hierarchy_targets,
                 name="pratyaksa_expert", **kwargs):
        super().__init__(name=name, **kwargs)
        self.time_steps = time_steps
        self.n_features = n_features
        self.hierarchy_targets = list(hierarchy_targets)

        self.lstm1 = LSTM(128, return_sequences=True)
        self.bn1 = BatchNormalization()
        self.drop1 = Dropout(0.3)
        self.lstm2 = LSTM(64, return_sequences=True)
        self.bn2 = BatchNormalization()
        self.drop2 = Dropout(0.2)
        self.lstm3 = LSTM(32, return_sequences=False)
        self.drop3 = Dropout(0.2)
        self.dense_shared = Dense(16, activation='relu')
        self.mc_dropout = Dropout(0.1)
        self.head_rul = Dense(1, activation='linear', name='RUL_hours')
        self.heads = {
            tgt: Dense(1, activation='linear', name=tgt.replace('RUL_', '').lower())
            for tgt in hierarchy_targets
        }

    def _backbone(self, inputs, training=False):
        x = self.lstm1(inputs)
        x = self.bn1(x, training=training)
        x = self.drop1(x, training=training)
        x = self.lstm2(x)
        x = self.bn2(x, training=training)
        x = self.drop2(x, training=training)
        x = self.lstm3(x)
        x = self.drop3(x, training=training)
        return self.dense_shared(x)

    def call(self, inputs, training=False, mc_sample=False):
        x = self._backbone(inputs, training=training)
        x = self.mc_dropout(x, training=(training or mc_sample))
        outputs = {'RUL_hours': self.head_rul(x)}
        for tgt, head in self.heads.items():
            outputs[tgt] = head(x)
        return outputs

    def get_config(self):
        cfg = super().get_config()
        cfg.update({
            'time_steps': self.time_steps,
            'n_features': self.n_features,
            'hierarchy_targets': self.hierarchy_targets,
        })
        return cfg

    @classmethod
    def from_config(cls, config):
        return cls(**config)


@dag(
    default_args=default_args,
    schedule_interval="0 0 * * 0",
    start_date=datetime(2026, 6, 1),
    catchup=False,
    tags=["pratyaksa", "mlops"],
)
def pratyaksa_retraining_pipeline():

    @task
    def extract_recent_telemetry():
        pg_hook = PostgresHook(postgres_conn_id="pratyaksa_db")
        sql = "SELECT * FROM sensor_readings WHERE time >= NOW() - INTERVAL '30 days'"
        df = pg_hook.get_pandas_df(sql)
        if len(df) < 500:
            raise ValueError(f"Hanya {len(df)} baris, minimal 500")
        filepath = TEMP_DIR / "latest_telemetry.parquet"
        df.to_parquet(filepath)
        return str(filepath)

    @task
    def retrain_xgboost(data_path: str):
        train_path = Path(data_path) if data_path else ARTIFACTS_DIR / "split_train.parquet"
        if not train_path.exists():
            train_path = ARTIFACTS_DIR / "split_train.parquet"
        if not train_path.exists():
            raise FileNotFoundError(f"Training data tidak ditemukan: {train_path}")
        df = pd.read_parquet(train_path)
        target_col = "label" if "label" in df.columns else "anomaly_class"
        X = df.drop(columns=[target_col])
        y = df[target_col]

        import joblib
        scaler_path = ARTIFACTS_DIR / "artifact_scaler.pkl"
        if scaler_path.exists():
            scaler = joblib.load(scaler_path)
            X_scaled = scaler.transform(X)
        else:
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

        X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2)
        num_classes = y.nunique()
        model = xgb.XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            objective="multi:softprob" if num_classes > 2 else "binary:logistic",
            eval_metric="mlogloss" if num_classes > 2 else "logloss",
            early_stopping_rounds=10
        )
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        model_path = ARTIFACTS_DIR / "artifact_xgb_model.json"
        model.save_model(str(model_path))
        return str(model_path)

    @task
    def retrain_lstm_experts(data_path: str):
        with open(ARTIFACTS_DIR / "artifact_deploy_meta.json") as f:
            meta = json.load(f)
        TIME_STEPS = meta["TIME_STEPS"]
        hierarchy_targets = meta.get("hierarchy_targets", [
            "RUL_hydraulic_system", "RUL_hydraulic_pump", "RUL_pump_seal_main",
            "RUL_brake_system", "RUL_brake_caliper", "RUL_brake_pad_rear",
            "RUL_steering_system"
        ])
        expert_types = meta.get("expert_types", ["haul_truck","excavator","bulldozer","wheel_loader"])

        X_path = ARTIFACTS_DIR / "X_train_lstm.npy"
        y_path = ARTIFACTS_DIR / "y_train_reg.npy"
        if not X_path.exists():
            raise FileNotFoundError("X_train_lstm.npy tidak ditemukan")
        X_all = np.load(X_path)
        y_rul = np.load(y_path)
        N_FEATURES = X_all.shape[2]

        model = PRATYAKSAExpert(TIME_STEPS, N_FEATURES, hierarchy_targets)
        model.compile(optimizer='adam', loss='mse')
        X_train, X_val, y_train, y_val = train_test_split(X_all, y_rul, test_size=0.2)
        model.fit(X_train, y_train, validation_data=(X_val, y_val), epochs=10, batch_size=32, verbose=1)

        saved = []
        for etype in expert_types:
            path = ARTIFACTS_DIR / f"artifact_lstm_{etype}.keras"
            save_model(model, str(path))
            saved.append(str(path))
        return saved

    @task
    def deploy_and_swap_metadata(xgb_path: str, lstm_paths: list):
        meta_path = ARTIFACTS_DIR / "artifact_deploy_meta.json"
        with open(meta_path) as f:
            meta = json.load(f)
        meta["model_version"] = f"3.4.{datetime.now().strftime('%Y%m%d')}"
        meta["last_retrained"] = datetime.now().isoformat()
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=4)
        return meta["model_version"]

    telemetry_path = extract_recent_telemetry()
    xgb_model_path = retrain_xgboost(telemetry_path)
    lstm_model_paths = retrain_lstm_experts(telemetry_path)
    version = deploy_and_swap_metadata(xgb_model_path, lstm_model_paths)

    trigger_hot_reload = SimpleHttpOperator(
        task_id="trigger_api_hot_reload",
        http_conn_id="pratyaksa_api",
        endpoint="reload-models",
        method="POST",
        headers={"X-API-Key": os.environ["PRATYAKSA_API_KEYS"]},
        log_response=True,
    )

    version >> trigger_hot_reload

pipeline = pratyaksa_retraining_pipeline()
