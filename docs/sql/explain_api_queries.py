"""EXPLAIN ANALYZE des requêtes de api_queries.sql sur la base PostGIS chargée.

Usage (depuis la racine, variables POSTGRES_* chargées depuis .env) :
    pipelines/.venv/Scripts/python.exe docs/sql/explain_api_queries.py
Chaque requête est exécutée 1 fois à blanc puis 10 fois ; on garde la médiane de
« Execution Time » (cache chaud, comme en service).
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines"))
from atlas_pipelines.load.postgis import conninfo_from_env  # noqa: E402

PARAMS: dict[str, tuple[object, ...]] = {
    # emprise de Bordeaux Métropole (≈ 25 × 20 km), maisons et appartements, 2024
    "hex_aggregates": (9, -0.75, 44.75, -0.45, 44.95, "tous", "2024", "tous"),
    "commune_search": ("bord",),
    "point_lookup": (-0.5792, 44.8378),  # Bordeaux centre
    "commune_transaction_stats": ("33063",),
    "commune_risks": ("33063",),
}
SEARCH_CHECKS = ("étau", "Étau", "ETAU", "etau")


def queries(path: Path) -> dict[str, str]:
    blocks = re.split(r"^-- name: (\w+)\s*$", path.read_text(encoding="utf-8"), flags=re.M)
    return {name: body.strip() for name, body in zip(blocks[1::2], blocks[2::2], strict=True)}


def to_psycopg(query: str, params: tuple[object, ...]) -> tuple[str, dict[str, object]]:
    """$1, $2... (style PostgreSQL) → %(p1)s pour psycopg ; les % littéraux sont doublés."""
    text = re.sub(r"\$(\d+)", r"%(p\1)s", query.rstrip(";").replace("%", "%%"))
    return text, {f"p{i}": v for i, v in enumerate(params, start=1)}


def main() -> None:
    sql = queries(Path(__file__).with_name("api_queries.sql"))
    with psycopg.connect(conninfo_from_env()) as conn, conn.cursor() as cur:
        # étalon CPU du serveur : à comparer d'une machine à l'autre
        cur.execute("EXPLAIN ANALYZE SELECT count(*) FROM generate_series(1, 1000000)")
        print("étalon generate_series(1e6) :", cur.fetchall()[-1][0])
        for name, query in sql.items():
            timings, plan = [], ""
            text, params = to_psycopg(query, PARAMS[name])
            for i in range(11):
                cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + text, params)
                plan = "\n".join(r[0] for r in cur.fetchall())
                ms = float(re.search(r"Execution Time: ([\d.]+) ms", plan).group(1))  # type: ignore[union-attr]
                if i:
                    timings.append(ms)
            cur.execute(text, params)
            rows = len(cur.fetchall())
            print(f"## {name} : médiane {statistics.median(timings):.2f} ms "
                  f"(max {max(timings):.2f}), {rows} lignes\n```\n{plan}\n```\n")
        # recherche insensible à la casse et aux accents : mêmes communes attendues
        for saisie in SEARCH_CHECKS:
            cur.execute(*to_psycopg(sql["commune_search"], (saisie,)))
            print(f"commune_search({saisie!r}) :", [r[1] for r in cur.fetchall()])


if __name__ == "__main__":
    main()
