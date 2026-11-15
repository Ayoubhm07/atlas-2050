"""Géorisques API v1 : Cat-Nat, TRI et AZI par commune (5 appels/s maximum).

Le champ `next` des réponses pointe vers un hôte interne du BRGM : on pagine par
numéro de page et on ne suit jamais ce lien.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

import duckdb
import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import RateLimiter, get_json, staging

logger = logging.getLogger(__name__)

BASE = "https://georisques.gouv.fr/api/v1/gaspar"
ENDPOINTS = ("catnat", "tri", "azi")
PAGE_SIZE = 100
MAX_PAGES = 50


def fetch_all(
    client: httpx.Client, endpoint: str, code_insee: str, limiter: RateLimiter
) -> list[dict[str, Any]]:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Endpoint Géorisques inconnu : {endpoint}")
    rows: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        body = get_json(
            client,
            f"{BASE}/{endpoint}",
            params={"code_insee": code_insee, "page": page, "page_size": PAGE_SIZE},
            limiter=limiter,
        )
        rows.extend(body.get("data") or [])
        if page >= int(body.get("total_pages") or 0):
            return rows
    raise RuntimeError(f"{endpoint} {code_insee} : plus de {MAX_PAGES} pages, abandon")


def communes_from_ban(cfg: PipelineConfig) -> list[str]:
    pattern = str(cfg.bronze("ban") / "*.parquet").replace("\\", "/")
    with duckdb.connect() as con:
        rows = con.execute(
            "SELECT DISTINCT code_insee FROM read_parquet(?) WHERE code_insee IS NOT NULL "
            "ORDER BY 1",
            [pattern],
        ).fetchall()
    return [r[0] for r in rows]


def write_payloads(
    rows: Iterable[tuple[str, str, str | None]], dest_name: str, cfg: PipelineConfig
) -> int:
    data = list(rows)
    table = pa.table(
        {
            "endpoint": pa.array([r[0] for r in data], pa.string()),
            "code_insee": pa.array([r[1] for r in data], pa.string()),
            "payload": pa.array([r[2] for r in data], pa.string()),
        }
    )
    dest = cfg.bronze("georisques") / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging(dest)
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(dest)
    return len(data)


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    """Une ligne par (endpoint, commune, enregistrement) ; payload JSON brut conservé.

    Une commune sans enregistrement reçoit une ligne `payload` NULL : on distingue
    « interrogée, rien trouvé » de « jamais interrogée ».
    """
    limiter = RateLimiter(calls_per_second=4.5)
    communes = communes_from_ban(cfg)
    if not communes:
        raise RuntimeError("Aucune commune : lancer l'ingestion BAN avant Géorisques")
    counts: dict[str, int] = {}
    for endpoint in ENDPOINTS:
        out: list[tuple[str, str, str | None]] = []
        for code in communes:
            records = fetch_all(client, endpoint, code, limiter)
            if not records:
                out.append((endpoint, code, None))  # vrai NULL SQL
            out.extend((endpoint, code, json.dumps(r, ensure_ascii=False)) for r in records)
        counts[endpoint] = write_payloads(out, f"{endpoint}.parquet", cfg)
        logger.info("Géorisques %s : %d lignes pour %d communes", endpoint, len(out), len(communes))
    return counts
