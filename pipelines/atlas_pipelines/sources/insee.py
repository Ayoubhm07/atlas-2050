"""INSEE Filosofi 2021 par IRIS (revenus disponibles)."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import httpx

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import download
from atlas_pipelines.sources.csv_to_parquet import csv_to_parquet

logger = logging.getLogger(__name__)

URL = "https://www.insee.fr/fr/statistiques/fichier/8229323/BASE_TD_FILO_IRIS_2021_DISP_CSV.zip"


def _extract_csv(archive: Path, out_dir: Path) -> Path:
    """Extrait l'unique CSV de données de l'archive, sans faire confiance aux chemins."""
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv") and "meta" not in n.lower()]
        if len(names) != 1:
            raise ValueError(f"CSV de données attendu unique dans {archive.name}, trouvé {names}")
        target = out_dir / Path(names[0]).name  # neutralise les chemins de type ../
        target.write_bytes(zf.read(names[0]))
    return target


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    raw = download(client, URL, cfg.raw("insee") / "filosofi_iris_2021_disp.zip")
    csv = _extract_csv(cfg.raw("insee") / raw.path, cfg.raw("insee"))
    deps = " OR ".join(f"starts_with(IRIS, '{d}')" for d in cfg.departements)
    n = csv_to_parquet(csv, cfg.bronze("insee") / "filosofi_iris_2021.parquet", sep=";", where=deps)
    logger.info("Filosofi IRIS 2021 : %d IRIS", n)
    return {"filosofi_iris_2021": n}
