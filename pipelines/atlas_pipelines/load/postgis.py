"""Gold Parquet → PostGIS (schéma `gold`), idempotent : tables `__new` puis bascule.

Pour chaque table : CREATE `gold.<t>__new` → COPY → géométrie → index → ANALYZE.
Puis, dans UNE transaction : DROP de l'ancienne table et RENAME des nouvelles (tables,
index, clés). Un échec avant la bascule laisse le gold en service intact ; relancer
le chargement repart de zéro (les `__new` résiduelles sont supprimées).

H3 : l'image `postgis/postgis:16-3.4` ne fournit pas l'extension `h3-pg`
(vérifié dans pg_available_extensions le 2026-11-15) : les index H3 calculés par dbt
sont stockés en texte, indexés en btree. Les colonnes de CODES (code_*, id_*, h3*,
dpe_numero : ASCII) sont en collation « C » (tri binaire, plusieurs fois plus rapide
que en_US.utf8 pour GROUP BY h3). Le texte libre (noms...) garde la collation de la
base : sous « C », lower('Étauliers') laisserait le « É » intact.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

SCHEMA = "gold"
BATCH = 10_000


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: str
    geometry: str  # "wkb" (colonne geom_wkb) ou "point" (lon/lat)
    btree: tuple[str, ...] = ()
    filtre: tuple[str, ...] = ()  # un index btree composite (colonnes de filtre de l'API)


TABLES: tuple[TableSpec, ...] = (
    TableSpec("dim_commune", "code_insee", "wkb", ("code_departement",)),
    TableSpec("dim_iris", "code_iris", "wkb", ("code_insee",)),
    TableSpec(
        "fact_transactions",
        "id_mutation",
        "point",
        ("code_commune", "code_iris", "h3_r7", "h3_r9", "date_mutation"),
    ),
    TableSpec("fact_risques_commune", "code_insee", "none"),
    TableSpec(
        "agg_hex",
        "id_agg",
        "point",
        ("h3",),
        ("resolution", "type_local", "annee", "dpe_etiquette"),
    ),
)

CODE_PREFIXES = ("code_", "id_", "h3")
CODE_COLUMNS = frozenset({"dpe_numero"})
_C_TEXT = 'text COLLATE "C"'

_PG_TYPES: tuple[tuple[Any, str], ...] = (
    (pa.types.is_string, "text"),
    (pa.types.is_large_string, "text"),
    (pa.types.is_boolean, "boolean"),
    (pa.types.is_int8, "smallint"),
    (pa.types.is_int16, "smallint"),
    (pa.types.is_int32, "integer"),
    (pa.types.is_int64, "bigint"),
    (pa.types.is_floating, "double precision"),
    (pa.types.is_date32, "date"),
    (pa.types.is_timestamp, "timestamp"),
    (pa.types.is_binary, "bytea"),
    (pa.types.is_large_binary, "bytea"),
)


class Cursor(Protocol):
    def execute(self, query: str, params: Any = None) -> Any: ...
    def copy(self, statement: str) -> Any: ...


def is_code_column(name: str) -> bool:
    """Codes ASCII (INSEE, IRIS, H3, identifiants) : collation « C » sans risque."""
    return name.startswith(CODE_PREFIXES) or name in CODE_COLUMNS


def pg_type(dtype: pa.DataType, code: bool = False) -> str:
    for check, name in _PG_TYPES:
        if check(dtype):
            return _C_TEXT if code and name == "text" else name
    raise TypeError(f"Type Parquet non géré pour PostGIS : {dtype}")


def ident(name: str) -> str:
    """Identifiant SQL : seuls lettres minuscules, chiffres et _ (noms internes au gold)."""
    if not name.replace("_", "").isalnum() or name.lower() != name:
        raise ValueError(f"Identifiant refusé : {name!r}")
    return f'"{name}"'


def create_sql(spec: TableSpec, schema: pa.Schema) -> str:
    cols = ", ".join(
        f"{ident(f.name)} {pg_type(f.type, is_code_column(f.name))}" for f in schema
    )
    return f"CREATE TABLE {SCHEMA}.{ident(spec.name + '__new')} ({cols})"


def finish_sql(spec: TableSpec) -> list[str]:
    """Géométrie, clé et index sur la table `__new` (avant bascule)."""
    t = f"{SCHEMA}.{ident(spec.name + '__new')}"
    out: list[str] = []
    if spec.geometry == "wkb":
        out += [
            f"ALTER TABLE {t} ADD COLUMN geom geometry(MultiPolygon, 4326)",
            f"UPDATE {t} SET geom = ST_Multi(ST_GeomFromWKB(geom_wkb, 4326))",
            f"ALTER TABLE {t} DROP COLUMN geom_wkb",
        ]
    elif spec.geometry == "point":
        out += [
            f"ALTER TABLE {t} ADD COLUMN geom geometry(Point, 4326)",
            f"UPDATE {t} SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326)",
        ]
    out.append(
        f"ALTER TABLE {t} ADD CONSTRAINT {ident(spec.name + '__new_pkey')} "
        f"PRIMARY KEY ({ident(spec.key)})"
    )
    if spec.geometry != "none":
        out.append(f"CREATE INDEX {ident(f'ix_{spec.name}_geom__new')} ON {t} USING gist (geom)")
    out += [
        f"CREATE INDEX {ident(f'ix_{spec.name}_{c}__new')} ON {t} ({ident(c)})" for c in spec.btree
    ]
    if spec.filtre:
        cols = ", ".join(ident(c) for c in spec.filtre)
        out.append(f"CREATE INDEX {ident(f'ix_{spec.name}_filtre__new')} ON {t} ({cols})")
    if spec.name == "dim_commune":  # recherche par préfixe (minuscules, sans accents)
        out.append(
            f"CREATE INDEX {ident('ix_dim_commune_nom__new')} ON {t} "
            f"({ident('nom_recherche')} text_pattern_ops)"
        )
    return out


def _index_names(spec: TableSpec) -> list[str]:
    names = [f"ix_{spec.name}_{c}" for c in spec.btree]
    if spec.geometry != "none":
        names.append(f"ix_{spec.name}_geom")
    if spec.filtre:
        names.append(f"ix_{spec.name}_filtre")
    if spec.name == "dim_commune":
        names.append("ix_dim_commune_nom")
    return names


def swap_sql(spec: TableSpec) -> list[str]:
    """Remplace l'ancienne table par `__new` (à exécuter dans la transaction de bascule)."""
    s, n = SCHEMA, spec.name
    out = [
        f"DROP TABLE IF EXISTS {s}.{ident(n)}",
        f"ALTER TABLE {s}.{ident(n + '__new')} RENAME TO {ident(n)}",
        f"ALTER TABLE {s}.{ident(n)} RENAME CONSTRAINT {ident(n + '__new_pkey')} "
        f"TO {ident(n + '_pkey')}",
    ]
    out += [
        f"ALTER INDEX {s}.{ident(i + '__new')} RENAME TO {ident(i)}" for i in _index_names(spec)
    ]
    return out


