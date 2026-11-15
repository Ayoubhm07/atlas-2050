"""Point d'entrée du job silver DVF (spark-submit ou tâche Airflow)."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from pyspark.sql import SparkSession

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.silver.dvf import nettoyer

logger = logging.getLogger(__name__)


def bronze_files(cfg: PipelineConfig) -> list[Path]:
    """Les fichiers des périodes configurées, et eux seuls (pas de reliquat ni de partiel)."""
    files = [cfg.bronze("dvf") / f"periode={p}.parquet" for p in cfg.dvf_periodes]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"Bronze DVF manquant : {missing}. Lancer l'ingestion DVF.")
    return files


def run(cfg: PipelineConfig, spark: SparkSession, report_dir: Path) -> int:
    start = time.perf_counter()
    bronze = spark.read.parquet(*[str(p) for p in bronze_files(cfg)])
    silver, report = nettoyer(bronze)
    target = cfg.silver("dvf")
    stage = target.with_name(f".{target.name}.staging")
    shutil.rmtree(stage, ignore_errors=True)
    (
        silver.repartition("code_departement")
        .write.mode("errorifexists")
        .partitionBy("code_departement", "annee")
        .parquet(str(stage))
    )
    # bascule : l'ancien silver reste lisible jusqu'à ce que le nouveau soit complet
    old = target.with_name(f".{target.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    stage.rename(target)
    shutil.rmtree(old, ignore_errors=True)
    elapsed = time.perf_counter() - start
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "dvf_silver.md").write_text(
        "# Qualité DVF silver\n\n"
        f"Départements : {', '.join(cfg.departements)} — durée : {elapsed:.0f} s\n\n"
        + report.to_markdown()
        + "\n",
        encoding="utf-8",
    )
    final = report.steps[-1][1]
    logger.info("DVF silver : %d ventes en %.0f s", final, elapsed)
    return final


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = PipelineConfig.from_env()
    spark = SparkSession.builder.appName("atlas-dvf-silver").getOrCreate()
    try:
        run(cfg, spark, Path("docs/quality"))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
