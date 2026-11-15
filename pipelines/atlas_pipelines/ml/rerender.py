"""Re-rendu SANS réentraînement : effets, erreurs par type, exemples et rapport.

    python -m atlas_pipelines.ml.rerender --out ../ml [--effect-boot 300]

Part de `results.json` et des modèles sauvegardés (`models/lgb_*.txt`) d'un run de
`train`. Reconstruit exactement le jeu de test 2024 (variables de voisinage calculées
sur les seules ventes ≤ 2023, comme à l'entraînement), le prédit avec le modèle
rechargé et VÉRIFIE que les quantiles de résidus obtenus sont ceux du run : sinon le
modèle et results.json ne vont pas ensemble et le programme s'arrête. Recalcule ensuite
les effets prix, les résidus par type, la maison d'exemple, les projections, la figure
des effets et `report.md`. Les scores, SHAP et la porte bloquante ne changent pas.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from atlas_pipelines.ml.data import load_dataset
from atlas_pipelines.ml.examples import (
    example_house,
    example_projections,
    residual_quantiles_by_type,
)
from atlas_pipelines.ml.experiment import with_neighbours
from atlas_pipelines.ml.features import add_model_features
from atlas_pipelines.ml.models import TYPES, lgb_matrix
from atlas_pipelines.ml.report import render
from atlas_pipelines.ml.train import TEST_YEAR, effects_figure, run_effects

logger = logging.getLogger(__name__)
TOLERANCE = 1e-9


class SavedModel:
    """Boosters LightGBM rechargés ; même logique de prédiction que `LgbModel`."""

    def __init__(self, models_dir: Path, strategy: str) -> None:
        names = {"global": ["global"], "par_type": list(TYPES)}.get(strategy)
        if names is None:
            raise ValueError(f"Stratégie inconnue dans results.json : {strategy!r}")
        self.strategy = strategy
        self.boosters: dict[str, lgb.Booster] = {}
        for name in names:
            path = models_dir / f"lgb_{name}.txt"
            if not path.is_file():
                raise FileNotFoundError(f"Modèle sauvegardé absent : {path}")
            self.boosters[name] = lgb.Booster(model_file=str(path))

    def predict(self, X: pd.DataFrame) -> np.ndarray[Any, Any]:
        if self.strategy == "global":
            return np.asarray(self.boosters["global"].predict(lgb_matrix(X, True)), dtype=float)
        out = np.full(len(X), np.nan)
        for typ, booster in self.boosters.items():
            m = (X["type_local"] == typ).to_numpy()
            if m.any():
                out[m] = booster.predict(lgb_matrix(X[m], False))
        return out


def _check_same_model(resid: np.ndarray[Any, Any], stored: list[float]) -> None:
    q = np.quantile(resid, np.linspace(0, 1, len(stored)))
    gap = float(np.max(np.abs(q - np.asarray(stored, dtype=float))))
    if not gap <= TOLERANCE:
        raise ValueError(
            f"Le modèle rechargé ne correspond pas à results.json (écart de quantile {gap:.3g}) "
            ": réentraîner avec atlas_pipelines.ml.train"
        )


def rerender(gold: Path, silver: Path, out: Path, effect_boot: int, seed: int) -> dict[str, Any]:
    path = out / "results.json"
    res: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    raw = load_dataset(gold, silver)
    df = add_model_features(raw)
    if len(df) != res["meta"]["n_ventes"]:
        raise ValueError(
            f"Le gold a changé : {len(df)} ventes au lieu de {res['meta']['n_ventes']}"
        )
    train = (df["annee"] <= TEST_YEAR - 1).to_numpy()
    test = (df["annee"] == TEST_YEAR).to_numpy()
    X_te = with_neighbours(df, reference=train).loc[test]
    model = SavedModel(out / "models", res["meta"]["strategie"])
    resid = X_te["log_prix_m2"].to_numpy(dtype=float) - model.predict(X_te)
    _check_same_model(resid, res["temporel"]["residus_quantiles"])

    te = res["temporel"]
    te["residus_quantiles_par_type"] = residual_quantiles_by_type(X_te["type_local"], resid)
    te["bien_exemple"] = example_house(X_te, model.predict)
    res["meta"]["n_exclues_terrain_sans_iris"] = raw.attrs.get("n_exclues_terrain_sans_iris", 0)
    res["meta"]["rerendu"] = {
        "date": dt.date.today().isoformat(),
        "reentrainement": False,
        "recalcule": "effets prix, résidus par type, bien d'exemple, projections, rapport",
    }
    res["effets"] = run_effects(df, effect_boot, seed)
    res["projection_exemples"] = example_projections(res)
    effects_figure(res, out / "figures")
    path.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    (out / "report.md").write_text(render(res), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Re-rendu du rapport sans réentraînement")
    data = Path(os.environ.get("ATLAS_DATA_DIR", "../data"))
    p.add_argument("--gold", type=Path, default=data / "gold")
    p.add_argument("--silver", type=Path, default=data / "silver")
    p.add_argument("--out", type=Path, default=Path("../ml"))
    p.add_argument("--effect-boot", type=int, default=300)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    rerender(a.gold, a.silver, a.out, a.effect_boot, a.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
