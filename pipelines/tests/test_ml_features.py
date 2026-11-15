"""Feature de voisinage H3 : aucune fuite temporelle ni de pli."""

from __future__ import annotations

import datetime as dt

import h3
import numpy as np
import pandas as pd
import pytest

from atlas_pipelines.ml.features import (
    NEIGHBOUR_COLUMNS,
    add_model_features,
    neighbourhood_log_price,
)

LAT, LON = 44.8378, -0.5792  # Bordeaux
CELL = h3.latlng_to_cell(LAT, LON, 7)
FAR = h3.latlng_to_cell(45.5, 0.5, 7)  # hors de l'anneau


def _frame(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date_mutation": pd.to_datetime([r[0] for r in rows]),
            "h3_r7": [r[1] for r in rows],
            "type_local": [r[2] for r in rows],
            "log_prix_m2": [r[3] for r in rows],
        }
    )


def test_only_strictly_earlier_sales_are_used() -> None:
    df = _frame(
        [
            ("2022-01-01", CELL, "Maison", np.log(1000)),
            ("2022-06-01", CELL, "Maison", np.log(9000)),  # même jour que la cible
            ("2022-06-01", CELL, "Maison", np.log(2000)),  # cible
            ("2023-01-01", CELL, "Maison", np.log(50000)),  # postérieure
        ]
    )
    out = neighbourhood_log_price(df, prior_weight=0.0)
    # la cible (ligne 2) ne voit que la vente du 2022-01-01
    assert out.loc[2, "voisinage_n"] == 1
    assert out.loc[2, "voisinage_log_prix"] == pytest.approx(np.log(1000))
    # la première vente n'a aucun passé
    assert out.loc[0, "voisinage_n"] == 0
    assert np.isnan(out.loc[0, "voisinage_log_prix"])


def test_target_price_never_influences_its_own_feature() -> None:
    base = [
        ("2022-01-01", CELL, "Maison", np.log(1000)),
        ("2022-02-01", CELL, "Maison", np.log(1200)),
        ("2022-03-01", CELL, "Maison", np.log(1500)),
    ]
    a = neighbourhood_log_price(_frame(base))
    shifted = [*base[:2], ("2022-03-01", CELL, "Maison", np.log(99999))]
    b = neighbourhood_log_price(_frame(shifted))
    assert a.loc[2, "voisinage_log_prix"] == b.loc[2, "voisinage_log_prix"]


def test_reference_mask_excludes_other_fold() -> None:
    df = _frame(
        [
            ("2022-01-01", CELL, "Maison", np.log(1000)),  # pli de test
            ("2022-02-01", CELL, "Maison", np.log(3000)),  # pli d'entraînement
            ("2022-03-01", CELL, "Maison", np.log(2000)),  # cible
        ]
    )
    reference = np.array([False, True, False])
    out = neighbourhood_log_price(df, reference=reference, prior_weight=0.0)
    assert out.loc[2, "voisinage_n"] == 1
    assert out.loc[2, "voisinage_log_prix"] == pytest.approx(np.log(3000))


def test_ring_type_and_k_limits() -> None:
    neighbour = sorted(set(h3.grid_disk(CELL, 1)) - {CELL})[0]
    rows = [(f"2022-01-{d:02d}", neighbour, "Maison", np.log(1000 + d)) for d in range(1, 11)]
    rows += [
        ("2022-01-15", FAR, "Maison", np.log(99999)),
        ("2022-01-16", CELL, "Appartement", np.log(99999)),
        ("2022-02-01", CELL, "Maison", np.log(2000)),
    ]
    out = neighbourhood_log_price(_frame(rows), k=3, prior_weight=0.0)
    target = len(rows) - 1
    assert out.loc[target, "voisinage_n"] == 3  # 3 plus récentes de l'anneau, même type
    assert out.loc[target, "voisinage_log_prix"] == pytest.approx(np.log(1009))


def test_smoothing_pulls_small_samples_to_prior() -> None:
    rows = [(f"2022-01-{d:02d}", FAR, "Maison", np.log(1000)) for d in range(1, 21)]
    rows += [("2022-01-25", CELL, "Maison", np.log(4000)), ("2022-02-01", CELL, "Maison", 0.0)]
    out = neighbourhood_log_price(_frame(rows), prior_weight=1.0)
    value = out.loc[len(rows) - 1, "voisinage_log_prix"]
    # 1 voisin à log(4000), a priori départemental ≈ log(1000) (21 ventes antérieures),
    # poids égal : moyenne des deux
    prior = np.median([np.log(1000)] * 20 + [np.log(4000)])
    assert value == pytest.approx((np.log(4000) + prior) / 2)


def test_rejects_bad_inputs() -> None:
    df = _frame([("2022-01-01", CELL, "Maison", 7.0)])
    with pytest.raises(ValueError, match="k"):
        neighbourhood_log_price(df, k=0)
    with pytest.raises(ValueError, match="reference"):
        neighbourhood_log_price(df, reference=np.array([True, False]))
    with pytest.raises(KeyError):
        neighbourhood_log_price(df.drop(columns="h3_r7"))


def test_add_model_features_builds_expected_columns() -> None:
    df = pd.DataFrame(
        {
            "date_mutation": [dt.date(2022, 3, 1), dt.date(2024, 1, 31)],
            "surface_bati": [80, 40],
            "surface_terrain": [500.0, None],
            "prix_m2": [3000.0, 4000.0],
            "in_tri": [True, False],
            "ppri": [None, True],
        }
    )
    out = add_model_features(df)
    assert out["log_surface"].tolist() == pytest.approx([np.log(80), np.log(40)])
    assert out["log_terrain"].iloc[0] == pytest.approx(np.log1p(500))
    assert np.isnan(out["log_terrain"].iloc[1])
    assert out["t_mois"].tolist() == [14, 36]
    assert out["log_prix_m2"].iloc[1] == pytest.approx(np.log(4000))
    assert out["in_tri"].tolist() == [1.0, 0.0]
    assert np.isnan(out["ppri"].iloc[0])
    assert "log_prix_m2" not in df.columns  # pas de mutation de l'entrée
    assert set(NEIGHBOUR_COLUMNS) == {"voisinage_log_prix", "voisinage_n"}
