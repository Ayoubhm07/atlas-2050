import datetime as dt
import logging
from dataclasses import replace
from pathlib import Path

import h3
import numpy as np
import pytest
from atlas_pipelines.ml.projection import NON_CAUSAL
from fastapi.testclient import TestClient

from atlas_api.config import Settings
from atlas_api.db import ReferenceSale
from atlas_api.estimator import (
    Estimator,
    ModelUnavailableError,
    feature_row,
    load_bundle,
    neighbour_features,
    t_mois,
)
from atlas_api.schemas import EstimateQuery, Localisation
from tests.conftest import CONTEXT, VALUATION, FakeGeocoder, FakeRepository, make_client

POINT = {"lat": 44.8378, "lon": -0.5792}
HOUSE = {"type_local": "Maison", "surface": 96, "pieces": 4, "surface_terrain": 760}
LOC = Localisation(code_insee="33063", nom_commune="Bordeaux", code_iris="330630101",
                   source="coordonnees")


def _scenarios(body: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {s["id"]: s for s in body["data"]["scenarios"]}


# --- route ------------------------------------------------------------------------


def test_estimate_by_coordinates(client: TestClient, repo: FakeRepository) -> None:
    res = client.get("/estimate", params={**POINT, **HOUSE, "dpe": "G"})
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    assert "etag" not in res.headers
    data = res.json()["data"]
    p = data["prix_m2"]
    assert p["p10"] < p["p50"] < p["p90"]
    assert p["p50"] % 10 == 0
    assert data["valeur"]["p50"] % 1000 == 0
    assert data["date_valeur"] == VALUATION.isoformat()
    assert data["localisation"]["source"] == "coordonnees"
    assert data["risques_actuels"]["termes"] == ["in_tri"]
    # ventes de référence : même type, cellules de l'anneau r7, avant la date de valeur
    kind, args = repo.calls[-1]
    assert kind == "sales" and isinstance(args, tuple)
    assert (args[0], args[2], len(args[1])) == ("Maison", VALUATION, 7)


def test_estimate_scenarios_contract(client: TestClient) -> None:
    body = client.get("/estimate", params={**POINT, **HOUSE, "dpe": "G"}).json()
    sc = _scenarios(body)
    assert sc["statu_quo"]["statut"] == "calcule"
    assert sc["statu_quo"]["location_interdite_depuis"] == 2025
    assert sc["renovation_D"]["statut"] == "calcule"
    assert "coût de la rénovation" in sc["renovation_D"]["non_inclus"]
    # risque déjà présent : pas de double comptage
    assert sc["nouveau_risque_in_tri"]["statut"] == "non_applicable"
    ppri = sc["nouveau_risque_ppri"]
    assert ppri["statut"] == "calcule"
    assert NON_CAUSAL in ppri["libelle"]
    sens = ppri["sensibilite"]
    assert sens["statut"] == NON_CAUSAL
    assert set(sens) >= {"avec_voisinage", "sans_voisinage"}
    assert ppri["prix_m2"]["p10"] <= min(sens["avec_voisinage"]["p10"],
                                         sens["sans_voisinage"]["p10"]) + 10
    for rcp in ("climat_rcp45", "climat_rcp85"):
        assert sc[rcp]["statut"] == "indisponible (DRIAS)"
        assert sc[rcp]["prix_m2"] is None and sc[rcp]["valeur"] is None


def test_estimate_without_dpe_has_no_renovation(client: TestClient) -> None:
    body = client.get("/estimate", params={**POINT, **HOUSE}).json()
    sc = _scenarios(body)
    assert sc["renovation_D"]["statut"] == "non_applicable"
    assert sc["statu_quo"]["location_interdite_depuis"] is None
    assert any("DPE inconnu" in x for x in sc["statu_quo"]["non_inclus"])


def test_estimate_factors_hide_neighbour_values(client: TestClient) -> None:
    facteurs = client.get("/estimate", params={**POINT, **HOUSE}).json()["data"]["facteurs"]
    assert 1 <= len(facteurs) <= 6
    by_name = {f["variable"]: f for f in facteurs}
    for hidden in ("voisinage_log_prix", "voisinage_n", "lon", "lat", "t_mois"):
        if hidden in by_name:
            assert by_name[hidden]["valeur"] is None
    if "log_surface" in by_name:
        assert by_name["log_surface"]["valeur"] == 96


def test_estimate_waterfall_closes_on_model_prediction(client: TestClient) -> None:
    """base × Π(1 + facteurs) × (1 + autres) = prédiction du modèle, aux arrondis près."""
    data = client.get("/estimate", params={**POINT, **HOUSE}).json()["data"]
    expl = data["explication"]
    product = expl["base_prix_m2"] * (1 + expl["autres_pct"] / 100)
    for f in data["facteurs"]:
        product *= 1 + f["contribution_pct"] / 100
    # arrondis : base et prédiction à 10 €, chaque pourcentage à 0,1 point (7 termes)
    assert abs(product - expl["prix_m2_modele"]) <= 0.006 * expl["prix_m2_modele"] + 10
    assert expl["base_prix_m2"] % 10 == 0 and expl["prix_m2_modele"] % 10 == 0


def test_factors_rest_is_the_exact_complement(estimator: Estimator) -> None:
    q = EstimateQuery(**POINT, **HOUSE)  # type: ignore[arg-type]
    X = feature_row(q, CONTEXT, POINT["lon"], POINT["lat"], VALUATION, (8.0, 12))
    facteurs, expl = estimator.factors(X, q)
    predicted = float(np.exp(estimator.predict_log(X)))
    assert abs(expl.prix_m2_modele - predicted) <= 5
    assert len(facteurs) <= 6


def test_estimate_by_address_never_echoes_it(
    client: TestClient, geocoder: FakeGeocoder, caplog: pytest.LogCaptureFixture
) -> None:
    address = "12 rue Secrète 33000 Bordeaux"
    with caplog.at_level(logging.DEBUG):
        res = client.post("/estimate", json={"address": address, **HOUSE})
    assert res.status_code == 200, res.text
    assert geocoder.seen == [address]
    loc = res.json()["data"]["localisation"]
    assert loc["source"] == "adresse_ban" and loc["score_geocodage"] == 0.93
    assert "Secr" not in res.text
    assert all("Secr" not in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({**POINT, "address": "12 rue X 33000 Bordeaux", **HOUSE}, 422),
        ({"address": "12 rue X 33000 Bordeaux", **HOUSE}, 422),  # adresse jamais en GET
        ({"lat": 44.8, **HOUSE}, 422),
        ({**HOUSE}, 422),
        ({**POINT, **HOUSE, "surface": 5}, 422),
        ({**POINT, **HOUSE, "surface_terrain": 20000}, 422),
        ({**POINT, **HOUSE, "dpe": "H"}, 422),
        ({**POINT, **HOUSE, "type_local": "Château"}, 422),
        ({"lat": 95, "lon": 0, **HOUSE}, 422),
    ],
)
def test_estimate_validation(client: TestClient, params: dict, status: int) -> None:  # type: ignore[type-arg]
    res = client.get("/estimate", params=params)
    assert res.status_code == status
    assert res.json()["success"] is False
    assert "rue X" not in res.text


