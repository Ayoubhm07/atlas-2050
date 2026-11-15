"""Conversion CSV(.gz) → Parquet via DuckDB, colonnes lues en texte (pas d'inférence)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from atlas_pipelines.http import staging


def _quote(path: Path) -> str:
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def csv_to_parquet(
    src: Path,
    dest: Path,
    *,
    sep: str = ",",
    where: str | None = None,
) -> int:
    """Écrit `dest` (atomique) et renvoie le nombre de lignes écrites.

    Toutes les colonnes restent en VARCHAR : codes INSEE et départements gardent
    leurs zéros initiaux ; le typage se fait en silver.
    `where` est une condition SQL interne (jamais issue d'une saisie utilisateur).
    """
    if len(sep) != 1 or sep == "'":
        raise ValueError(f"Séparateur invalide : {sep!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging(dest)
    # quote/escape explicites : l'auto-détection se fie à un échantillon et rate les
    # champs entre guillemets rares (ex. DVF « "Pierraille, pierrier" » ligne 584 909).
    read = (
        f"read_csv({_quote(src)}, delim='{sep}', quote='\"', escape='\"', "
        "header=true, all_varchar=true)"
    )
    query = f"SELECT * FROM {read}" + (f" WHERE {where}" if where else "")
    with duckdb.connect() as con:
        con.execute(f"COPY ({query}) TO {_quote(tmp)} (FORMAT parquet, COMPRESSION zstd)")
        rows: int = con.execute(f"SELECT count(*) FROM read_parquet({_quote(tmp)})").fetchone()[0]  # type: ignore[index]
    tmp.replace(dest)
    return rows