def iter_rows(path: Path) -> Iterator[tuple[Any, ...]]:
    for batch in pq.ParquetFile(path).iter_batches(batch_size=BATCH):
        cols = [c.to_pylist() for c in batch.columns]
        yield from zip(*cols, strict=True)


def stage_table(cur: Cursor, spec: TableSpec, path: Path) -> int:
    """Crée et remplit `gold.<t>__new` ; renvoie le nombre de lignes copiées."""
    schema = pq.read_schema(path)
    cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{ident(spec.name + '__new')}")
    cur.execute(create_sql(spec, schema))
    cols = ", ".join(ident(f.name) for f in schema)
    n = 0
    with cur.copy(f"COPY {SCHEMA}.{ident(spec.name + '__new')} ({cols}) FROM STDIN") as copy:
        for row in iter_rows(path):
            copy.write_row(row)
            n += 1
    for stmt in finish_sql(spec):
        cur.execute(stmt)
    return n


def conninfo_from_env() -> str:
    """Paramètres de connexion lus dans l'environnement (jamais journalisés)."""
    from psycopg.conninfo import make_conninfo

    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [k for k in required if k not in os.environ]
    if missing:
        raise RuntimeError(f"Variables PostgreSQL manquantes : {missing}")
    return make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


def load(gold_dir: Path, conninfo: str, specs: tuple[TableSpec, ...] = TABLES) -> dict[str, int]:
    """Charge toutes les tables, puis bascule l'ensemble d'un coup (tout ou rien)."""
    import psycopg

    files = {s.name: gold_dir / f"{s.name}.parquet" for s in specs}
    missing = [p.name for p in files.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Gold absent : {missing}. Lancer make gold (dbt build puis promotion) avant."
        )
    counts: dict[str, int] = {}
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            for spec in specs:
                counts[spec.name] = stage_table(cur, spec, files[spec.name])
                conn.commit()  # chaque `__new` est prête ; le gold en service n'a pas bougé
                logger.info("%s : %d lignes en préparation", spec.name, counts[spec.name])
            for spec in specs:
                for stmt in swap_sql(spec):
                    cur.execute(stmt)
        conn.commit()  # bascule atomique de toutes les tables
        conn.autocommit = True
        with conn.cursor() as cur:
            for spec in specs:
                cur.execute(f"ANALYZE {SCHEMA}.{ident(spec.name)}")
    return counts


def main() -> None:
    import json

    from atlas_pipelines.config import PipelineConfig

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = PipelineConfig.from_env()
    result = load(cfg.data_dir / "gold", conninfo_from_env())
    print(json.dumps(result, indent=2))  # noqa: T201 - sortie CLI


if __name__ == "__main__":
    main()
