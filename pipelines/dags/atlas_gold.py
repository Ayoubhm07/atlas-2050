"""DAGs silver DuckDB (BAN, DPE, Géorisques) et gold (dbt build + chargement PostGIS).

bronze/ban ──────────────────────► silver_ban ─┐
bronze/dpe ──────────────────────► silver_dpe ─┤
bronze/georisques | ppr | rga ───► silver_geo ─┼──► gold : dbt build ─► promotion ─► PostGIS
silver/dvf (atlas_silver_dvf) ─────────────────┤
bronze/iris, bronze/insee (lus tels quels) ────┘

dbt écrit dans data/gold_build (ses Parquet existent AVANT ses tests) ; la promotion
vers data/gold, lu par le chargeur, n'a lieu que si `dbt build` a réussi, tests compris.

Mêmes URI de Datasets que dags/atlas_ingestion.py (une URI = un Dataset Airflow ; ppr
et rga écrivent physiquement dans bronze/georisques, l'URI est logique). Les imports
lourds (duckdb, psycopg, atlas_pipelines) sont faits dans les tâches, pas au parsing.
dbt tourne dans son propre venv (/opt/dbt-venv) : dbt-core 1.10 impose des versions
de dépendances incompatibles avec l'environnement Airflow.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator

DATA = "file:///opt/atlas/data"
DBT_BIN = "/opt/dbt-venv/bin/dbt"
DBT_PROJECT = "/opt/atlas/dbt"

BRONZE = {
    n: Dataset(f"{DATA}/bronze/{n}")
    for n in ("ban", "dpe", "georisques", "ppr", "rga", "iris", "insee")
}
SILVER = {n: Dataset(f"{DATA}/silver/{n}") for n in ("ban", "dpe", "georisques", "dvf")}
GOLD_PARQUET = Dataset(f"{DATA}/gold")
# forme attendue par le provider postgres : postgres://hôte:port/base/schéma/table
GOLD_POSTGIS = Dataset("postgres://db:5432/atlas/gold/fact_transactions")

START = datetime(2026, 9, 1)
DEFAULT_ARGS = {
    "owner": "atlas",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def silver(source: str) -> dict[str, int]:
    from atlas_pipelines.config import PipelineConfig
    from atlas_pipelines.silver.run_duck import RUNNERS

    return RUNNERS[source](PipelineConfig.from_env())


def dbt_build() -> None:
    import os
    import subprocess  # noqa: S404 - commande fixe, aucun argument venant de l'extérieur

    from atlas_pipelines.config import PipelineConfig

    # dbt ouvre data/gold_build/atlas.duckdb : le répertoire doit exister
    (PipelineConfig.from_env().data_dir / "gold_build").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DBT_PROFILES_DIR": DBT_PROJECT}
    subprocess.run(  # noqa: S603
        [DBT_BIN, "build", "--project-dir", DBT_PROJECT, "--profiles-dir", DBT_PROJECT],
        check=True,
        env=env,
    )


def promote_gold() -> list[str]:
    from atlas_pipelines.config import PipelineConfig
    from atlas_pipelines.load.promote import promote

    data = PipelineConfig.from_env().data_dir
    return [p.name for p in promote(data / "gold_build", data / "gold")]


def load_postgis() -> dict[str, int]:
    from atlas_pipelines.config import PipelineConfig
    from atlas_pipelines.load.postgis import conninfo_from_env, load

    return load(PipelineConfig.from_env().data_dir / "gold", conninfo_from_env())


SILVER_SCHEDULES = {
    "ban": [BRONZE["ban"]],
    "dpe": [BRONZE["dpe"]],
    "georisques": BRONZE["georisques"] | BRONZE["ppr"] | BRONZE["rga"],
}

for name, schedule in SILVER_SCHEDULES.items():
    with DAG(
        dag_id=f"atlas_silver_{name}",
        start_date=START,
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["atlas", "silver"],
    ) as dag:
        PythonOperator(
            task_id=f"clean_{name}",
            python_callable=silver,
            op_kwargs={"source": name},
            outlets=[SILVER[name]],
        )
    globals()[dag.dag_id] = dag

with DAG(
    dag_id="atlas_gold",
    start_date=START,
    # n'importe quel silver (ou référentiel IRIS / Filosofi lu en bronze par dim_iris et
    # dim_commune) mis à jour relance le gold (dbt reconstruit tout en ~1 min)
    schedule=(
        SILVER["dvf"]
        | SILVER["ban"]
        | SILVER["dpe"]
        | SILVER["georisques"]
        | BRONZE["iris"]
        | BRONZE["insee"]
    ),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["atlas", "gold"],
) as gold_dag:
    build = PythonOperator(task_id="dbt_build", python_callable=dbt_build)
    promotion = PythonOperator(
        task_id="promote_gold", python_callable=promote_gold, outlets=[GOLD_PARQUET]
    )
    charge = PythonOperator(
        task_id="load_postgis", python_callable=load_postgis, outlets=[GOLD_POSTGIS]
    )
    build >> promotion >> charge
