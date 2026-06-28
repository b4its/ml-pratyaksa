"""
PRATYAKSA Inference API v3.4
FastAPI + Redis Streams consumer + MC Dropout + Drift Detection + AuthN
+ P3: /explain endpoint (SHAP waterfall)
+ P4: /workorder endpoint (Prescriptive Recommendation)
+ Fixes: C1 (double resolve_risk), C7/H1 (DB write semaphore),
        H2 (fleet active set), H4 (feature index cache),
        P3 (explain base64), P4 (prescriptive engine)
"""
import asyncio
import base64
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
import redis.asyncio as aioredis
import xgboost as xgb
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

# Keras 3 Native Imports
import tensorflow as tf
from keras import Model
from keras.layers import LSTM, Dense, Dropout, BatchNormalization
from keras.saving import load_model, register_keras_serializable

from pydantic import BaseModel, Field

# Prescriptive engine (P4)
from .prescriptive import RecommendationEngine

# SHAP for explainability (P3)
import shap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Async Database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

from prometheus_fastapi_instrumentator import Instrumentator


# ---------- Custom loss function (sama persis dengan notebook) ----------
@register_keras_serializable()
def asymmetric_loss(y_true, y_pred):
    """
    Loss dua arah:
    - Overprediction (terlambat deteksi) saat RUL < 100h → penalty 20x
    - Underprediction (false alarm) saat RUL > 200h      → penalty 5x
    """
    error    = y_pred - y_true
    abs_err  = tf.abs(error)
    critical = tf.cast(y_true < 100.0, tf.float32)
    safe     = tf.cast(y_true > 200.0, tf.float32)
    overpred = tf.cast(error > 0, tf.float32)

    factor = (1.0
              + 19.0 * critical * overpred          # 20x saat RUL<100 & terlambat
              + 4.0  * safe     * (1 - overpred))   # 5x false alarm saat unit sehat
    return tf.reduce_mean(factor * abs_err)


# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pratyaksa")


# ---------- Auth ----------
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)
# AUDIT R2: hanya fallback jika ENV=development
if os.getenv("ENV") == "development":
    _VALID_KEYS = {"dev-key-pratyaksa"}
else:
    _VALID_KEYS = set(os.environ["PRATYAKSA_API_KEYS"].split(","))

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    if api_key not in _VALID_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key


# ---------- Paths & Metadata ----------
PROJECT_ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"

with open(ARTIFACTS_DIR / "artifact_deploy_meta.json") as f:
    META = json.load(f)

FITUR_KOLOM = META["FITUR_KOLOM"]
N_FEATURES = len(FITUR_KOLOM)
TIME_STEPS = META["TIME_STEPS"]
RUL_MAX = META["RUL_MAX"]
EXPERT_TYPES = META["expert_types"]
WARNING_THRESH = META.get("WARNING_THRESH", 72)
CRITICAL_THRESH = META.get("CRITICAL_THRESH", 24)
XGB_THRESHOLD = META.get("xgb_threshold", 0.5)
LABEL_NAMES = {0: "NORMAL", 1: "WARNING", 2: "CRITICAL"}
SCALER_CHECKSUM_EXPECTED = META.get("scaler_checksum")

with open(PROJECT_ROOT / "schema_config.json") as f:
    _SCHEMA = json.load(f)
FITUR_KE_GRUP: Dict[str, str] = {
    ft: grp for grp, fts in _SCHEMA.items() for ft in fts
}

def _get_group(feat_name: str) -> str:
    return FITUR_KE_GRUP.get(feat_name, "unknown")

# Cache indeks fitur
_FEAT_IDX = {name: i for i, name in enumerate(FITUR_KOLOM)}


# ---------- PRATYAKSA Expert (Keras Model) ----------
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


