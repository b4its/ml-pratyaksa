from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd
import numpy as np

def check_quality():
    df = pd.read_parquet("/opt/airflow/data/dataset_pratyaksa_pilot.parquet")
    issues = []
    total, nulls, dupes = len(df), df.isnull().sum().sum(), df.duplicated().sum()
    if nulls > 0:
        issues.append(f"Null values: {nulls}")
    if dupes > 0:
        issues.append(f"Duplicate rows: {dupes}")
    for col in df.select_dtypes(include=[np.number]).columns:
        if df[col].isnull().sum() > 0:
            continue
        z_scores = np.abs((df[col] - df[col].mean()) / df[col].std())
        outliers = (z_scores > 5).sum()
        if outliers > 0:
            issues.append(f"Outliers (>5σ) in {col}: {outliers}")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_rows": total,
        "issues": issues,
        "status": "PASS" if not issues else "ISSUES_FOUND"
    }
    import json
    with open("/tmp/dq_report.json", "w") as f:
        json.dump(summary, f, indent=2)

default_args = {'owner': 'airflow', 'start_date': datetime(2026,6,1)}

with DAG('daily_data_quality',
         default_args=default_args,
         schedule_interval='0 6 * * *',
         catchup=False) as dag:
    PythonOperator(task_id='check_quality', python_callable=check_quality)
