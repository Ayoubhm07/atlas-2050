"""Plans de prévention des risques naturels (GASPAR PPRN) par commune, Géorisques API v1.

Endpoint vérifié le 2026-11-15 dans l'OpenAPI v1 : `GET /api/v1/gaspar/pprn`
(paramètres `codeInsee`, `page` à partir de 1, `page_size`). Réponse paginée au format
Spring : `content`, `totalPages`, `totalElements` (différent de catnat/tri/azi).
`modeleProcedure` distingue PPRN-I (inondation), PPRN-L (littoral, submersion marine),
PPRN-IF (incendie de forêt), PPRN-Mvt (mouvement de terrain), etc.

Pour la Gironde, sans AZI, les PPRI + TRI sont le signal inondation (data-contract §4).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import RateLimiter, get_json
from atlas_pipelines.sources.georisques import communes_from_ban, write_payloads

logger = logging.getLogger(__name__)

URL = "https://georisques.gouv.fr/api/v1/gaspar/pprn"
PAGE_SIZE = 100
MAX_PAGES = 20


def fetch_pprn(client: httpx.Client, code_insee: str, limiter: RateLimiter) -> list[dict[str, Any]]:
    """Toutes les procédures PPRN d'une commune ; pagination par numéro, jamais par lien."""
    rows: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        body = get_json(
            client,
            URL,
            params={"codeInsee": code_insee, "page": page, "page_size": PAGE_SIZE},
            limiter=limiter,
        )
        rows.extend(body.get("content") or [])
        if page >= int(body.get("totalPages") or 0):
            return rows
    raise RuntimeError(f"pprn {code_insee} : plus de {MAX_PAGES} pages, abandon")


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    """Une ligne par (commune, procédure) ; payload NULL = interrogée, aucune procédure."""
    limiter = RateLimiter(calls_per_second=4.5)
    communes = communes_from_ban(cfg)
    if not communes:
        raise RuntimeError("Aucune commune : lancer l'ingestion BAN avant les PPR")
    out: list[tuple[str, str, str | None]] = []
    for code in communes:
        records = fetch_pprn(client, code, limiter)
        if not records:
            out.append(("pprn", code, None))
        out.extend(("pprn", code, json.dumps(r, ensure_ascii=False)) for r in records)
    n = write_payloads(out, "pprn.parquet", cfg)
    logger.info("Géorisques pprn : %d lignes pour %d communes", n, len(communes))
    return {"pprn": n}