@pytest.mark.parametrize(
    "body",
    [
        {**POINT, "address": "12 rue X 33000 Bordeaux", **HOUSE},
        {"lat": 44.8, **HOUSE},
        {**HOUSE},
        {"address": "rue", **HOUSE},
        {"address": "12 rue X 33000 Bordeaux", **HOUSE, "surface": 5},
        {"address": "12 rue X 33000 Bordeaux", **HOUSE, "inconnu": 1},
    ],
)
def test_estimate_post_validation(client: TestClient, body: dict) -> None:  # type: ignore[type-arg]
    res = client.post("/estimate", json=body)
    assert res.status_code == 422
    assert res.json()["success"] is False
    assert "rue X" not in res.text


def test_estimate_post_by_coordinates_matches_get(client: TestClient) -> None:
    got = client.get("/estimate", params={**POINT, **HOUSE}).json()["data"]
    posted = client.post("/estimate", json={**POINT, **HOUSE}).json()["data"]
    assert posted["prix_m2"] == got["prix_m2"]
    assert posted["localisation"]["source"] == "coordonnees"


def test_estimate_outside_perimeter_is_404(client: TestClient, repo: FakeRepository) -> None:
    repo.context = None
    res = client.get("/estimate", params={**POINT, **HOUSE})
    assert res.status_code == 404


