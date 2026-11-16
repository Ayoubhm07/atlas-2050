"""Faux dépôt, faux géocodeur et petit modèle LightGBM : tests sans base ni réseau."""

import datetime as dt
import shutil
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from atlas_pipelines.ml.models import NUMERIC
from fastapi.testclient import TestClient

from atlas_api.config import Settings
from atlas_api.db import HexFilter, PointContext, ReferenceSale
from atlas_api.estimator import Estimator, load_bundle
from atlas_api.geocode import AddressNotFoundError, GeocodedPoint, GeocodingError
from atlas_api.main import create_app
from atlas_api.schemas import CommuneHit, CommuneRisques, CommuneStats, HexCell, StatsGroupe

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "ml" / "results.json"
BORDEAUX = (-0.5792, 44.8378)
VALUATION = dt.date(2025, 1, 1)

CONTEXT = PointContext(
    code_iris="330630101",
    code_insee="33063",
    nom_commune="Bordeaux",
    revenu_median=24000.0,
    gini=0.3,
    rga_code=1,
    rga_exposition="faible",
    n_catnat_10ans=1,
    in_tri=True,
    ppri=False,
    azi=None,
)


@dataclass
class FakeRepository:
    up: bool = True
    hexes: list[HexCell] = field(default_factory=list)
    context: PointContext | None = CONTEXT
    valuation: dt.date | None = VALUATION
    calls: list[tuple[str, object]] = field(default_factory=list)

    def ping(self) -> bool:
        return self.up

    def search_communes(self, prefix: str) -> list[CommuneHit]:
        self.calls.append(("search", prefix))
        hits = [
            CommuneHit(code_insee="33063", nom_commune="Bordeaux", code_departement="33",
                       lon=-0.57, lat=44.85),
            CommuneHit(code_insee="33162", nom_commune="Étauliers", code_departement="33",
                       lon=-0.57, lat=45.22),
        ]
        return [h for h in hits if h.nom_commune.lower().replace("é", "e").startswith(prefix)]

    def hex_cells(self, f: HexFilter) -> list[HexCell]:
        self.calls.append(("hex", f))
        return self.hexes[: f.limit]

    def commune_stats(self, code_insee: str) -> CommuneStats | None:
        if code_insee != "33063":
            return None
        g = StatsGroupe(type_local="Maison", annee=2024, n_ventes=7, prix_m2_q1=None,
                        prix_m2_median=4520.0, prix_m2_q3=None, surface_mediane=100.0)
        return CommuneStats(code_insee=code_insee, groupes=(g,))

    def commune_risks(self, code_insee: str) -> CommuneRisques | None:
        if code_insee != "33063":
            return None
        return CommuneRisques(code_insee="33063", nom_commune="Bordeaux", n_catnat=12,
                              n_catnat_10ans=1, date_reference=dt.date(2026, 11, 1),
                              in_tri=True, ppri=False, n_ppr=2, azi=None,
                              rga_iris={"faible": 10})

    def point_context(self, lon: float, lat: float) -> PointContext | None:
        self.calls.append(("point", (lon, lat)))
        return self.context

    def valuation_date(self) -> dt.date | None:
        return self.valuation

    def reference_sales(
        self, type_local: str, cells: Sequence[str], before: dt.date, k: int, n_prior: int
    ) -> list[ReferenceSale]:
        self.calls.append(("sales", (type_local, tuple(cells), before)))
        rng = np.random.default_rng(1)
        cell = sorted(cells)[0]
        return [
            ReferenceSale(before - dt.timedelta(days=i + 1), cell, float(rng.normal(4500, 300)))
            for i in range(40)
        ]


class FakeGeocoder:
    def __init__(self, outcome: str = "ok") -> None:
        self.outcome = outcome
        self.seen: list[str] = []

    def geocode(self, address: str) -> GeocodedPoint:
        self.seen.append(address)
        if self.outcome == "notfound":
            raise AddressNotFoundError("x")
        if self.outcome == "down":
            raise GeocodingError("x")
        return GeocodedPoint(BORDEAUX[0], BORDEAUX[1], 0.93, "33063")


def _train_tiny_model(path: Path) -> None:
    """Booster minuscule aux mêmes colonnes que le vrai modèle global."""
    rng = np.random.default_rng(0)
    n = 400
    X = pd.DataFrame({c: rng.normal(size=n) for c in NUMERIC})
    X["est_maison"] = rng.integers(0, 2, n).astype(float)
    # voisinage sur l'échelle réelle (log €/m² ≈ 7-9) : le modèle y est sensible, ce qui
    # rend les tests de confidentialité du voisinage probants
    X["voisinage_log_prix"] = rng.normal(8.0, 0.5, n)
    y = 8.3 + 0.8 * (X["voisinage_log_prix"] - 8.0) - 0.1 * X["log_surface"] + rng.normal(0, 0.1, n)
    booster = lgb.train(
        {"objective": "regression", "verbose": -1, "num_leaves": 7, "seed": 0},
        lgb.Dataset(X, y),
        num_boost_round=20,
    )
    booster.save_model(str(path))


@pytest.fixture(scope="session")
def ml_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("ml")
    (d / "models").mkdir()
    shutil.copy(RESULTS, d / "results.json")  # results.json est versionné (sprint 3)
    _train_tiny_model(d / "models" / "lgb_global.txt")
    return d


@pytest.fixture(scope="session")
def estimator(ml_dir: Path) -> Estimator:
    return Estimator(load_bundle(ml_dir), n_draws=2000)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        atlas_departements="33,13",
        api_cors_origins="http://a",
        api_rate_limit="1000/minute",
        api_hex_max_rows=3,
    )


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository(hexes=[HexCell(h3=f"87{i}", n_ventes=5 + i, prix_m2_median=3000)
                                 for i in range(3)])


@pytest.fixture
def geocoder() -> FakeGeocoder:
    return FakeGeocoder()


@pytest.fixture
def client(
    settings: Settings, repo: FakeRepository, estimator: Estimator, geocoder: FakeGeocoder
) -> Iterator[TestClient]:
    app = create_app(settings, repository=repo, estimator=estimator, geocoder=geocoder)
    with TestClient(app) as c:
        yield c


def make_client(settings: Settings, **kwargs: object) -> TestClient:
    return TestClient(create_app(settings, **kwargs))  # type: ignore[arg-type]


__all__ = ["FakeRepository", "FakeGeocoder", "make_client", "replace"]
