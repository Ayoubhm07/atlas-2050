"""Projections climatiques DRIAS : dépôt manuel (compte requis, pas d'API).

Une personne de l'équipe télécharge les indicateurs depuis drias-climat.fr et les
dépose dans `data/raw/drias/`, avec un `manifest.json` décrivant chaque fichier.
Ce module vérifie ce dépôt et le convertit en bronze ; il échoue clairement sinon.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.sources.csv_to_parquet import csv_to_parquet

logger = logging.getLogger(__name__)

SCENARIOS = frozenset({"rcp45", "rcp85"})
REQUIRED_SCENARIOS = SCENARIOS


HORIZONS = frozenset({"2030", "2050"})
_INDICATEUR_RE = re.compile(r"^[a-z0-9_]{1,40}$")


@dataclass(frozen=True)
class DriasFile:
    file: str
    indicateur: str
    scenario: str
    horizon: str
    sha256: str
    telecharge_le: str

    @property
    def output_name(self) -> str:
        return f"{self.indicateur}_{self.scenario}_{self.horizon}.parquet"


class DriasDepotError(RuntimeError):
    """Le dépôt manuel DRIAS est absent ou incomplet."""


def load_manifest(raw_dir: Path) -> list[DriasFile]:
    path = raw_dir / "manifest.json"
    if not path.exists():
        raise DriasDepotError(
            f"{path} introuvable. Créer un compte sur drias-climat.fr, télécharger les "
            "indicateurs (CSV, RCP 4.5 et 8.5) puis décrire chaque fichier dans manifest.json. "
            "Voir docs/data-contract.md §6."
        )
    entries = [DriasFile(**e) for e in json.loads(path.read_text(encoding="utf-8"))]
    if not entries:
        raise DriasDepotError("manifest.json est vide")
    bad = [e.scenario for e in entries if e.scenario not in SCENARIOS]
    if bad:
        raise DriasDepotError(f"Scénarios inconnus : {bad} (attendu {sorted(SCENARIOS)})")
    missing = REQUIRED_SCENARIOS - {e.scenario for e in entries}
    if missing:
        raise DriasDepotError(f"Scénarios manquants : {sorted(missing)}")
    bad_h = [e.horizon for e in entries if e.horizon not in HORIZONS]
    if bad_h:
        raise DriasDepotError(f"Horizons inconnus : {bad_h} (attendu {sorted(HORIZONS)})")
    bad_i = [e.indicateur for e in entries if not _INDICATEUR_RE.match(e.indicateur)]
    if bad_i:
        raise DriasDepotError(f"Noms d'indicateur invalides (a-z, 0-9, _) : {bad_i}")
    names = [e.output_name for e in entries]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise DriasDepotError(f"Entrées en double (même indicateur/scénario/horizon) : {dupes}")
    return entries


def verify(raw_dir: Path, entry: DriasFile) -> Path:
    path = raw_dir / Path(entry.file).name
    if not path.exists():
        raise DriasDepotError(f"Fichier déclaré mais absent : {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.sha256:
        raise DriasDepotError(f"Checksum invalide pour {path.name}")
    return path


def ingest(cfg: PipelineConfig) -> dict[str, int]:
    raw_dir = cfg.raw("drias")
    counts: dict[str, int] = {}
    for entry in load_manifest(raw_dir):
        src = verify(raw_dir, entry)
        name = entry.output_name
        counts[name] = csv_to_parquet(src, cfg.bronze("drias") / name, sep=";")
        logger.info("DRIAS %s : %d lignes", name, counts[name])
    return counts