# ---------- Drift Detector ----------
class DriftDetector:
    def __init__(self, baseline_mean: list, baseline_std: list, threshold: float = 3.0):
        self.mean = np.array(baseline_mean, dtype=np.float32)
        self.std = np.array(baseline_std, dtype=np.float32)
        self.thr = threshold

    def check(self, features_scaled: np.ndarray) -> dict:
        batch_mean = features_scaled.mean(axis=0)
        z_scores = (batch_mean - self.mean) / (self.std + 1e-8)
        drifted_idx = np.where(np.abs(z_scores) > self.thr)[0]
        return {
            "drift_detected": bool(len(drifted_idx) > 0),
            "drifted_features": [FITUR_KOLOM[i] for i in drifted_idx],
            "max_z_score": float(np.max(np.abs(z_scores))),
            "n_drifted": int(len(drifted_idx)),
        }


# ---------- Digital Twin ----------
class DigitalTwin:
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

    def cross_check(self, raw_features: list, equipment_type: str) -> dict:
        def _get(name, default=0.0):
            idx = _FEAT_IDX.get(name)
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


# ---------- Hierarchy enforcement ----------
def enforce_hierarchy(preds: dict) -> dict:
    chains = [
        ('RUL_pump_seal_main', 'RUL_hydraulic_pump', 'RUL_hydraulic_system'),
        ('RUL_brake_pad_rear', 'RUL_brake_caliper', 'RUL_brake_system'),
    ]
    for part, comp, subs in chains:
        if all(k in preds for k in [part, comp, subs]):
            preds[comp] = min(preds[comp], preds[subs])
            preds[part] = min(preds[part], preds[comp])
    return preds


# ---------- XGB / LSTM conflict resolution ----------
def resolve_risk(xgb_class: int, rul_hours: float) -> dict:
    lstm_class = (2 if rul_hours < CRITICAL_THRESH
                  else 1 if rul_hours < WARNING_THRESH
                  else 0)
    final_class = max(xgb_class, lstm_class)
    agreement = (xgb_class == lstm_class)
    if not agreement:
        logger.warning(
            f"Model disagreement — XGB={LABEL_NAMES[xgb_class]}, "
            f"LSTM={LABEL_NAMES[lstm_class]} (RUL={rul_hours:.1f}h) → "
            f"resolved={LABEL_NAMES[final_class]}"
        )
    return {
        "final_class": final_class,
        "final_label": LABEL_NAMES[final_class],
        "xgb_class": xgb_class,
        "lstm_class": lstm_class,
        "model_agreement": agreement,
    }


# ---------- Async DB Batcher ----------
class AsyncDBBatcher:
    def __init__(self, engine: AsyncEngine, write_func, max_size: int = 50, flush_interval: float = 2.0):
        self.engine = engine
        self.write_func = write_func
        self.buffer: deque[dict] = deque()
        self.max_size = max_size
        self.flush_interval = flush_interval
        self._flushing = False
        self._task = asyncio.create_task(self._periodic_flush())
        logger.info(f"DBBatcher started (max_size={max_size}, interval={flush_interval:.1f}s)")

    def push(self, result: dict) -> None:
        self.buffer.append(result)
        if len(self.buffer) >= self.max_size and not self._flushing:
            asyncio.ensure_future(self._flush())

    async def _periodic_flush(self):
        while True:
            try:
                await asyncio.sleep(self.flush_interval)
                if self.buffer and not self._flushing:
                    await self._flush()
            except asyncio.CancelledError:
                if self.buffer:
                    await self._flush()
                raise
            except Exception:
                logger.exception("DBBatcher periodic flush failed")

    async def _flush(self):
        if self._flushing or not self.buffer:
            return
        self._flushing = True
        try:
            batch = list(self.buffer)
            self.buffer.clear()
            for result in batch:
                try:
                    await self.write_func(result)
                except Exception as e:
                    logger.error(f"DB write failed for {result.get('asset_id')}: {e}")
        finally:
            self._flushing = False


# ---------- Global services ----------
_scaler: object = None
_xgb_model: object = None
_expert_models: Dict[str, PRATYAKSAExpert] = {}
_drift_detector: Optional[DriftDetector] = None
_digital_twin = DigitalTwin()
_redis: Optional[aioredis.Redis] = None
_db_engine: Optional[AsyncEngine] = None
_db_batcher: Optional[AsyncDBBatcher] = None
_db_write_semaphore = asyncio.Semaphore(50)
_shap_explainer = None   # AUDIT R8: cache explainer


