"""Chaîne complète sur données synthétiques : chargement, modèles, effets, MLflow, rapport."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from ml_synth import make_sales, write_lake

from atlas_pipelines.ml import rerender, train
from atlas_pipelines.ml.data import load_dataset
from atlas_pipelines.ml.effects import dpe_shares, estimate_dpe_effects, estimate_risk_effects
from atlas_pipelines.ml.experiment import with_neighbours
from atlas_pipelines.ml.explain import archetype, global_importance, local_explanation
from atlas_pipelines.ml.features import add_model_features
from atlas_pipelines.ml.models import LgbModel, RidgeModel, tune_lgb


@pytest.fixture
def lake(tmp_path: Path) -> tuple[Path, Path]:
    return write_lake(tmp_path / "data")


def test_load_dataset_point_in_time_catnat(lake: tuple[Path, Path]) -> None:
    gold, silver = lake
    path = silver / "georisques" / "catnat.parquet"
    cat = pd.read_parquet(path)
    extra = pd.DataFrame(
        {
            "code_insee": ["33000", "33000"],
            "code_national_catnat": ["FUTUR", "ANCIEN"],
            "date_debut_evt": [
                pd.Timestamp("2023-01-01").date(),
                pd.Timestamp("2005-01-01").date(),
            ],
            "date_arrete": [pd.Timestamp("2023-06-01").date(), pd.Timestamp("2005-06-01").date()],
        }
    )
    pd.concat([cat, extra]).to_parquet(path)
    df = load_dataset(gold, silver)
    assert "id_mutation" not in df.columns and "id_parcelle" not in df.columns
    assert len(df) == 1500
    # commune 33000 : arrêtés 2015 et 2021 (+ 2005, hors fenêtre de 10 ans) ; celui
    # publié en juin 2023 n'est compté que pour les ventes postérieures
    c0 = df.loc[df["code_commune"] == "33000"]
    dates = pd.to_datetime(c0["date_mutation"])
    assert set(c0.loc[dates < "2023-06-01", "n_catnat_10ans"]) == {2}
    assert set(c0.loc[dates > "2023-06-01", "n_catnat_10ans"]) == {3}
    assert df["urbain"].dtype == bool


def test_load_dataset_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path, tmp_path)


def test_load_dataset_excludes_large_plots(tmp_path: Path) -> None:
    gold, silver = write_lake(tmp_path / "d")
    fact = pd.read_parquet(gold / "fact_transactions.parquet")
    fact.loc[fact["type_local"] == "Maison", "surface_terrain"] = 20000.0
    fact.to_parquet(gold / "fact_transactions.parquet")
    df = load_dataset(gold, silver)
    assert (df["type_local"] == "Maison").sum() == 0
    # communes paires : IRIS de type Z (commune sans IRIS, « rurale »)
    houses = fact.loc[fact["type_local"] == "Maison"]
    rural = houses["code_commune"].str[-3:].astype(int) % 2 == 0
    assert df.attrs["n_exclues_terrain"] == len(houses)
    assert df.attrs["n_exclues_terrain_sans_iris"] == int(rural.sum())


def test_models_fit_and_predict() -> None:
    df = add_model_features(make_sales(600))
    df = df.assign(
        revenu_median=np.nan, gini=0.3, rga_code=2.0, in_tri=0.0, ppri=1.0, n_catnat_10ans=0
    )
    feat = with_neighbours(df, np.ones(len(df), bool))
    y = feat["log_prix_m2"].to_numpy()
    for model in (RidgeModel(), LgbModel("global"), LgbModel("par_type")):
        pred = model.fit(feat, y).predict(feat)
        assert pred.shape == y.shape and np.isfinite(pred).all()
    with pytest.raises(RuntimeError):
        LgbModel().predict(feat)
    only_houses = LgbModel("par_type").fit(
        feat[feat["type_local"] == "Maison"], y[(feat["type_local"] == "Maison").to_numpy()]
    )
    with pytest.raises(ValueError):
        only_houses.predict(feat)
    params, mae = tune_lgb(feat, y, feat["code_commune"].to_numpy(), "global", n_trials=2)
    assert mae > 0 and "num_leaves" in params


def test_effects_recover_planted_dpe_effect() -> None:
    df = add_model_features(make_sales(3000, seed=3))
    g = (df["dpe_etiquette"] == "G").to_numpy()
    df.loc[g, "log_prix_m2"] -= 0.3
    df = df.assign(
        revenu_median=np.nan, gini=0.3, rga_code=2.0, in_tri=0.0, ppri=0.0, n_catnat_10ans=0
    )
    feat = with_neighbours(df, np.ones(len(df), bool))
    effects = {e.term: e for e in estimate_dpe_effects(feat, n_boot=50)}
    g_eff = effects["dpe_G"]
    # effet planté −0,30 (log) ; tolérance pour le bruit et le lissage du voisinage
    assert -0.4 < g_eff.low <= g_eff.coef <= g_eff.high < -0.2
    assert abs(effects["dpe_A"].coef) < 0.1  # aucun effet planté sur A
    lo, mid, hi = effects["dpe_G"].factor
    assert lo < mid < hi < 1
    risks = estimate_risk_effects(feat, n_boot=20)
    assert risks == []  # aucune variation de risque : rien d'estimable


def test_risk_bounds_with_and_without_neighbourhood_control() -> None:
    """Risque communal planté (−0,20) : le voisinage l'absorbe, son absence le restitue."""
    df = add_model_features(make_sales(3000, seed=4))
    commune = df["code_commune"].str[-3:].astype(int)
    ppri = (commune % 3 == 0).to_numpy(dtype=float)
    df["log_prix_m2"] = df["log_prix_m2"] - 0.20 * ppri
    df = df.assign(
        revenu_median=np.nan, gini=0.3, rga_code=2.0, in_tri=0.0, ppri=ppri, n_catnat_10ans=0
    )
    feat = with_neighbours(df, np.ones(len(df), bool))
    avec = {e.term: e for e in estimate_risk_effects(feat, n_boot=30)}["ppri"]
    sans = {e.term: e for e in estimate_risk_effects(feat, n_boot=30, neighbourhood_control=False)}[
        "ppri"
    ]
    assert abs(avec.coef) < abs(sans.coef)
    assert sans.low <= sans.coef <= sans.high
    assert avec.n_obs == sans.n_obs  # même échantillon pour les deux bornes
    shares = dpe_shares(feat)
    assert set(shares) == set("ABCDEFG") and sum(shares.values()) == pytest.approx(1.0)


