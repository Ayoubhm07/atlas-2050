"""Contours IRIS (IGN, GeoPackage WGS84 dans une archive 7z) → Parquet géométrie WKB.

Édition retenue : 2026-01-01. Mesure du 2026-11-15 sur la Gironde : les 339 codes IRIS
de Filosofi 2021 existent tous dans cette édition (100 %), inutile de chercher une
édition plus ancienne (docs/quality/gold_33_2024.md).

Extraction : seul le fichier `.gpkg` est décompressé, vers un nom de fichier fixé par
nous ; le chemin stocké dans l'archive n'est jamais utilisé (pas de traversée de
répertoire possible, et pas de chemin Windows trop long).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

import httpx
import py7zr
from py7zr.io import Py7zIO, WriterFactory

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import download, staging
from atlas_pipelines.spatial import connect_spatial, sql_path

logger = logging.getLogger(__name__)

EDITION = "CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01"
URL = (
    "https://data.geopf.fr/telechargement/download/CONTOURS-IRIS/"
    f"{EDITION}/{EDITION}.7z"
)
MAX_GPKG_BYTES = 2 * 1024**3  # 172 Mo en 2026 : au-delà, archive suspecte
FIELDS = ("code_iris", "code_insee", "nom_commune", "nom_iris", "type_iris", "geometrie")


class _FileSink(Py7zIO):
    """Écrit un membre de l'archive dans un fichier choisi par nous, avec plafond de taille."""

    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh
        self._size = 0

    def write(self, s: bytes | bytearray) -> int:
        self._size += len(s)
        if self._size > MAX_GPKG_BYTES:
            raise ValueError(f"GeoPackage > {MAX_GPKG_BYTES} octets : archive refusée")
        return self._fh.write(s)

    def read(self, size: int | None = None) -> bytes:
        return b""

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._fh.seek(offset, whence)

    def flush(self) -> None:
        self._fh.flush()

    def size(self) -> int:
        return self._size


class _SingleFileFactory(WriterFactory):
    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh

    def create(self, filename: str) -> Py7zIO:
        return _FileSink(self._fh)


def extract_gpkg(archive: Path, dest: Path) -> Path:
    """Extrait l'unique `.gpkg` de l'archive vers `dest` (écriture atomique)."""
    with py7zr.SevenZipFile(archive) as z:
        names = [n for n in z.getnames() if n.lower().endswith(".gpkg")]
        if len(names) != 1:
            raise ValueError(f"GeoPackage attendu unique dans {archive.name}, trouvé {names}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = staging(dest)
        try:
            with tmp.open("wb") as fh:
                z.extract(targets=names, factory=_SingleFileFactory(fh))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    if tmp.stat().st_size == 0:
        tmp.unlink()
        raise ValueError(f"GeoPackage vide dans {archive.name}")
    tmp.replace(dest)
    return dest


def gpkg_to_parquet(gpkg: Path, dest: Path, departements: tuple[str, ...]) -> int:
    """IRIS des départements demandés : codes + géométrie en WKB (EPSG:4326, lon/lat).

    Écriture atomique : le `.part` est supprimé si quoi que ce soit échoue.
    """
    if not departements:
        # sans département, le filtre SQL serait vide (erreur ou France entière)
        raise ValueError("Aucun département demandé pour les contours IRIS")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging(dest)
    try:
        with connect_spatial() as con:
            con.execute(f"CREATE VIEW src AS SELECT * FROM ST_Read({sql_path(gpkg)})")
            cols = {r[0] for r in con.execute("DESCRIBE src").fetchall()}
            missing = [f for f in FIELDS if f not in cols]
            if missing:
                raise ValueError(f"Champs absents du GeoPackage IRIS : {missing} (trouvés {cols})")
            where = " OR ".join("starts_with(code_insee, ?)" for _ in departements)
            con.execute(
                f"""COPY (
                    SELECT code_iris, code_insee, nom_commune, nom_iris, type_iris,
                           ST_AsWKB(geometrie) AS geom_wkb
                    FROM src WHERE {where} ORDER BY code_iris
                ) TO {sql_path(tmp)} (FORMAT parquet, COMPRESSION zstd)""",
                list(departements),
            )
            row = con.execute(f"SELECT count(*) FROM read_parquet({sql_path(tmp)})").fetchone()
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return int(row[0]) if row else 0


def ingest(cfg: PipelineConfig, client: httpx.Client) -> dict[str, int]:
    raw = download(client, URL, cfg.raw("iris") / f"{EDITION}.7z")
    gpkg = extract_gpkg(cfg.raw("iris") / raw.path, cfg.raw("iris") / "iris.gpkg")
    n = gpkg_to_parquet(gpkg, cfg.bronze("iris") / "contours_iris.parquet", cfg.departements)
    logger.info("Contours IRIS %s : %d IRIS", EDITION, n)
    return {"contours_iris": n}