# ---------- Database write helpers ----------
async def _write_sensor_reading_to_db(reading: dict, features: list) -> None:
    if _db_engine is None:
        return
    async with _db_write_semaphore:
        raw_feat_names = FITUR_KOLOM[:32]
        cols = ['time', 'asset_id'] + raw_feat_names
        vals = ['to_timestamp(:ts)', ':asset_id'] + [f':f{i}' for i in range(32)]
        sql = text(f"""
            INSERT INTO sensor_readings ({', '.join(cols)})
            VALUES ({', '.join(vals)})
            ON CONFLICT DO NOTHING
        """)

        # Tangani timestamp yang mungkin berupa string ISO atau float epoch
        ts_val = reading.get('timestamp', time.time())
        if isinstance(ts_val, str):
            from datetime import datetime
            try:
                ts_val = datetime.fromisoformat(ts_val).timestamp()
            except ValueError:
                ts_val = time.time()
        else:
            ts_val = float(ts_val)

        params = {
            'ts': ts_val,
            'asset_id': reading['asset_id']
        }
        for i in range(32):
            params[f'f{i}'] = features[i]
        async with _db_engine.begin() as conn:
            await conn.execute(sql, params)


async def _write_prediction_to_db(result: dict) -> None:
    if _db_engine is None:
        raise RuntimeError("DB engine unavailable")
    async with _db_write_semaphore:
        drift = result.get("drift_status", {})
        twin = result.get("digital_twin", {})

        sql = text("""
            INSERT INTO predictions (
                time, asset_id, equipment_type,
                xgb_anomaly_class, xgb_anomaly_label,
                lstm_rul_hours, rul_uncertainty,
                rul_hydraulic_system, rul_hydraulic_pump, rul_pump_seal_main,
                rul_brake_system, rul_brake_caliper, rul_brake_pad_rear,
                rul_steering_system,
                risk_level, risk_class, model_agreement,
                brake_twin_rul, bearing_twin_rul, hydraulic_twin_rul,
                drift_detected, drift_max_z_score, drift_n_features,
                latency_ms, api_version
            ) VALUES (
                to_timestamp(:processed_at), :asset_id, :equipment_type,
                :xgb_anomaly_class, :xgb_anomaly_label,
                :lstm_rul_hours, :rul_uncertainty,
                :rul_hydraulic_system, :rul_hydraulic_pump, :rul_pump_seal_main,
                :rul_brake_system, :rul_brake_caliper, :rul_brake_pad_rear,
                :rul_steering_system,
                :risk_level, :risk_class, :model_agreement,
                :brake_twin_rul, :bearing_twin_rul, :hydraulic_twin_rul,
                :drift_detected, :drift_max_z_score, :drift_n_features,
                :latency_ms, :api_version
            )
        """)
        async with _db_engine.begin() as conn:
            await conn.execute(sql, {
                "processed_at": result["processed_at"],
                "asset_id": result["asset_id"],
                "equipment_type": result["equipment_type"],
                "xgb_anomaly_class": result["xgb_anomaly_class"],
                "xgb_anomaly_label": result["xgb_anomaly_label"],
                "lstm_rul_hours": result["lstm_rul_hours"],
                "rul_uncertainty": result["rul_uncertainty"],
                "rul_hydraulic_system": result.get("RUL_hydraulic_system", 0.0),
                "rul_hydraulic_pump": result.get("RUL_hydraulic_pump", 0.0),
                "rul_pump_seal_main": result.get("RUL_pump_seal_main", 0.0),
                "rul_brake_system": result.get("RUL_brake_system", 0.0),
                "rul_brake_caliper": result.get("RUL_brake_caliper", 0.0),
                "rul_brake_pad_rear": result.get("RUL_brake_pad_rear", 0.0),
                "rul_steering_system": result.get("RUL_steering_system", 0.0),
                "risk_level": result["risk_level"],
                "risk_class": result["risk_class"],
                "model_agreement": result["model_agreement"],
                "brake_twin_rul": twin.get("brake_twin_rul", 0.0),
                "bearing_twin_rul": twin.get("bearing_twin_rul", 0.0),
                "hydraulic_twin_rul": twin.get("hydraulic_twin_rul", 0.0),
                "drift_detected": drift.get("drift_detected", False),
                "drift_max_z_score": drift.get("max_z_score", 0.0),
                "drift_n_features": drift.get("n_drifted", 0),
                "latency_ms": result.get("latency_ms", 0.0),
                "api_version": META.get("model_version", "unknown"),
            })


