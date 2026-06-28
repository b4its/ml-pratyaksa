"""
PRATYAKSA Stream Simulator
Simulasi pengiriman data sensor ke Redis Streams (menggantikan Rust ingestion saat dev)
"""
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulator")

PROJECT_ROOT  = Path(__file__).parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
DATA_DIR      = PROJECT_ROOT / "data"

# Load metadata
with open(ARTIFACTS_DIR / "artifact_deploy_meta.json") as f:
    META = json.load(f)

FITUR_KOLOM  = META["FITUR_KOLOM"]
EXPERT_TYPES = META["expert_types"]

# Konfigurasi simulasi
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
STREAM_PREFIX     = "stream:sensors:"
SEND_INTERVAL_SEC = 5.0   # kirim setiap 5 detik per unit
MAX_STREAM_LEN    = 10000 # trim stream jika > ini

# Load pilot dataset (data nyata dari pipeline)
PILOT_PATH = DATA_DIR / "dataset_pratyaksa_pilot.parquet"
NOISY_PATH = DATA_DIR / "dataset_pratyaksa_noisy.parquet"

def load_dataset() -> pd.DataFrame:
    path = PILOT_PATH if PILOT_PATH.exists() else NOISY_PATH
    df   = pd.read_parquet(path, engine='fastparquet')
    logger.info(f"Loaded dataset: {path.name} | {len(df):,} rows | "
                f"{df['asset_id'].nunique()} units")
    return df

def get_unit_iterator(df: pd.DataFrame, asset_id: str):
    """Generator yang loop data unit secara kronologis."""
    unit_df = df[df['asset_id'] == asset_id].sort_values('timestamp')
    rows    = unit_df[FITUR_KOLOM].values.tolist()
    i = 0
    while True:
        yield rows[i % len(rows)]
        i += 1

async def send_to_stream(
    r: aioredis.Redis,
    asset_id: str,
    equipment_type: str,
    features: list,
):
    stream_key = f"{STREAM_PREFIX}{equipment_type}"
    msg = {
        b"asset_id":       asset_id.encode(),
        b"equipment_type": equipment_type.encode(),
        b"timestamp":      datetime.now(timezone.utc).isoformat().encode(),
        b"features":       json.dumps(features).encode(),
    }
    msg_id = await r.xadd(stream_key, msg, maxlen=MAX_STREAM_LEN, approximate=True)
    return msg_id

async def simulate_unit(
    r: aioredis.Redis,
    asset_id: str,
    equipment_type: str,
    df: pd.DataFrame,
    interval: float,
    jitter: float = 0.5,
):
    """Coroutine per unit — kirim data secara async."""
    gen = get_unit_iterator(df, asset_id)
    logger.info(f"  [{asset_id}] Started ({equipment_type})")

    while True:
        features = next(gen)
        # Tambah noise kecil untuk simulasi real sensor
        features_noisy = [
            f + random.gauss(0, abs(f) * 0.01) if isinstance(f, float) else f
            for f in features
        ]

        try:
            msg_id = await send_to_stream(r, asset_id, equipment_type, features_noisy)
            logger.debug(f"  [{asset_id}] → {stream_key_str(equipment_type)} | id={msg_id}")
        except Exception as e:
            logger.error(f"  [{asset_id}] Send error: {e}")

        # Jitter interval agar tidak semua unit sync
        await asyncio.sleep(interval + random.uniform(-jitter, jitter))

def stream_key_str(etype): return f"{STREAM_PREFIX}{etype}"

async def monitor_streams(r: aioredis.Redis):
    """Print ringkasan stream setiap 30 detik."""
    while True:
        await asyncio.sleep(30)
        logger.info("─" * 50)
        for etype in EXPERT_TYPES:
            key  = f"{STREAM_PREFIX}{etype}"
            try:
                info = await r.xinfo_stream(key)
                logger.info(f"  {key}: {info['length']} messages | "
                            f"first={info.get('first-entry', ['?'])[0]} | "
                            f"last={info.get('last-entry', ['?'])[0]}")
            except Exception as e:
                logger.warning(f"  {key}: Could not read stream info ({e})")

        # Juga cek result keys menggunakan scan_iter
        result_keys = []
        async for key in r.scan_iter(match="result:*", count=100):
            result_keys.append(key)
        logger.info(f"  Active predictions cached: {len(result_keys)}")
        logger.info("─" * 50)


async def main():
    logger.info("PRATYAKSA Stream Simulator v3")
    logger.info(f"Redis: {REDIS_URL}")
    logger.info(f"Equipment types: {EXPERT_TYPES}")
    logger.info(f"Send interval: {SEND_INTERVAL_SEC}s per unit")

    df = load_dataset()

    r = await aioredis.from_url(REDIS_URL, decode_responses=False)
    await r.ping()
    logger.info("Redis connected.")

    # Initialize streams
    for etype in EXPERT_TYPES:
        key = f"{STREAM_PREFIX}{etype}"
        try:
            await r.xgroup_create(key, "pratyaksa-analytics", id='0', mkstream=True)
            logger.info(f"  Stream initialized: {key}")
        except Exception:
            logger.info(f"  Stream already exists: {key}")

    # Buat tasks dengan stagger yang benar agar tidak thundering herd
    async def start_with_delay(asset_id, etype, delay):
        await asyncio.sleep(delay)
        await simulate_unit(r, asset_id, etype, df, SEND_INTERVAL_SEC)

    real_tasks = []
    for asset_id in df['asset_id'].unique():
        etype_row = df[df['asset_id'] == asset_id]['equipment_type'].iloc[0]
        if etype_row in EXPERT_TYPES:
            delay = random.uniform(0, SEND_INTERVAL_SEC)
            real_tasks.append(
                asyncio.create_task(start_with_delay(asset_id, etype_row, delay))
            )

    real_tasks.append(asyncio.create_task(monitor_streams(r)))

    logger.info(f"\n[START] Simulating {len(real_tasks)-1} units...")
    logger.info("Press Ctrl+C to stop.\n")

    try:
        await asyncio.gather(*real_tasks)
    except KeyboardInterrupt:
        logger.info("Simulator stopped by user.")
    except Exception as e:
        logger.error(f"Simulator crashed: {e}")
    finally:
        for t in real_tasks:
            t.cancel()
        await r.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Suppress the messy traceback on Ctrl+C exit