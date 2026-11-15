"""DPE ADEME (logements existants depuis juillet 2021) via l'API data-fair, paginée par curseur."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import RateLimiter, get_json, staging

logger = logging.getLogger(__name__)

LINES_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
ALLOWED_HOST = "data.ademe.fr"
PAGE_SIZE = 5000
MAX_PAGES = 1000  # 5 M de lignes par département : très au-delà du réel (~610 k pour le 59)
FIELDS = (
    "numero_dpe",
    "identifiant_ban",
    "code_insee_ban",
    "etiquette_dpe",
    "etiquette_ges",
    "date_etablissement_dpe",
    "surface_habitable_logement",
    "type_batiment",
    "periode_construction",
    "_geopoint",
)


def iter_pages(
    client: httpx.Client, dep: str, limiter: RateLimiter
) -> Iterator[list[dict[str, Any]]]:
    url: str = LINES_URL
    params: dict[str, Any] | None = {
        "size": PAGE_SIZE,
        "qs": f"code_departement_ban:{dep}",
        "select": ",".join(FIELDS),
    }
    for _ in range(MAX_PAGES):
        page = get_json(client, url, params=params, limiter=limiter)
        rows = page.get("results", [])
        if rows:
            yield rows
        url = page.get("next")
        if not url:
            return
        params = None  # le curseur `next` contient déjà tous les paramètres
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise ValueError(f"Lien de pagination inattendu, refusé : {url}")
    raise RuntimeError(f"DPE dép {dep} : plus de {MAX_PAGES} pages, abandon (curseur en boucle ?)")


def _to_table(rows: list[dict[str, Any]]) -> pa.Table:
    cols = {f: [None if r.get(f) is None else str(r[f]) for r in rows] for f in FIELDS}
    return pa.table({f: pa.array(v, type=pa.string()) for f, v in cols.items()})


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    limiter = RateLimiter(calls_per_second=4)
    counts: dict[str, int] = {}
    for dep in cfg.departements:
        dest = cfg.bronze("dpe") / f"dep={dep}.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = staging(dest)
        total = 0
        schema = _to_table([]).schema
        try:
            with pq.ParquetWriter(tmp, schema, compression="zstd") as writer:
                for rows in iter_pages(client, dep, limiter):
                    writer.write_table(_to_table(rows))
                    total += len(rows)
        except BaseException:
            tmp.unlink(missing_ok=True)  # jamais de fichier partiel mais lisible
            raise
        tmp.replace(dest)
        counts[dep] = total
        logger.info("DPE dép %s : %d diagnostics", dep, total)
    return counts