# ---------- In‑memory sequence buffer ----------
MAX_HISTORY = TIME_STEPS
_buffer: Dict[str, deque] = {}
MAX_ASSETS = 200

def get_buffer(asset_id: str) -> deque:
    if asset_id not in _buffer:
        if len(_buffer) >= MAX_ASSETS:
            oldest = next(iter(_buffer))
            del _buffer[oldest]
        _buffer[asset_id] = deque(maxlen=TIME_STEPS)
    return _buffer[asset_id]

def get_or_init_buffer(asset_id: str, features: list) -> np.ndarray:
    buf = get_buffer(asset_id)
    buf.append(features)
    while len(buf) < TIME_STEPS:
        buf.appendleft(buf[0] if buf else features)
    return np.array(buf, dtype=np.float32)


# ---------- Dropout flag computation ----------
FLATLINE_WIN = 10
FLATLINE_THR = 1e-6

def compute_dropout_flags(asset_id: str) -> dict:
    buf = get_buffer(asset_id)
    flags = {}
    if len(buf) < FLATLINE_WIN:
        return flags
    recent = np.array(list(buf)[-FLATLINE_WIN:])
    for flag_name, feat_name in [
        ('oil_particle_count_iso_dropout_flag', 'oil_particle_count_iso'),
        ('payload_tonnage_dropout_flag', 'payload_tonnage'),
        ('cycle_time_minutes_dropout_flag', 'cycle_time_minutes'),
        ('haul_distance_km_dropout_flag', 'haul_distance_km'),
        ('oil_change_flag_dropout_flag', 'oil_change_flag'),
    ]:
        flag_idx = _FEAT_IDX.get(flag_name)
        feat_idx = _FEAT_IDX.get(feat_name)
        if flag_idx is not None and feat_idx is not None:
            if recent[:, feat_idx].std() < FLATLINE_THR:
                flags[flag_idx] = 1.0
            else:
                flags[flag_idx] = 0.0
    return flags


# ---------- Single‑forward pass for LSTM ----------
def _predict_expert_single_pass(expert: PRATYAKSAExpert, X_seq: np.ndarray, n_iter: int = 20):
    X_tiled = np.tile(X_seq, (n_iter, 1, 1))
    preds = expert(X_tiled, training=False, mc_sample=True)
    rul_samples = preds['RUL_hours'].numpy().flatten()
    rul_mean = float(rul_samples.mean())
    rul_std = float(rul_samples.std())
    hier_keys = ['RUL_hydraulic_system', 'RUL_hydraulic_pump', 'RUL_pump_seal_main',
                 'RUL_brake_system', 'RUL_brake_caliper', 'RUL_brake_pad_rear',
                 'RUL_steering_system']
    hier = {}
    for key in hier_keys:
        if key in preds:
            hier[key] = float(preds[key].numpy().flatten().mean())
        else:
            hier[key] = 0.0
    return rul_mean, rul_std, hier


