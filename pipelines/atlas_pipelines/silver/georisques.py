"""Géorisques bronze → silver (DuckDB) : payloads JSON aplatis en colonnes typées.

Bronze : une ligne par (endpoint, commune, enregistrement), payload NULL quand la
commune a été interrogée sans résultat. Silver :
- une table par endpoint, une ligne par enregistrement réel ;
- `couverture` : (endpoint, code_insee, n_enregistrements) pour TOUTES les communes
  interrogées. 0 = « interrogée, rien trouvé » ; commune absente = jamais interrogée.
  C'est ce qui permet la variable AZI à trois états (oui / non / inconnu).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.silver.duck import write_query
from atlas_pipelines.spatial import sql_path

logger = logging.getLogger(__name__)

# PPRN dont le modèle de procédure couvre l'inondation : I = inondation,
# L = littoral (submersion marine). Valeurs lues dans l'API réelle le 2026-11-15.
PPR_INONDATION = ("PPRN-I", "PPRN-L")


def _date(field: str) -> str:
    return f"TRY_STRPTIME(json_extract_string(payload, '$.{field}'), '%d/%m/%Y')::DATE"


def _s(field: str) -> str:
    return f"json_extract_string(payload, '$.{field}')"


def catnat(src: str) -> str:
    return f"""
    SELECT DISTINCT code_insee, {_s("code_national_catnat")} AS code_national_catnat,
           {_s("libelle_risque_jo")} AS libelle_risque,
           {_date("date_debut_evt")} AS date_debut_evt,
           {_date("date_fin_evt")} AS date_fin_evt,
           {_date("date_publication_arrete")} AS date_arrete
    FROM read_parquet({src}) WHERE payload IS NOT NULL
    ORDER BY code_insee, code_national_catnat
    """


def tri(src: str) -> str:
    return f"""
    SELECT DISTINCT code_insee, {_s("code_national_tri")} AS code_tri,
           {_s("libelle_tri")} AS libelle_tri
    FROM read_parquet({src}) WHERE payload IS NOT NULL ORDER BY code_insee, code_tri
    """


def azi(src: str) -> str:
    return f"""
    SELECT DISTINCT code_insee, {_s("code_national_azi")} AS code_azi,
           {_s("libelle_azi")} AS libelle_azi
    FROM read_parquet({src}) WHERE payload IS NOT NULL ORDER BY code_insee, code_azi
    """


def pprn(src: str) -> str:
    flood = ", ".join(f"'{m}'" for m in PPR_INONDATION)
    return f"""
    SELECT DISTINCT code_insee, {_s("idGaspar")} AS id_gaspar,
           {_s("modeleProcedure")} AS modele_procedure,
           {_s("libPpr")} AS libelle_ppr,
           {_s("modeleProcedure")} IN ({flood}) AS risque_inondation
    FROM read_parquet({src}) WHERE payload IS NOT NULL ORDER BY code_insee, id_gaspar
    """


def rga(src: str) -> str:
    return f"""
    SELECT code_iris, lon, lat,
           TRY_CAST({_s("codeExposition")} AS INTEGER) AS code_exposition,
           {_s("exposition")} AS exposition
    FROM read_parquet({src}) ORDER BY code_iris
    """


def couverture(srcs: list[str]) -> str:
    union = " UNION ALL ".join(
        f"SELECT endpoint, code_insee, payload FROM read_parquet({s})" for s in srcs
    )
    return f"""
    SELECT endpoint, code_insee, count(payload) AS n_enregistrements
    FROM ({union}) GROUP BY ALL ORDER BY endpoint, code_insee
    """


TABLES = {"catnat": catnat, "tri": tri, "azi": azi, "pprn": pprn}


def run(cfg: PipelineConfig) -> dict[str, int]:
    bronze = cfg.bronze("georisques")
    present: dict[str, Path] = {
        name: bronze / f"{name}.parquet" for name in TABLES if (bronze / f"{name}.parquet").exists()
    }
    if not present:
        raise FileNotFoundError(f"Aucun bronze Géorisques dans {bronze}")
    counts: dict[str, int] = {}
    out = cfg.silver("georisques")
    with duckdb.connect() as con:
        for name, path in present.items():
            counts[name] = write_query(con, TABLES[name](sql_path(path)), out / f"{name}.parquet")
        srcs = [sql_path(p) for p in present.values()]
        counts["couverture"] = write_query(con, couverture(srcs), out / "couverture.parquet")
        rga_src = bronze / "rga.parquet"
        if rga_src.exists():
            counts["rga"] = write_query(con, rga(sql_path(rga_src)), out / "rga.parquet")
    missing = sorted(set(TABLES) - set(present)) + ([] if "rga" in counts else ["rga"])
    if missing:
        logger.warning("Bronze Géorisques absent (silver partiel) : %s", missing)
    logger.info("Géorisques silver : %s", counts)
    return counts
