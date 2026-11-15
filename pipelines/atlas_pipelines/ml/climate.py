"""Interface des projections climatiques DRIAS (RCP 4.5 / 8.5) — lecture seule.

DRIAS n'a pas d'API : les fichiers sont déposés à la main puis convertis en bronze par
`atlas_pipelines.sources.drias` (`data/bronze/drias/{indicateur}_{scenario}_{horizon}
.parquet`). Ce module lit ce bronze et ÉCHOUE EXPLICITEMENT si un fichier manque :
aucune valeur climatique n'est jamais inventée, interpolée depuis une autre source ou
remplacée par une valeur par défaut.

Même avec les fichiers, le passage « exposition climatique → prix » n'est pas estimé :
il faudrait une relation prix/indicateur mesurée sur les ventes (indicateur de la
période de référence au point de chaque vente). `climate_price_factor` lève donc
`ClimatePriceEffectNotEstimated` tant que cette estimation n'existe pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from atlas_pipelines.sources.drias import HORIZONS, SCENARIOS

Scenario = Literal["rcp45", "rcp85"]


class DriasUnavailableError(RuntimeError):
    """Les fichiers DRIAS nécessaires ne sont pas dans le bronze."""


class ClimatePriceEffectNotEstimated(RuntimeError):
    """Aucune relation prix ↔ indicateur climatique n'a été estimée sur les données."""


@dataclass(frozen=True)
class DriasClimate:
    bronze_dir: Path
    lat_col: str = "latitude"
    lon_col: str = "longitude"

    def path(self, indicateur: str, scenario: str, horizon: str) -> Path:
        if scenario not in SCENARIOS:
            raise ValueError(f"Scénario inconnu : {scenario} (attendu {sorted(SCENARIOS)})")
        if horizon not in HORIZONS:
            raise ValueError(f"Horizon inconnu : {horizon} (attendu {sorted(HORIZONS)})")
        return self.bronze_dir / f"{indicateur}_{scenario}_{horizon}.parquet"

    def load(self, indicateur: str, scenario: str, horizon: str) -> pd.DataFrame:
        path = self.path(indicateur, scenario, horizon)
        if not path.is_file():
            raise DriasUnavailableError(
                f"Projection DRIAS absente : {path}. DRIAS exige un compte (pas d'API) : "
                "déposer les CSV dans data/raw/drias avec manifest.json puis lancer "
                "`python -m atlas_pipelines.cli drias`. Aucune valeur n'est inventée."
            )
        df = pd.read_parquet(path)
        missing = [c for c in (self.lat_col, self.lon_col) if c not in df.columns]
        if missing:
            raise DriasUnavailableError(
                f"{path.name} : colonnes {missing} absentes (colonnes : {list(df.columns)})"
            )
        return df

    def value_at(
        self, lon: float, lat: float, indicateur: str, scenario: str, horizon: str, column: str
    ) -> float:
        """Valeur du point de grille le plus proche (grille SAFRAN 8 km)."""
        df = self.load(indicateur, scenario, horizon)
        if column not in df.columns:
            raise DriasUnavailableError(f"Colonne {column!r} absente de {indicateur}")
        d2 = (df[self.lat_col].to_numpy(float) - lat) ** 2 + (
            (df[self.lon_col].to_numpy(float) - lon) * np.cos(np.radians(lat))
        ) ** 2
        return float(df[column].to_numpy(float)[int(np.argmin(d2))])


def climate_price_factor(
    climate: DriasClimate | None, scenario: Scenario, horizon: int
) -> tuple[float, float, float]:
    """Facteur prix climatique (bas, central, haut). Échoue tant qu'il n'est pas estimable."""
    if climate is None:
        raise DriasUnavailableError(
            f"Scénario {scenario} {horizon} demandé sans données DRIAS (accès bloqué : "
            "compte requis). La projection climatique n'est pas calculée."
        )
    available = sorted(p.name for p in climate.bronze_dir.glob(f"*_{scenario}_*.parquet"))
    if not available:
        raise DriasUnavailableError(
            f"Aucun fichier {scenario} dans {climate.bronze_dir} : projection impossible."
        )
    raise ClimatePriceEffectNotEstimated(
        f"Fichiers DRIAS présents ({available}) mais la relation prix ↔ indicateur n'est "
        "pas encore estimée sur les ventes : aucun facteur climatique n'est appliqué."
    )