def test_end_to_end_run(lake: tuple[Path, Path], tmp_path: Path) -> None:
    gold, silver = lake
    out = tmp_path / "ml"
    code = train.main(
        [
            "--gold",
            str(gold),
            "--silver",
            str(silver),
            "--out",
            str(out),
            "--trials",
            "2",
            "--cv-trials",
            "1",
            "--folds",
            "3",
            "--boot",
            "50",
            "--effect-boot",
            "20",
            "--tracking-uri",
            (tmp_path / "mlruns").as_uri(),
        ]
    )
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert code == (0 if res["porte"]["passe"] else 2)
    assert res["meta"]["strategie"] in {"global", "par_type"}
    for proto in ("spatial", "temporel"):
        assert res[proto]["lgb"]["tous"]["mae"] > 0
        assert set(res[proto]["lgb"]["par_type"]) == {"Appartement", "Maison"}
    assert res["temporel"]["n_test"] == res["temporel"]["lgb"]["tous"]["n"]
    assert len(res["temporel"]["residus_quantiles"]) == 201
    assert set(res["temporel"]["residus_quantiles_par_type"]) == {"Appartement", "Maison"}
    bien = res["temporel"]["bien_exemple"]
    assert bien["type_local"] == "Maison" and "ppri" not in bien["risques_actuels"]
    assert {"risques_avec_voisinage", "risques_sans_voisinage", "parts_dpe"} <= set(res["effets"])
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Porte bloquante" in report and "fictive" in report
    assert "refus explicite" in report  # RCP 8.5 sans DRIAS
    cases = {c["cas"]: c for c in res["projection_exemples"]}
    assert "erreur" in cases["G, statu quo, RCP 8.5"]
    p10, p50, p90 = cases["G, statu quo, 2050"]["prix_m2_p10_p50_p90"]
    assert p10 < p50 < p90
    assert len(list((out / "figures").glob("*.png"))) >= 8
    assert any((tmp_path / "mlruns").rglob("results.json"))

    # re-rendu sans réentraînement : modèle rechargé, mêmes résidus, rapport réécrit
    (out / "report.md").unlink()
    args = ["--gold", str(gold), "--silver", str(silver), "--out", str(out)]
    assert rerender.main([*args, "--effect-boot", "20"]) == 0
    again = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert again["temporel"]["residus_quantiles"] == res["temporel"]["residus_quantiles"]
    assert again["temporel"]["lgb"] == res["temporel"]["lgb"]
    assert again["meta"]["rerendu"]["reentrainement"] is False
    assert "non causal" in (out / "report.md").read_text(encoding="utf-8")
    # un results.json qui ne correspond plus au modèle sauvegardé est refusé
    again["temporel"]["residus_quantiles"][100] += 0.5
    (out / "results.json").write_text(json.dumps(again), encoding="utf-8")
    with pytest.raises(ValueError, match="ne correspond pas"):
        rerender.main(args)


def test_shap_per_type_model_and_fictitious_archetype() -> None:
    df = add_model_features(make_sales(800, seed=5))
    df = df.assign(
        revenu_median=np.nan, gini=0.3, rga_code=2.0, in_tri=0.0, ppri=0.0, n_catnat_10ans=0
    )
    feat = with_neighbours(df, np.ones(len(df), bool))
    model = LgbModel("par_type").fit(feat, feat["log_prix_m2"].to_numpy())
    imp = global_importance(model, feat, n=300)
    assert imp.index[0] in imp.index and (imp >= 0).all()
    row = archetype(feat, "Maison")
    assert len(row) == 1  # un seul bien, fictif (médianes)
    contrib, base = local_explanation(model, row)
    pred = model.predict(row)[0]
    assert base + contrib.sum() == pytest.approx(pred, abs=1e-6)
    with pytest.raises(ValueError, match="bien type"):
        archetype(feat.head(10), "Maison")
