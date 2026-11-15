"""DVF géolocalisées : fichiers nationaux par période, filtrés sur les départements pilotes.

Les fichiers par département (`geo-dvf/latest/...`) sont archivés et annoncés supprimés :
on résout les URL nationales via l'API data.gouv, car elles contiennent un horodatage.
"""

from __future__ import annotations

import logging
import re

import httpx

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import download, get_json
from atlas_pipelines.sources.csv_to_parquet import csv_to_parquet

logger = logging.getLogger(__name__)

DATASET_API = "https://www.data.gouv.fr/api/1/datasets/demandes-de-valeurs-foncieres-geolocalisees/"
_FULL_RE = re.compile(r"/full-(\d{4}(?:-s[12])?)\.csv\.gz$")


def resolve_urls(client: httpx.Client, periodes: tuple[str, ...]) -> dict[str, str]:
    """Associe chaque période demandée à l'URL de son fichier national."""
    dataset = get_json(client, DATASET_API)
    found: dict[str, str] = {}
    for res in dataset.get("resources", []):
        match = _FULL_RE.search(res.get("url", ""))
        if match:
            periode = match.group(1)
            if periode in found:
                raise LookupError(f"Plusieurs fichiers DVF pour {periode} : ambigu, arrêt")
            found[periode] = res["url"]
    missing = [p for p in periodes if p not in found]
    if missing:
        raise LookupError(
            f"Périodes DVF absentes de data.gouv : {missing}. Disponibles : {sorted(found)}"
        )
    return {p: found[p] for p in periodes}


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    """Télécharge et filtre (une lecture par période) ; renvoie les lignes bronze par période."""
    deps = ", ".join(f"'{d}'" for d in cfg.departements)  # codes validés par la config
    counts: dict[str, int] = {}
    for periode, url in resolve_urls(client, cfg.dvf_periodes).items():
        raw = download(client, url, cfg.raw("dvf") / f"full-{periode}.csv.gz")
        counts[periode] = csv_to_parquet(
            cfg.raw("dvf") / raw.path,
            cfg.bronze("dvf") / f"periode={periode}.parquet",
            where=f"code_departement IN ({deps})",
        )
        logger.info("DVF %s : %d lignes (dép %s)", periode, counts[periode], deps)
    return counts
