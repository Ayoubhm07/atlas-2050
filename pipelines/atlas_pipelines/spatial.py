"""Connexion DuckDB avec l'extension `spatial` (GDAL, géométries, WKB)."""

from __future__ import annotations

from pathlib import Path

import duckdb


def sql_path(path: Path | str) -> str:
    """Chemin en littéral SQL (barres obliques, apostrophes doublées)."""
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def connect_spatial() -> duckdb.DuckDBPyConnection:
    """Connexion en mémoire avec `spatial` chargée (installée au premier appel)."""
    con = duckdb.connect()
    try:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
    except duckdb.Error as exc:
        con.close()
        raise RuntimeError(
            "Extension DuckDB `spatial` indisponible (réseau requis au premier usage) : "
            f"{exc}"
        ) from exc
    return con
