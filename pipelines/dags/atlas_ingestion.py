"""DAGs ATLAS 2050 : un DAG par source + nettoyage silver, chaînés par Datasets Airflow.

ban ──► georisques            dvf ──► silver_dvf
dpe, insee, drias : indépendants

Le fichier ne fait que déclarer les DAGs : httpx, duckdb, pyarrow et pyspark sont
importés à l'exécution des tâches, pas au parsing (rapide pour le scheduler).
Planification : Airflow lance un run à la FIN de chaque intervalle. Avec un start_date
antérieur d'un intervalle et catchup=False, le premier run part dès l'activation.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator

DATA = "file:///opt/atlas/data"
SOURCES = ("dvf", "ban", "dpe", "georisques", "insee", "drias")
DS = {name: Dataset(f"{DATA}/bronze/{name}") for name in SOURCES}
DS_SILVER_DVF = Dataset(f"{DATA}/silver/dvf")

START = datetime(2026, 9, 1)
SCHEDULES: dict[str, Any] = {
    "dvf": "@monthly",  # data.gouv publie 2 fois par an ; le manifeste évite tout re-téléchargement
    "ban": "@monthly",  # URL fixe `latest/` : rafraîchie via ETag / Last-Modified
    "dpe": "@weekly",
    "insee": "@once",  # Filosofi IRIS 2021 est la dernière édition publiée
    "drias": None,  # dépôt manuel : déclenché à la main après le dépôt
    "georisques": [DS["ban"]],  # communes issues de la BAN
}

DEFAULT_ARGS = {
    "owner": "atlas",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


def ingest(source: str) -> dict[str, int]:
    from atlas_pipelines.config import PipelineConfig
    from atlas_pipelines.http import make_client

    module = importlib.import_module(f"atlas_pipelines.sources.{source}")
    cfg = PipelineConfig.from_env()
    if source == "drias":
        result: dict[str, int] = module.ingest(cfg)
        return result
    with make_client(timeout=300) as client:
        result = module.ingest(cfg, client)
        return result


def silver_dvf() -> int:
    from pathlib import Path

    from pyspark.sql import SparkSession

    from atlas_pipelines.config import PipelineConfig
    from atlas_pipelines.silver.run_dvf import run

    spark = (
        SparkSession.builder.appName("atlas-dvf-silver")
        .master("local[*]")
        # 200 partitions par défaut = des milliers de petits fichiers, très lent sur un
        # volume monté depuis Windows (402 s contre 43 s en local pour la Gironde 2024)
        .config("spark.sql.shuffle.partitions", "16")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    try:
        return run(PipelineConfig.from_env(), spark, Path("/opt/atlas/data/quality"))
    finally:
        spark.stop()


for name in SOURCES:
    with DAG(
        dag_id=f"atlas_ingest_{name}",
        start_date=START,
        schedule=SCHEDULES[name],
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["atlas", "bronze"],
    ) as dag:
        PythonOperator(
            task_id=f"ingest_{name}",
            python_callable=ingest,
            op_kwargs={"source": name},
            outlets=[DS[name]],
        )
    globals()[dag.dag_id] = dag

with DAG(
    dag_id="atlas_silver_dvf",
    start_date=START,
    schedule=[DS["dvf"]],
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["atlas", "silver"],
) as silver_dag:
    PythonOperator(task_id="clean_dvf", python_callable=silver_dvf, outlets=[DS_SILVER_DVF])
