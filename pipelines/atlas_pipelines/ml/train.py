"""Entraînement, validation, SHAP, effets prix, MLflow et rapport.

    python -m atlas_pipelines.ml.train --out ../ml [--trials 30 --cv-trials 12]

Porte bloquante : LightGBM doit battre Ridge avec une différence de MAE dont l'IC 95 %
bootstrap (par commune) est entièrement négatif, en validation spatiale ET temporelle.
Sinon le programme sort avec le code 2 (le rapport est écrit quand même).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd

from atlas_pipelines.ml import figures
from atlas_pipelines.ml.data import load_dataset
from atlas_pipelines.ml.effects import dpe_shares, estimate_dpe_effects, estimate_risk_effects
from atlas_pipelines.ml.examples import (
    example_house,
    example_projections,
    residual_quantiles_by_type,
)
from atlas_pipelines.ml.experiment import (
    choose_strategy,
    fit_predict,
    make_tuner,
    scores_by,
    spatial_cv,
    with_neighbours,
)
from atlas_pipelines.ml.explain import archetype, global_importance, local_explanation
from atlas_pipelines.ml.features import add_model_features
from atlas_pipelines.ml.metrics import cluster_bootstrap_mae_diff
from atlas_pipelines.ml.models import Strategy
from atlas_pipelines.ml.report import render
from atlas_pipelines.ml.tracking import flatten, resolve_tracking_uri, sanitize

logger = logging.getLogger(__name__)
TEST_YEAR = 2024


@dataclass(frozen=True)
class RunConfig:
    gold_dir: Path
    silver_dir: Path
    out_dir: Path
    trials: int = 30
    cv_trials: int = 12
    folds: int = 5
    n_boot: int = 2000
    effect_boot: int = 300
    tracking_uri: str | None = None
    seed: int = 0


def _evaluate(
    df: pd.DataFrame, y: np.ndarray[Any, Any], pr: Any, pl: Any, boot: int
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, pred in (("ridge", pr), ("lgb", pl)):
        out[name] = {
            **scores_by(df, y, pred, None),
            "par_type": scores_by(df, y, pred, "type_local"),
            "par_urbain": scores_by(df, y, pred, "zone"),
        }
    out["diff"] = cluster_bootstrap_mae_diff(
        y, pl, pr, df["code_commune"].to_numpy(), n_boot=boot
    ).as_dict()
    return out


def run_temporal(df: pd.DataFrame, cfg: RunConfig, strategy: Strategy) -> dict[str, Any]:
    train = (df["annee"] <= TEST_YEAR - 1).to_numpy()
    test = (df["annee"] == TEST_YEAR).to_numpy()
    tuner = make_tuner(strategy, cfg.trials, cfg.seed)
    res, model, X_te = fit_predict(df, train, test, strategy, tuner)
    y = df.loc[test, "prix_m2"].to_numpy(float)
    ev = _evaluate(df.loc[test], y, res.pred_ridge, res.pred_lgb, cfg.n_boot)
    resid = np.log(y) - np.log(res.pred_lgb)
    imp = global_importance(model, X_te, seed=cfg.seed)
    local = {}
    for typ in ("Maison", "Appartement"):
        row = archetype(X_te, typ)
        contrib, base = local_explanation(model, row)
        local[typ] = {
            "bien": {k: (None if pd.isna(v) else v) for k, v in row.iloc[0].to_dict().items()},
            "base_m2": float(np.exp(base)),
            "prediction_m2": float(np.exp(base + contrib.sum())),
            "contributions": contrib.sort_values(key=np.abs, ascending=False).to_dict(),
        }
    ev.update(
        n_train=int(train.sum()),
        n_test=int(test.sum()),
        params=res.params,
        residus_quantiles=np.quantile(resid, np.linspace(0, 1, 201)).tolist(),
        residus_quantiles_par_type=residual_quantiles_by_type(X_te["type_local"], resid),
        bien_exemple=example_house(X_te, model.predict),
        shap_global=imp.to_dict(),
        shap_local=local,
        calibration={"pred": res.pred_lgb, "obs": y},
    )
    for name, booster in model.models.items():
        path = cfg.out_dir / "models" / f"lgb_{name.replace('*', 'global')}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        booster.booster_.save_model(str(path))
    return ev


def run_spatial(df: pd.DataFrame, cfg: RunConfig, strategy: Strategy) -> dict[str, Any]:
    oof = spatial_cv(df, strategy, make_tuner(strategy, cfg.cv_trials, cfg.seed), cfg.folds)
    y = df["prix_m2"].to_numpy(float)
    ev: dict[str, Any] = _evaluate(
        df, y, oof["pred_ridge"].to_numpy(), oof["pred_lgb"].to_numpy(), cfg.n_boot
    )
    ev["n"] = len(df)
    ev["n_communes"] = int(df["code_commune"].nunique())
    return ev


def run_effects(df: pd.DataFrame, effect_boot: int, seed: int) -> dict[str, Any]:
    """Effets prix ; risques en deux bornes (avec / sans contrôle de voisinage)."""
    feat = with_neighbours(df, reference=np.ones(len(df), bool))

    def risks(control: bool) -> list[dict[str, Any]]:
        found = estimate_risk_effects(feat, effect_boot, seed, neighbourhood_control=control)
        return [e.as_dict() for e in found]

    return {
        "risques_avec_voisinage": risks(True),
        "risques_sans_voisinage": risks(False),
        "dpe": [e.as_dict() for e in estimate_dpe_effects(feat, effect_boot, seed)],
        "parts_dpe": dpe_shares(feat),
        "n_dpe_apparies": int(df["dpe_etiquette"].isin(list("ABCDEFG")).sum()),
        "n_dpe_apparies_maisons": int(
            (df["dpe_etiquette"].isin(list("ABCDEFG")) & (df["type_local"] == "Maison")).sum()
        ),
    }


def make_figures(res: dict[str, Any], fig_dir: Path) -> list[Path]:
    sp, te = res["spatial"], res["temporel"]
    paths = [
        figures.mae_bars(
            {
                "spatial (GroupKFold)": {
                    "ridge": sp["ridge"]["tous"]["mae"],
                    "lgb": sp["lgb"]["tous"]["mae"],
                },
                "temporel (test 2024)": {
                    "ridge": te["ridge"]["tous"]["mae"],
                    "lgb": te["lgb"]["tous"]["mae"],
                },
            },
            fig_dir / "mae_baseline_vs_lgb.png",
        ),
        figures.diff_ci(
            {"spatial": sp["diff"], "temporel": te["diff"]}, fig_dir / "mae_diff_bootstrap.png"
        ),
    ]
    for proto, ev in (("temporel", te), ("spatial", sp)):
        rows = {}
        for grp in ("par_type", "par_urbain"):
            for k in ev["lgb"][grp]:
                rows[k] = {
                    "ridge": 100 * ev["ridge"][grp][k]["mape"],
                    "lgb": 100 * ev["lgb"][grp][k]["mape"],
                }
        paths.append(
            figures.by_group(
                pd.DataFrame(rows).T,
                "MAPE (%)",
                fig_dir / f"mape_groupes_{proto}.png",
                f"MAPE par type et zone, {proto}",
            )
        )
    cal = te.pop("calibration")
    paths.append(
        figures.calibration(
            np.asarray(cal["pred"]), np.asarray(cal["obs"]), fig_dir / "calibration_test_2024.png"
        )
    )
    imp = pd.Series(te["shap_global"]).head(15)
    paths.append(
        figures.hbar(
            imp,
            fig_dir / "shap_global.png",
            "moyenne |SHAP| (log-prix)",
            "Importance SHAP globale, test 2024",
        )
    )
    for typ, loc in te["shap_local"].items():
        contrib = pd.Series(loc["contributions"]).head(10)
        paths.append(
            figures.hbar(
                100 * (np.exp(contrib) - 1),
                fig_dir / f"shap_local_{typ.lower()}_fictif.png",
                "effet sur le prix/m² (%)",
                f"{typ} fictive (médianes du test) : contributions SHAP",
                signed=True,
            )
        )
    paths.append(effects_figure(res, fig_dir))
    return paths


def effects_figure(res: dict[str, Any], fig_dir: Path) -> Path:
    ef = res["effets"]
    rows = [
        {**e, "term": f"{e['term']} ({label})"}
        for key, label in (
            ("risques_avec_voisinage", "avec voisinage"),
            ("risques_sans_voisinage", "sans voisinage"),
        )
        for e in ef[key]
    ]
    return figures.effects_plot(
        rows + ef["dpe"],
        fig_dir / "effets_risques_dpe.png",
        "Effets prix estimés (IC 95 % bootstrap par commune)",
    )


def _log_mlflow(res: dict[str, Any], cfg: RunConfig, paths: list[Path]) -> str:
    uri = resolve_tracking_uri(cfg.tracking_uri, cfg.out_dir.parent / "mlruns")
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("atlas-prix-m2")
    with mlflow.start_run(run_name=f"s3-{res['meta']['strategie']}") as run:
        mlflow.log_params(
            {
                sanitize(k): v
                for k, v in {
                    "strategie": res["meta"]["strategie"],
                    "trials": cfg.trials,
                    "cv_trials": cfg.cv_trials,
                    "folds": cfg.folds,
                    "n_boot": cfg.n_boot,
                    **{f"lgb.{k}": v for k, v in res["temporel"]["params"].items()},
                }.items()
            }
        )
        metrics = {}
        for proto in ("spatial", "temporel"):
            for model in ("ridge", "lgb"):
                metrics.update(flatten(f"{proto}.{model}", res[proto][model]))
            metrics.update(flatten(f"{proto}.diff", res[proto]["diff"]))
        mlflow.log_metrics({sanitize(k): v for k, v in metrics.items()})
        mlflow.set_tag("porte_passee", str(res["porte"]["passe"]))
        for p in paths:
            mlflow.log_artifact(str(p), "figures")
        mlflow.log_artifact(str(cfg.out_dir / "results.json"))
        mlflow.log_artifacts(str(cfg.out_dir / "models"), "models")
        where = "mlruns/ local" if uri.startswith("file:") else uri
        return f"{where}, expérience atlas-prix-m2, run {run.info.run_id}"


def run(cfg: RunConfig) -> dict[str, Any]:
    raw = load_dataset(cfg.gold_dir, cfg.silver_dir)
    df = add_model_features(raw)
    df["zone"] = np.where(df["urbain"], "commune à IRIS", "commune sans IRIS")
    choice = choose_strategy(df.loc[df["annee"] < TEST_YEAR].reset_index(drop=True))
    strategy: Strategy = "global" if choice["global"] <= choice["par_type"] else "par_type"
    logger.info("Stratégie : %s (%s)", strategy, choice)
    res: dict[str, Any] = {
        "meta": {
            "date": dt.date.today().isoformat(),
            "n_ventes": len(df),
            "n_exclues_terrain": raw.attrs.get("n_exclues_terrain", 0),
            "n_exclues_terrain_sans_iris": raw.attrs.get("n_exclues_terrain_sans_iris", 0),
            "annees": sorted(df["annee"].unique().tolist()),
            "n_communes": int(df["code_commune"].nunique()),
            "strategie": strategy,
            "choix_strategie_mae": choice,
            "trials": cfg.trials,
            "cv_trials": cfg.cv_trials,
            "folds": cfg.folds,
        }
    }
    res["temporel"] = run_temporal(df, cfg, strategy)
    res["spatial"] = run_spatial(df, cfg, strategy)
    res["effets"] = run_effects(df, cfg.effect_boot, cfg.seed)
    res["projection_exemples"] = example_projections(res)
    res["porte"] = {p: bool(res[p]["diff"]["significatif"]) for p in ("spatial", "temporel")}
    res["porte"]["passe"] = all(res["porte"].values())
    paths = make_figures(res, cfg.out_dir / "figures")
    (cfg.out_dir / "results.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8"
    )
    res["meta"]["mlflow"] = _log_mlflow(res, cfg, paths)
    (cfg.out_dir / "results.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8"
    )
    (cfg.out_dir / "report.md").write_text(render(res), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Modèle de prix ATLAS 2050 (sprint 3)")
    data = Path(os.environ.get("ATLAS_DATA_DIR", "../data"))
    p.add_argument("--gold", type=Path, default=data / "gold")
    p.add_argument("--silver", type=Path, default=data / "silver")
    p.add_argument("--out", type=Path, default=Path("../ml"))
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--cv-trials", type=int, default=12)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--boot", type=int, default=2000)
    p.add_argument("--effect-boot", type=int, default=300)
    p.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = RunConfig(
        a.gold,
        a.silver,
        a.out,
        a.trials,
        a.cv_trials,
        a.folds,
        a.boot,
        a.effect_boot,
        a.tracking_uri,
    )
    res = run(cfg)
    if not res["porte"]["passe"]:
        logger.error(
            "PORTE BLOQUANTE : LightGBM ne bat pas Ridge significativement %s", res["porte"]
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
