"""BAN bronze → silver (DuckDB) : une ligne par `id` d'adresse, coordonnées typées.

`cad_parcelles` devient une liste (`parcelles`) : le pivot DVF → BAN l'éclate en gold.
Doublons d'`id` constatés dans le fichier source (727 531 lignes, 726 647 `id` distincts
en Gironde) : on garde une ligne par `id`, choisie de façon déterministe.
"""

from __future__ import annotations

import logging

import duckdb

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.silver.duck import require, write_query
from atlas_pipelines.spatial import sql_path

logger = logging.getLogger(__name__)


def query(src: str) -> str:
    return f"""
    SELECT id, code_insee, nom_commune, code_postal, numero, rep, nom_voie,
           TRY_CAST(lon AS DOUBLE) AS lon,
           TRY_CAST(lat AS DOUBLE) AS lat,
           list_filter(string_split(coalesce(cad_parcelles, ''), '|'), p -> p <> '')
               AS parcelles
    FROM read_parquet({src})
    WHERE id IS NOT NULL AND id <> '' AND code_insee IS NOT NULL
    QUALIFY row_number() OVER (
        PARTITION BY id ORDER BY cad_parcelles DESC NULLS LAST, lon, lat, numero
    ) = 1
    ORDER BY id
    """


def run(cfg: PipelineConfig) -> dict[str, int]:
    counts: dict[str, int] = {}
    with duckdb.connect() as con:
        for dep in cfg.departements:
            src = require(cfg.bronze("ban") / f"dep={dep}.parquet", "lancer l'ingestion BAN")
            dest = cfg.silver("ban") / f"dep={dep}.parquet"
            counts[dep] = write_query(con, query(sql_path(src)), dest)
            logger.info("BAN silver dép %s : %d adresses", dep, counts[dep])
    return counts