@pytest.mark.parametrize(("outcome", "status"), [("notfound", 404), ("down", 503)])
def test_estimate_geocoder_failures(settings: Settings, estimator: Estimator,
                                    outcome: str, status: int) -> None:
    with make_client(settings, repository=FakeRepository(), estimator=estimator,
                     geocoder=FakeGeocoder(outcome)) as c:
        res = c.post("/estimate", json={"address": "1 rue Inconnue 33000", **HOUSE})
    assert res.status_code == status
    assert res.json()["success"] is False


def test_estimate_without_model_is_503(settings: Settings) -> None:
    with make_client(settings, repository=FakeRepository(), geocoder=FakeGeocoder(),
                     load_model=False) as c:
        res = c.get("/estimate", params={**POINT, **HOUSE})
    assert res.status_code == 503
    assert res.json()["error"] == "Modèle de prix indisponible"


def test_estimate_without_sales_is_503(settings: Settings, estimator: Estimator) -> None:
    with make_client(settings, repository=FakeRepository(valuation=None), estimator=estimator,
                     geocoder=FakeGeocoder()) as c:
        res = c.get("/estimate", params={**POINT, **HOUSE})
    assert res.status_code == 503


def test_estimate_apartment_ignores_land(client: TestClient) -> None:
    res = client.get("/estimate", params={**POINT, "type_local": "Appartement", "surface": 50,
                                          "pieces": 2, "surface_terrain": 300})
    assert res.status_code == 200


def test_model_loaded_at_startup_from_settings(settings: Settings, ml_dir: Path) -> None:
    cfg = settings.model_copy(update={"atlas_ml_dir": ml_dir})
    with make_client(cfg, repository=FakeRepository(), geocoder=FakeGeocoder()) as c:
        assert c.get("/health").json()["data"]["model"] == "ok"


# --- estimateur (unitaire) --------------------------------------------------------


def test_load_bundle_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ModelUnavailableError):
        load_bundle(tmp_path)


def test_t_mois_matches_training_epoch() -> None:
    assert t_mois(dt.date(2021, 1, 15)) == 0
    assert t_mois(dt.date(2025, 1, 1)) == 48


def test_neighbour_features_use_only_reference_sales() -> None:
    day = dt.date(2025, 1, 1)
    cell = h3.latlng_to_cell(44.8378, -0.5792, 7)
    far_cell = h3.latlng_to_cell(43.3, 5.4, 7)  # Marseille : hors de l'anneau
    sales = [ReferenceSale(day - dt.timedelta(days=i + 1), cell, 4000.0) for i in range(10)]
    value, n = neighbour_features(sales, cell, "Maison", day)
    assert n == 10
    assert value == pytest.approx(np.log(4000.0))
    # aucun voisin : a priori seul ; aucune vente du tout : NaN, jamais une valeur inventée
    far = [ReferenceSale(s.date_mutation, far_cell, 3000.0) for s in sales]
    value_far, n_far = neighbour_features(far, cell, "Maison", day)
    assert n_far == 0 and value_far == pytest.approx(np.log(3000.0))
    value_none, n_none = neighbour_features([], cell, "Maison", day)
    assert n_none == 0 and np.isnan(value_none)