# ---------- Core inference ----------
async def process_sensor_reading(reading: dict, xgb_class_override: Optional[int] = None) -> dict:
    asset_id = reading["asset_id"]
    etype = reading["equipment_type"]
    features = reading["features"]

    if len(features) != N_FEATURES:
        raise ValueError("Feature count mismatch")
    if etype not in _expert_models:
        raise ValueError("Unknown equipment type")

    t_start = time.perf_counter()
    flag_updates = compute_dropout_flags(asset_id)
    for idx, val in flag_updates.items():
        features[idx] = val

    raw_arr = np.array(features, dtype=np.float32).reshape(1, -1)
    scaled_arr = _scaler.transform(raw_arr)

    if xgb_class_override is not None:
        xgb_class = xgb_class_override
    else:
        xgb_proba = _xgb_model.predict_proba(scaled_arr)
        xgb_class = int(np.where(xgb_proba[0, 2] >= XGB_THRESHOLD, 2, np.argmax(xgb_proba[0, :2])))

    seq_raw = get_or_init_buffer(asset_id, features)
    seq_scaled = _scaler.transform(seq_raw)
    X_seq = seq_scaled[np.newaxis, ...]

    expert = _expert_models[etype]
    rul_mean, rul_std, hier_preds_raw = _predict_expert_single_pass(expert, X_seq, n_iter=20)
    rul_hours = float(np.clip(rul_mean, 0, RUL_MAX))
    hier_preds = enforce_hierarchy(hier_preds_raw)
    risk = resolve_risk(xgb_class, rul_hours)

    drift_status = {}
    if _drift_detector:
        drift_status = _drift_detector.check(scaled_arr)

    twin_est = _digital_twin.cross_check(features, etype)
    latency_ms = (time.perf_counter() - t_start) * 1000

    result = {
        "asset_id": asset_id,
        "equipment_type": etype,
        "timestamp": reading.get("timestamp", ""),
        "xgb_anomaly_class": xgb_class,
        "xgb_anomaly_label": LABEL_NAMES[xgb_class],
        "lstm_rul_hours": rul_hours,
        "rul_uncertainty": float(rul_std),
        "risk_level": risk["final_label"],
        "risk_class": risk["final_class"],
        "model_agreement": risk["model_agreement"],
        **hier_preds,
        "digital_twin": twin_est,
        "drift_status": drift_status,
        "processed_at": time.time(),
        "latency_ms": latency_ms,
    }
    return result


# ---------- Batched XGBoost helper ----------
def _batch_xgboost_predict(features_batch: list) -> list:
    if not features_batch:
        return []
    scaled = _scaler.transform(np.array(features_batch))
    probas = _xgb_model.predict_proba(scaled)
    classes = []
    for p in probas:
        if p[2] >= XGB_THRESHOLD:
            classes.append(2)
        else:
            classes.append(int(np.argmax(p[:2])))
    return classes


# ---------- Stream consumer ----------
STREAM_PREFIX = "stream:sensors:"

async def consume_sensor_streams() -> None:
    if _redis is None:
        return
    group_name = "pratyaksa-analytics"
    consumer_name = f"worker-{os.getpid()}"

    for etype in EXPERT_TYPES:
        try:
            await _redis.xgroup_create(f"{STREAM_PREFIX}{etype}", group_name, id='0', mkstream=True)
        except Exception:
            pass

    while True:
        try:
            streams = {f"{STREAM_PREFIX}{etype}": '>' for etype in EXPERT_TYPES}
            messages = await _redis.xreadgroup(
                groupname=group_name, consumername=consumer_name,
                streams=streams, count=20, block=1000,
            )
            if not messages:
                continue

            readings = []
            msg_acks = []
            for stream_key, msgs in messages:
                for msg_id, fields in msgs:
                    try:
                        reading = {
                            "asset_id": fields[b"asset_id"].decode(),
                            "equipment_type": fields[b"equipment_type"].decode(),
                            "timestamp": fields[b"timestamp"].decode(),
                            "features": json.loads(fields[b"features"]),
                        }
                        readings.append(reading)
                        msg_acks.append((stream_key, msg_id))
                    except Exception as e:
                        logger.error(f"Malformed stream message: {e}")

            if not readings:
                continue

            raw_feats_batch = [r["features"] for r in readings]
            xgb_classes = _batch_xgboost_predict(raw_feats_batch)

            for idx, reading in enumerate(readings):
                result = await process_sensor_reading(reading, xgb_class_override=xgb_classes[idx])

                await _redis.setex(f"result:{reading['asset_id']}", 3600, json.dumps(result))
                await _redis.publish("predictions", json.dumps(result))
                await _redis.sadd("active_assets", reading["asset_id"])

                if _db_engine is not None:
                    asyncio.create_task(_write_sensor_reading_to_db(reading, reading["features"]))
                    _db_batcher.push(result)

            for stream_key, msg_id in msg_acks:
                await _redis.xack(stream_key, group_name, msg_id)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Stream consumer loop error")
            await asyncio.sleep(5)


