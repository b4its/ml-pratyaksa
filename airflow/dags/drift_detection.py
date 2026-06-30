from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd
import numpy as np
import json
from pathlib import Path
from scipy.stats import ks_2samp

def detect_drift():
    ref = pd.read_parquet("/opt/airflow/artifacts/split_train.parquet")
    yesterday = (datetime.now() - timedelta(1)).strftime("%Y-%m-%d")
    daily_path = Path(f"/opt/airflow/data/daily/{yesterday}.parquet")
    if not daily_path.exists():
        print(f"No daily data for {yesterday}, skipping drift detection")
        return
    curr = pd.read_parquet(daily_path)
    report = {}
    for col in ref.select_dtypes(include=[np.number]).columns:
        if col in curr.columns:
            stat, p = ks_2samp(ref[col].dropna(), curr[col].dropna())
            if p < 0.05:
                report[col] = {"ks_stat": float(stat), "p_value": float(p)}
    with open(f"/tmp/drift_{yesterday}.json", "w") as f:
        json.dump(report, f)

default_args = {'owner': 'airflow', 'start_date': datetime(2026,6,1)}

with DAG('daily_drift_detection',
         default_args=default_args,
         schedule_interval='0 8 * * *',
         catchup=False) as dag:
    PythonOperator(task_id='detect_drift', python_callable=detect_drift)