def test_feature_row_apartment_has_no_land() -> None:
    q = EstimateQuery(lat=44.8, lon=-0.5, type_local="Appartement", surface=50, pieces=2,
                      surface_terrain=100)
    X = feature_row(q, CONTEXT, -0.5, 44.8, dt.date(2025, 1, 1), (8.0, 12))
    assert np.isnan(X["log_terrain"].iloc[0])
    assert X["in_tri"].iloc[0] == 1.0 and X["ppri"].iloc[0] == 0.0
    unknown = replace(CONTEXT, in_tri=None, revenu_median=None)
    X2 = feature_row(q, unknown, -0.5, 44.8, dt.date(2025, 1, 1), (8.0, 12))
    assert np.isnan(X2["in_tri"].iloc[0]) and np.isnan(X2["revenu_median"].iloc[0])


# --- ADR 0005 : aucune vente isolée lisible à travers /estimate ----------------------

FAR_CELL = h3.latlng_to_cell(43.3, 5.4, 7)  # hors de l'anneau : sert d'a priori
RING_CELL = h3.latlng_to_cell(POINT["lat"], POINT["lon"], 7)
PRIOR = [ReferenceSale(dt.date(2024, 1, 1), FAR_CELL, 3000.0)] * 500


def _probe(estimator: Estimator, ring: list[ReferenceSale]) -> dict:  # type: ignore[type-arg]
    q = EstimateQuery(**POINT, **HOUSE)  # type: ignore[arg-type]
    out = estimator.estimate(q, CONTEXT, POINT["lon"], POINT["lat"], VALUATION,
                             [*PRIOR, *ring], LOC)
    return out.model_dump(mode="json")


@pytest.mark.parametrize("n_ring", [1, 4])
def test_single_sale_price_cannot_be_read_below_five(estimator: Estimator, n_ring: int) -> None:
    """Régression de la sonde : < 5 ventes d'anneau → sortie invariante au prix d'une vente."""
    def ring(price: float) -> list[ReferenceSale]:
        base = [ReferenceSale(dt.date(2024, 6, d), RING_CELL, 2500.0) for d in range(1, n_ring)]
        return [*base, ReferenceSale(dt.date(2024, 7, 1), RING_CELL, price)]

    baseline = _probe(estimator, [])
    for price in (1500.0, 2800.0, 3000.0, 4000.0, 6000.0):
        assert _probe(estimator, ring(price)) == baseline, price


def test_five_ring_sales_are_used(estimator: Estimator) -> None:
    def ring(price: float) -> list[ReferenceSale]:
        return [ReferenceSale(dt.date(2024, 6, d), RING_CELL, price) for d in range(1, 6)]

    assert _probe(estimator, ring(1500.0))["prix_m2"] != _probe(estimator, ring(9000.0))["prix_m2"]


def test_warnings_do_not_depend_on_neighbour_count(estimator: Estimator) -> None:
    """Aucun avertissement conditionnel : il servirait d'oracle sur le nombre de ventes."""
    ring = [ReferenceSale(dt.date(2024, 6, d), RING_CELL, 2500.0) for d in range(1, 11)]
    counts = {tuple(_probe(estimator, ring[:n])["avertissements"]) for n in (0, 4, 5, 10)}
    assert len(counts) == 1
    assert not any("Moins de 5 ventes" in w for w in counts.pop())


def test_neighbour_features_ignore_fewer_than_five_ring_sales() -> None:
    day = dt.date(2025, 1, 1)
    four = [ReferenceSale(day - dt.timedelta(days=i + 1), RING_CELL, 9000.0) for i in range(4)]
    value, n = neighbour_features([*PRIOR, *four], RING_CELL, "Maison", day)
    assert n == 0 and value == pytest.approx(np.log(3000.0))