# ---------- Lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scaler, _xgb_model, _expert_models, _drift_detector, _redis, _db_engine, _db_batcher, _shap_explainer

    logger.info("PRATYAKSA API starting up...")

    # Scaler
    _scaler = joblib.load(ARTIFACTS_DIR / "artifact_scaler.pkl")
    checksum = float(_scaler.mean_.sum())
    if SCALER_CHECKSUM_EXPECTED and abs(checksum - SCALER_CHECKSUM_EXPECTED) > 1e-3:
        logger.warning(f"Scaler checksum mismatch! Expected {SCALER_CHECKSUM_EXPECTED:.4f}, got {checksum:.4f}. Continue anyway...")
    else:
        logger.info(f"Scaler loaded — checksum OK ({checksum:.4f})")

    # XGBoost
    _xgb_model = xgb.XGBClassifier()
    _xgb_model.load_model(str(ARTIFACTS_DIR / "artifact_xgb_model.json"))
    logger.info("XGBoost loaded.")

    # LSTM experts
    for etype in EXPERT_TYPES:
        path = ARTIFACTS_DIR / f"artifact_lstm_{etype}.keras"
        if path.exists():
            _expert_models[etype] = load_model(
                str(path),
                custom_objects={
                    "PRATYAKSAExpert": PRATYAKSAExpert,
                    "asymmetric_loss": asymmetric_loss
                }
            )
            logger.info(f"Expert loaded: {etype}")
        else:
            logger.warning(f"Expert model NOT found: {path}")

    # Drift detector
    drift_b = META.get("drift_baseline", {})
    if drift_b:
        _drift_detector = DriftDetector(drift_b["mean"], drift_b["std"])
        logger.info("Drift detector initialized.")

    # Redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    _redis = await aioredis.from_url(redis_url, decode_responses=False)
    await _redis.ping()
    logger.info(f"Redis connected: {redis_url}")

    # PostgreSQL
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        try:
            _db_engine = create_async_engine(
                async_db_url,
                pool_size=10,
                max_overflow=20,
                connect_args={"server_settings": {"jit": "off"}}
            )
            async with _db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("PostgreSQL (Async) connected.")
        except Exception as e:
            logger.warning(f"PostgreSQL unavailable (non-fatal): {e}")
            _db_engine = None
    else:
        logger.warning("DATABASE_URL not set.")

    # DB Batcher
    if _db_engine is not None:
        _db_batcher = AsyncDBBatcher(_db_engine, _write_prediction_to_db,
                                     max_size=50, flush_interval=2.0)
    else:
        _db_batcher = None

    # SHAP explainer cache
    _shap_explainer = shap.TreeExplainer(_xgb_model)
    logger.info("SHAP explainer cached.")

    consumer_task = asyncio.create_task(consume_sensor_streams())
    logger.info("PRATYAKSA API ready.")
    yield

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    if _db_batcher:
        _db_batcher._task.cancel()
        try:
            await _db_batcher._task
        except asyncio.CancelledError:
            pass
    if _redis:
        await _redis.aclose()
    if _db_engine:
        await _db_engine.dispose()
    logger.info("PRATYAKSA API shutdown complete.")


