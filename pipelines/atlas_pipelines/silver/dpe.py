"""DPE bronze → silver (DuckDB) : historique complet des DPE valides par adresse BAN.

Règles (data-contract §2) : `etiquette_dpe` dans A–G, DPE établis à partir du
2021-07-01 (méthode actuelle), `identifiant_ban` renseigné. AUCUN dédoublonnage par
adresse : garder seulement le plus récent ferait fuiter vers une vente un DPE établi
après elle. Le gold (fact_transactions) choisit, pour chaque vente, le DPE le plus
récent parmi ceux établis au plus tard à la date de vente, et compte à cette même date
les DPE de l'adresse (immeubles : plusieurs logements partagent une adresse BAN).
"""

from __future__ import annotations

import logging

import duckdb

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.silver.duck import count, require, write_query
from atlas_pipelines.spatial import sql_path

logger = logging.getLogger(__name__)

DATE_MIN = "2021-07-01"
CLASSES = ("A", "B", "C", "D", "E", "F", "G")


def query(src: str) -> str:
    classes = ", ".join(f"'{c}'" for c in CLASSES)
    return f"""
    WITH typed AS (
        SELECT numero_dpe, identifiant_ban,
               code_insee_ban AS code_insee,
               upper(trim(etiquette_dpe)) AS etiquette_dpe,
               CASE WHEN upper(trim(etiquette_ges)) IN ({classes})
                    THEN upper(trim(etiquette_ges)) END AS etiquette_ges,
               TRY_CAST(date_etablissement_dpe AS DATE) AS date_dpe,
               TRY_CAST(surface_habitable_logement AS DOUBLE) AS surface_habitable,
               lower(type_batiment) AS type_batiment,
               periode_construction,
               TRY_CAST(split_part(_geopoint, ',', 2) AS DOUBLE) AS lon,
               TRY_CAST(split_part(_geopoint, ',', 1) AS DOUBLE) AS lat
        FROM read_parquet({src})
        WHERE identifiant_ban IS NOT NULL AND identifiant_ban <> ''
    ), valid AS (
        SELECT * FROM typed
        WHERE etiquette_dpe IN ({classes}) AND date_dpe >= DATE '{DATE_MIN}'
    )
    SELECT * FROM valid
    ORDER BY identifiant_ban, date_dpe, numero_dpe
    """


def run(cfg: PipelineConfig) -> dict[str, int]:
    counts: dict[str, int] = {}
    with duckdb.connect() as con:
        for dep in cfg.departements:
            src = require(cfg.bronze("dpe") / f"dep={dep}.parquet", "lancer l'ingestion DPE")
            dest = cfg.silver("dpe") / f"dep={dep}.parquet"
            counts[f"{dep}_bronze"] = count(con, src)
            counts[dep] = write_query(con, query(sql_path(src)), dest)
            logger.info(
                "DPE silver dép %s : %d DPE bronze → %d DPE valides",
                dep,
                counts[f"{dep}_bronze"],
                counts[dep],
            )
    return counts
