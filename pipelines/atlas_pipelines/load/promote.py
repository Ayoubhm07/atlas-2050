"""Promotion du gold : `data/gold_build` (sortie de dbt) → `data/gold` (lu par le chargeur).

dbt écrit ses Parquet AVANT d'exécuter ses tests : écrire directement dans `data/gold`
publierait un gold qui échoue ensuite à ses tests. dbt écrit donc dans `gold_build`, et
ce module n'est lancé qu'après un `dbt build` réussi (`make gold`, DAG `atlas_gold`).

Tout ou rien : chaque table attendue doit exister et être un Parquet lisible ; elles
sont copiées dans un répertoire caché `.gold.new`, puis deux renommages basculent le
répertoire (`gold` → `.gold.old`, `.gold.new` → `gold`), avec retour arrière si le
second échoue. Un lecteur voit donc l'ancien jeu complet ou le nouveau, jamais un
mélange ; entre les deux renommages, `gold` est absent quelques microsecondes (aucun
lecteur concurrent dans le DAG : le chargement PostGIS suit la promotion).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pyarrow.parquet as pq

from atlas_pipelines.load.postgis import TABLES

logger = logging.getLogger(__name__)

GOLD_TABLES: tuple[str, ...] = tuple(spec.name for spec in TABLES)


def _check(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Table gold absente du build : {path}")
    try:
        pq.read_metadata(path)
    except Exception as exc:  # pyarrow lève ArrowInvalid / OSError selon le défaut
        raise ValueError(f"Parquet illisible dans le build : {path} ({exc})") from exc


def _remove(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def promote(build_dir: Path, gold_dir: Path, tables: tuple[str, ...] = GOLD_TABLES) -> list[Path]:
    """Remplace `gold_dir` par les tables `tables` de `build_dir` ; renvoie les chemins promus."""
    if not tables:
        raise ValueError("Aucune table à promouvoir")
    sources = [build_dir / f"{t}.parquet" for t in tables]
    for src in sources:
        _check(src)
    new = gold_dir.with_name(f".{gold_dir.name}.new")
    old = gold_dir.with_name(f".{gold_dir.name}.old")
    _remove(new)
    _remove(old)
    new.mkdir(parents=True)
    try:
        for src in sources:
            shutil.copy2(src, new / src.name)
    except BaseException:
        _remove(new)
        raise
    had_gold = gold_dir.exists()
    if had_gold:
        gold_dir.rename(old)
    try:
        new.rename(gold_dir)
    except BaseException:
        if had_gold:
            old.rename(gold_dir)
        _remove(new)
        raise
    _remove(old)
    logger.info("Gold promu : %d tables %s → %s", len(sources), build_dir, gold_dir)
    return [gold_dir / src.name for src in sources]


def main() -> None:
    import json

    from atlas_pipelines.config import PipelineConfig

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    data = PipelineConfig.from_env().data_dir
    out = promote(data / "gold_build", data / "gold")
    print(json.dumps([p.name for p in out], indent=2))  # noqa: T201 - sortie CLI


if __name__ == "__main__":
    main()