# ---------- FastAPI app ----------
app = FastAPI(
    title="PRATYAKSA Inference API",
    version="3.4.0",
    description="AIoT Predictive Maintenance — Production Hardened",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


# ---------- Pydantic models ----------
class SensorReading(BaseModel):
    asset_id: str
    equipment_type: str
    timestamp: str
    features: List[float] = Field(..., min_length=1)


class PredictionResponse(BaseModel):
    prediction_id: str
    asset_id: str
    equipment_type: str
    xgb_anomaly_class: int
    xgb_anomaly_label: str
    lstm_rul_hours: float
    rul_uncertainty: float
    risk_level: str
    risk_class: int
    model_agreement: bool
    lstm_hydraulic_system: float
    lstm_hydraulic_pump: float
    lstm_pump_seal: float
    lstm_brake_system: float
    lstm_brake_caliper: float
    lstm_brake_pad: float
    lstm_steering_system: float
    digital_twin: dict
    drift_status: dict
    latency_ms: float


# ---------- Endpoints ----------
@app.post("/predict", response_model=PredictionResponse, dependencies=[Depends(verify_api_key)])
async def predict(reading: SensorReading):
    if len(reading.features) != N_FEATURES:
        raise HTTPException(status_code=422, detail=f"Expected {N_FEATURES} features.")
    if reading.equipment_type not in _expert_models:
        raise HTTPException(status_code=422, detail="Unknown equipment_type.")

    result = await process_sensor_reading(reading.model_dump())

    pred_id = f"{reading.asset_id}_{int(time.time()*1000)}"
    await _redis.setex(f"pred:{pred_id}", 86400, json.dumps({
        "features": reading.features,
        "asset_id": reading.asset_id
    }))

    if _db_engine is not None:
        asyncio.create_task(_write_sensor_reading_to_db(reading.model_dump(), reading.features))
        _db_batcher.push(result)

    await _redis.setex(f"result:{reading.asset_id}", 3600, json.dumps(result))
    await _redis.publish("predictions", json.dumps(result))
    await _redis.sadd("active_assets", reading.asset_id)

    return PredictionResponse(
        prediction_id=pred_id,
        asset_id=result["asset_id"],
        equipment_type=result["equipment_type"],
        xgb_anomaly_class=result["xgb_anomaly_class"],
        xgb_anomaly_label=result["xgb_anomaly_label"],
        lstm_rul_hours=result["lstm_rul_hours"],
        rul_uncertainty=result["rul_uncertainty"],
        risk_level=result["risk_level"],
        risk_class=result["risk_class"],
        model_agreement=result["model_agreement"],
        lstm_hydraulic_system=result.get("RUL_hydraulic_system", 0.0),
        lstm_hydraulic_pump=result.get("RUL_hydraulic_pump", 0.0),
        lstm_pump_seal=result.get("RUL_pump_seal_main", 0.0),
        lstm_brake_system=result.get("RUL_brake_system", 0.0),
        lstm_brake_caliper=result.get("RUL_brake_caliper", 0.0),
        lstm_brake_pad=result.get("RUL_brake_pad_rear", 0.0),
        lstm_steering_system=result.get("RUL_steering_system", 0.0),
        digital_twin=result["digital_twin"],
        drift_status=result["drift_status"],
        latency_ms=result["latency_ms"],
    )


@app.get("/result/{asset_id}", dependencies=[Depends(verify_api_key)])
async def get_latest_result(asset_id: str):
    raw = await _redis.get(f"result:{asset_id}")
    if not raw:
        raise HTTPException(404, "Not found")
    return json.loads(raw)


@app.get("/health")
async def health():
    redis_ok, db_ok = False, False
    try:
        redis_ok = bool(await _redis.ping())
    except:
        pass
    try:
        if _db_engine:
            async with _db_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_ok = True
    except:
        pass

    return {
        "status": "ok" if (redis_ok and len(_expert_models) == len(EXPERT_TYPES)) else "degraded",
        "redis": "ok" if redis_ok else "unavailable",
        "postgres": "ok" if db_ok else "unavailable",
        "experts_loaded": list(_expert_models.keys()),
        "model_version": META.get("model_version", "unknown"),
    }


@app.post("/reload-models", dependencies=[Depends(verify_api_key)])
async def reload_models():
    global _scaler, _xgb_model, _expert_models
    logger.info("Triggering zero-downtime hot-reload...")
    try:
        new_scaler = joblib.load(ARTIFACTS_DIR / "artifact_scaler.pkl")
        new_xgb = xgb.XGBClassifier()
        new_xgb.load_model(str(ARTIFACTS_DIR / "artifact_xgb_model.json"))

        new_experts = {}
        for etype in EXPERT_TYPES:
            path = ARTIFACTS_DIR / f"artifact_lstm_{etype}.keras"
            if path.exists():
                new_experts[etype] = load_model(
                    str(path),
                    custom_objects={
                        "PRATYAKSAExpert": PRATYAKSAExpert,
                        "asymmetric_loss": asymmetric_loss
                    }
                )
            else:
                raise FileNotFoundError(f"Missing newly trained expert: {path}")

        _scaler, _xgb_model, _expert_models = new_scaler, new_xgb, new_experts
        return {"status": "success", "message": "Models hot-swapped successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features", dependencies=[Depends(verify_api_key)])
async def list_features():
    return {"features": [{"index": i, "name": f, "group": _get_group(f)} for i, f in enumerate(FITUR_KOLOM)], "total": N_FEATURES}


@app.get("/fleet", dependencies=[Depends(verify_api_key)])
async def fleet_status():
    assets = await _redis.smembers("active_assets")
    if not assets:
        return {"fleet": [], "total": 0}

    pipe = _redis.pipeline()
    for a in assets:
        pipe.get(f"result:{a.decode()}")
    results = await pipe.execute()

    fleet = []
    for raw in results:
        if raw:
            try:
                r = json.loads(raw)
                fleet.append({
                    "asset_id": r["asset_id"],
                    "equipment_type": r["equipment_type"],
                    "risk_level": r["risk_level"],
                    "lstm_rul_hours": r["lstm_rul_hours"],
                    "rul_uncertainty": r["rul_uncertainty"],
                    "model_agreement": r["model_agreement"],
                    "drift_detected": r.get("drift_status", {}).get("drift_detected", False),
                    "processed_at": r["processed_at"],
                })
            except Exception:
                continue

    fleet.sort(key=lambda x: x["risk_level"] == "CRITICAL", reverse=True)
    return {"fleet": fleet, "total": len(fleet)}


# ──────────────────────── P3: /explain ────────────────────────────
@app.get("/explain/{prediction_id}", dependencies=[Depends(verify_api_key)])
async def explain_prediction(prediction_id: str):
    raw = await _redis.get(f"pred:{prediction_id}")
    if not raw:
        raise HTTPException(404, "Prediction not found")
    data = json.loads(raw)
    features = data["features"]

    scaled = _scaler.transform(np.array(features).reshape(1, -1))
    shap_values = _shap_explainer.shap_values(scaled)

    # ── Tangani berbagai bentuk output SHAP ──
    expected = _shap_explainer.expected_value

    # Base value untuk kelas CRITICAL (indeks 2)
    if isinstance(expected, (list, np.ndarray)):
        base_val = float(expected[2]) if len(expected) > 2 else float(expected[1])
    else:
        base_val = float(expected)

    # SHAP values untuk kelas CRITICAL (indeks 2)
    if isinstance(shap_values, list):
        # SHAP < 0.46: list of arrays, masing-masing (n_samples, n_features)
        sv = shap_values[2][0]
    elif shap_values.ndim == 3:
        # SHAP >= 0.46: (n_samples, n_features, n_classes)
        sv = shap_values[0, :, 2]
    elif shap_values.ndim == 2 and shap_values.shape[1] == 3:
        # (n_features, n_classes) – sangat jarang
        sv = shap_values[:, 2]
    else:
        # Binary: (n_features,)
        sv = shap_values[0]

    # Pastikan sv adalah array 1D (n_features,)
    if sv.ndim > 1:
        sv = sv.flatten()

    plt.figure(figsize=(10, 6))
    shap.waterfall_plot(
        shap.Explanation(
            values=sv,
            base_values=base_val,
            data=scaled[0],
            feature_names=FITUR_KOLOM
        ),
        show=False
    )
    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    plt.close()
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()

    return {"prediction_id": prediction_id, "waterfall": img_b64}


# ──────────────────────── P4: /workorder ──────────────────────────
@app.post("/workorder", dependencies=[Depends(verify_api_key)])
async def create_work_order(component: str, risk_score: float):
    if _db_engine is None:
        raise HTTPException(503, "Database not available")
    engine = RecommendationEngine(_db_engine)
    rec = await engine.generate(risk_score, component)
    if rec["action"] == "Create Work Order":
        return {"status": "created", "recommendation": rec}
    return {"status": "not_created", "message": "Risk too low"}