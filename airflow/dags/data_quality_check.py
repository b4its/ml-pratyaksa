from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
import pandas as pd

def check_quality():
    df = pd.read_parquet("/opt/airflow/data/dataset_pratyaksa_pilot.parquet")
    issues = []
    if df.isnull().sum().sum() > 0:
        issues.append("Null values found")
    with open("/tmp/dq_report.txt", "w") as f:
        f.write("\n".join(issues))

default_args = {'owner': 'airflow', 'start_date': datetime(2026,6,1)}

with DAG('daily_data_quality',
        default_args=default_args,
         schedule_interval='0 6 * * *',
        catchup=False) as dag:
    PythonOperator(task_id='check_quality', python_callable=check_quality)