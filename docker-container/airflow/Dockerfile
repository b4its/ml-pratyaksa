# Use Airflow 2.9.1 with Python 3.11 (explicit tag)
FROM apache/airflow:2.9.1-python3.11

# Switch to root for system dependencies
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Switch back to airflow user
USER airflow

# Install pinned ML & provider packages
RUN pip install --no-cache-dir \
    pandas==2.3.3 \
    xgboost==3.2.0 \
    keras==3.14.1 \
    tensorflow==2.21.0 \
    scikit-learn==1.8.0 \
    joblib==1.5.3 \
    pyarrow==24.0.0 \
    apache-airflow-providers-postgres==6.7.1 \
    apache-airflow-providers-http==6.0.3