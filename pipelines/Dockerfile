# Image Airflow + PySpark (Java requis par Spark) + dbt-duckdb dans un venv séparé
FROM apache/airflow:2.10.3-python3.11

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
 && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# dbt-core 1.10 épingle des dépendances (pathspec, protobuf...) en conflit avec Airflow :
# venv dédié, appelé par le DAG atlas_gold via /opt/dbt-venv/bin/dbt
USER root
RUN python -m venv /opt/dbt-venv && chown -R airflow: /opt/dbt-venv
USER airflow
COPY dbt-requirements.txt /tmp/dbt-requirements.txt
RUN /opt/dbt-venv/bin/pip install --no-cache-dir -r /tmp/dbt-requirements.txt
