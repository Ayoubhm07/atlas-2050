"""Retrait-gonflement des argiles (Géorisques `rga?latlon=lon,lat`), un appel par IRIS.

On interroge un point par IRIS (pas par bien : ~1 M d'appels sinon). Le point est
`ST_PointOnSurface` du contour : comme un centroïde, mais toujours DANS le polygone
(un centroïde d'IRIS en croissant ou littoral peut tomber dehors, voire en mer).

Constat réel (2026-11-15) : hors zone cartographiée l'API répond 200 avec un corps
vide (pas de JSON) ; on l'enregistre en payload NULL = « interrogé, pas de donnée ».
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import RateLimiter, retrying, staging
from atlas_pipelines.spatial import connect_spatial, sql_path

logger = logging.getLogger(__name__)

URL = "https://georisques.gouv.fr/api/v1/rga"


def iris_points(cfg: PipelineConfig) -> list[tuple[str, float, float]]:
    """(code_iris, lon, lat) d'un point intérieur à chaque IRIS du bronze."""
    src = cfg.bronze("iris") / "contours_iris.parquet"
    if not src.exists():
        raise FileNotFoundError(f"{src} absent : lancer l'ingestion IRIS avant la RGA")
    with connect_spatial() as con:
        rows = con.execute(
            f"""SELECT code_iris, ST_X(p), ST_Y(p) FROM (
                  SELECT code_iris, ST_PointOnSurface(ST_GeomFromWKB(geom_wkb)) AS p
                  FROM read_parquet({sql_path(src)})
                ) ORDER BY code_iris"""
        ).fetchall()
    return [(r[0], round(float(r[1]), 6), round(float(r[2]), 6)) for r in rows]


@retrying
def fetch_rga(
    client: httpx.Client, lon: float, lat: float, limiter: RateLimiter
) -> str | None:
    """Réponse JSON brute, ou None si le serveur renvoie un corps vide."""
    limiter.wait()
    res = client.get(URL, params={"latlon": f"{lon},{lat}"})
    res.raise_for_status()
    text = res.text.strip()
    if not text:
        return None
    body: Any = res.json()  # lève si ce n'est pas du JSON : on ne stocke pas n'importe quoi
    if not isinstance(body, dict):
        raise ValueError(f"Réponse RGA inattendue pour {lon},{lat} : {text[:200]}")
    return text


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    limiter = RateLimiter(calls_per_second=4.5)
    points = iris_points(cfg)
    payloads = [fetch_rga(client, lon, lat, limiter) for _, lon, lat in points]
    table = pa.table(
        {
            "code_iris": pa.array([p[0] for p in points], pa.string()),
            "lon": pa.array([p[1] for p in points], pa.float64()),
            "lat": pa.array([p[2] for p in points], pa.float64()),
            "payload": pa.array(payloads, pa.string()),
        }
    )
    dest = cfg.bronze("georisques") / "rga.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging(dest)
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(dest)
    found = sum(p is not None for p in payloads)
    logger.info("RGA : %d IRIS interrogés, %d avec donnée", len(points), found)
    return {"rga": len(points), "rga_avec_donnee": found}
