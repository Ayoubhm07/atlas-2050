"""Base Adresse Nationale : pivot adresse ↔ parcelle (DVF) ↔ identifiant BAN (DPE)."""

from __future__ import annotations

import logging

import httpx

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import download
from atlas_pipelines.sources.csv_to_parquet import csv_to_parquet

logger = logging.getLogger(__name__)

URL = "https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{dep}.csv.gz"


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dep in cfg.departements:
        raw = download(client, URL.format(dep=dep), cfg.raw("ban") / f"adresses-{dep}.csv.gz")
        counts[dep] = csv_to_parquet(
            cfg.raw("ban") / raw.path, cfg.bronze("ban") / f"dep={dep}.parquet", sep=";"
        )
        logger.info("BAN dép %s : %d adresses", dep, counts[dep])
    return counts
