"""Outils communs du silver DuckDB : écriture Parquet atomique d'une requête."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from atlas_pipelines.http import staging
from atlas_pipelines.spatial import sql_path


def require(path: Path, hint: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} absent : {hint}")
    return path


def write_query(
    con: duckdb.DuckDBPyConnection,
    query: str,
    dest: Path,
    params: list[Any] | None = None,
) -> int:
    """Écrit le résultat de `query` dans `dest` (fichier caché puis renommage)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging(dest)
    try:
        con.execute(
            f"COPY ({query}) TO {sql_path(tmp)} (FORMAT parquet, COMPRESSION zstd)",
            params or [],
        )
        row = con.execute(f"SELECT count(*) FROM read_parquet({sql_path(tmp)})").fetchone()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return int(row[0]) if row else 0


def count(con: duckdb.DuckDBPyConnection, path: Path, where: str = "true") -> int:
    """Nombre de lignes d'un Parquet (`where` : condition interne, jamais une saisie)."""
    row = con.execute(f"SELECT count(*) FROM read_parquet({sql_path(path)}) WHERE {where}")
    res = row.fetchone()
    return int(res[0]) if res else 0
