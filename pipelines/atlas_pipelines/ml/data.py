"""Jeu de modélisation : gold `fact_transactions` enrichi, sans identifiant de vente.

Jointures (DuckDB, lecture seule du gold et du silver Géorisques) :
- `dim_iris` : revenu médian et Gini Filosofi 2021 (manquants hors IRIS diffusés :
  laissés NULL, jamais imputés ici), exposition RGA (code 1-3, NULL si inconnue) ;
- `fact_risques_commune` : TRI, PPRI (sans date d'approbation dans GASPAR : état
  actuel, voir docs/methodology.md) ;
- Cat-Nat À LA DATE DE VENTE : arrêtés publiés avant la vente et dont l'événement a
  commencé dans les 10 ans qui précèdent (le compteur du gold est figé à la date du run,
  il inclurait des arrêtés postérieurs à la vente : fuite) ;
- `urbain` : commune découpée en IRIS (≥ ~5 000 habitants, INSEE), sinon « rural ».
  C'est un indicateur de taille de commune, pas la grille de densité INSEE.

Exclusions propres au modèle (le silver/gold n'est pas modifié) : maisons avec plus
d'un hectare de terrain (le prix paie surtout le foncier, docs/data-contract.md §1).
Elles sont surtout rurales : le nombre d'exclues en commune sans IRIS est conservé
dans `attrs` pour le rapport.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

MAX_TERRAIN_M2 = 10_000.0

_SQL = """
with t as (
    select * from read_parquet($fact)
),
catnat as (
    select t.id_mutation,
           count(distinct c.code_national_catnat) as n_catnat_10ans
    from t
    join read_parquet($catnat) as c
      on c.code_insee = t.code_commune
     and c.date_arrete < t.date_mutation
     and c.date_debut_evt >= t.date_mutation - interval 10 year
    group by t.id_mutation
),
urbain as (
    select code_insee, bool_or(type_iris <> 'Z') as urbain
    from read_parquet($iris)
    group by code_insee
)
select
    t.date_mutation, t.annee, t.code_commune, t.type_local,
    t.surface_bati, t.pieces, t.surface_terrain, t.n_dependances,
    t.prix_m2, t.lon, t.lat, t.h3_r7, t.dpe_etiquette,
    i.revenu_median, i.gini, i.rga_code_exposition as rga_code,
    r.in_tri, r.ppri,
    coalesce(c.n_catnat_10ans, 0) as n_catnat_10ans,
    coalesce(u.urbain, false) as urbain
from t
left join read_parquet($iris) as i using (code_iris)
left join read_parquet($risques) as r on r.code_insee = t.code_commune
left join catnat as c using (id_mutation)
left join urbain as u on u.code_insee = t.code_commune
order by t.date_mutation, t.code_commune, t.prix_m2
"""


def load_dataset(gold_dir: Path, silver_dir: Path) -> pd.DataFrame:
    """Une ligne par vente, sans id_mutation ni id_parcelle (ADR 0005)."""
    params = {
        "fact": str(gold_dir / "fact_transactions.parquet"),
        "iris": str(gold_dir / "dim_iris.parquet"),
        "risques": str(gold_dir / "fact_risques_commune.parquet"),
        "catnat": str(silver_dir / "georisques" / "catnat.parquet"),
    }
    for path in params.values():
        if not Path(path).is_file():
            raise FileNotFoundError(f"Entrée du modèle absente : {path}")
    with duckdb.connect() as con:
        df = con.execute(_SQL, params).df()
    big = (df["type_local"] == "Maison") & (df["surface_terrain"] > MAX_TERRAIN_M2)
    logger.info("Ventes : %d ; exclues (terrain > 1 ha) : %d", len(df), int(big.sum()))
    out = df.loc[~big].reset_index(drop=True)
    out.attrs["n_exclues_terrain"] = int(big.sum())
    # l'exclusion touche surtout les communes rurales (docs/methodology.md §4)
    out.attrs["n_exclues_terrain_sans_iris"] = int((big & ~df["urbain"].astype(bool)).sum())
    return out
