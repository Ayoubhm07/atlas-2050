"""Configuration des pipelines, lue depuis l'environnement et validée."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# métropole 01-95 (20 remplacé par 2A/2B) ou DOM 971-976 ; « 97 » seul est refusé car
# un filtre starts_with('97') capterait tous les DOM.
_DEP_RE = re.compile(r"^(0[1-9]|1\d|2[1-9]|[3-8]\d|9[0-5]|2A|2B|97[1-6])$")
_PERIODE_RE = re.compile(r"^\d{4}(-s[12])?$")

DEFAULT_DEPARTEMENTS = "33,13,59"
DEFAULT_DVF_PERIODES = "2021-s2,2022,2023,2024,2025,2026-s1"


def _split(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


@dataclass(frozen=True)
class PipelineConfig:
    data_dir: Path
    departements: tuple[str, ...]
    dvf_periodes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.departements:
            raise ValueError("Aucun département configuré (ATLAS_DEPARTEMENTS)")
        bad = [d for d in self.departements if not _DEP_RE.match(d)]
        if bad:
            raise ValueError(f"Codes département invalides : {bad}")
        bad_p = [p for p in self.dvf_periodes if not _PERIODE_RE.match(p)]
        if bad_p:
            raise ValueError(f"Périodes DVF invalides (attendu 2024 ou 2021-s2) : {bad_p}")

    @classmethod
    def from_env(cls) -> PipelineConfig:
        return cls(
            data_dir=Path(os.environ.get("ATLAS_DATA_DIR", "./data")).resolve(),
            departements=_split(os.environ.get("ATLAS_DEPARTEMENTS", DEFAULT_DEPARTEMENTS)),
            dvf_periodes=_split(os.environ.get("ATLAS_DVF_PERIODES", DEFAULT_DVF_PERIODES)),
        )

    def raw(self, source: str) -> Path:
        """Fichiers téléchargés tels quels (non versionnés)."""
        return self.data_dir / "raw" / source

    def bronze(self, source: str) -> Path:
        return self.data_dir / "bronze" / source

    def silver(self, source: str) -> Path:
        return self.data_dir / "silver" / source
