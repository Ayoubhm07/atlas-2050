"""Baseline Ridge et LightGBM (+ Optuna) sur log(prix/m²).

Les deux modèles reçoivent exactement les mêmes variables. Les manquants (revenu IRIS,
terrain des appartements, RGA inconnu) : Ridge les impute par la médiane du pli
d'entraînement et ajoute un indicateur de manquant ; LightGBM les traite nativement.
DPE : pas de variable directe (7,5 % des ventes appariées, 5 905 / 78 358, presque
toutes des maisons, docs/analysis/eda.ipynb §6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

logger = logging.getLogger(__name__)

NUMERIC: tuple[str, ...] = (
    "log_surface",
    "pieces",
    "log_terrain",
    "n_dependances",
    "revenu_median",
    "gini",
    "rga_code",
    "in_tri",
    "ppri",
    "n_catnat_10ans",
    "voisinage_log_prix",
    "voisinage_n",
    "lon",
    "lat",
    "t_mois",
)
TYPES: tuple[str, ...] = ("Appartement", "Maison")
Strategy = Literal["global", "par_type"]
FloatArray = np.ndarray[Any, np.dtype[np.float64]]


class LogPriceModel(Protocol):
    def fit(self, X: pd.DataFrame, y: FloatArray) -> LogPriceModel: ...
    def predict(self, X: pd.DataFrame) -> FloatArray: ...


def make_ridge() -> Pipeline:
    numeric = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        StandardScaler(),
    )
    pre = ColumnTransformer(
        [
            ("num", numeric, list(NUMERIC)),
            ("type", OneHotEncoder(categories=[list(TYPES)], drop="first"), ["type_local"]),
        ]
    )
    return Pipeline([("pre", pre), ("ridge", RidgeCV(alphas=np.logspace(-3, 3, 13)))])


class RidgeModel:
    def __init__(self) -> None:
        self.pipe = make_ridge()

    def fit(self, X: pd.DataFrame, y: FloatArray) -> RidgeModel:
        self.pipe.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> FloatArray:
        return np.asarray(self.pipe.predict(X), dtype=float)


def lgb_matrix(X: pd.DataFrame, with_type: bool) -> pd.DataFrame:
    cols = list(NUMERIC)
    out = X[cols].astype(float)
    if with_type:
        out = out.assign(est_maison=(X["type_local"] == "Maison").astype(float))
    return out


DEFAULT_LGB: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.05,
    "n_estimators": 600,
    "num_leaves": 63,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
}


@dataclass
class LgbModel:
    strategy: Strategy = "global"
    params: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULT_LGB))
    seed: int = 0
    models: dict[str, lgb.LGBMRegressor] = field(default_factory=dict)

    def _new(self) -> lgb.LGBMRegressor:
        return lgb.LGBMRegressor(**self.params, random_state=self.seed, verbose=-1, n_jobs=-1)

    def fit(self, X: pd.DataFrame, y: FloatArray) -> LgbModel:
        y = np.asarray(y, dtype=float)
        self.models = {}
        if self.strategy == "global":
            self.models["*"] = self._new().fit(lgb_matrix(X, True), y)
        else:
            for typ in TYPES:
                m = (X["type_local"] == typ).to_numpy()
                if m.any():
                    self.models[typ] = self._new().fit(lgb_matrix(X[m], False), y[m])
        return self

    def predict(self, X: pd.DataFrame) -> FloatArray:
        if not self.models:
            raise RuntimeError("Modèle non entraîné")
        if self.strategy == "global":
            return np.asarray(self.models["*"].predict(lgb_matrix(X, True)), dtype=float)
        out = np.full(len(X), np.nan)
        for typ, model in self.models.items():
            m = (X["type_local"] == typ).to_numpy()
            if m.any():
                out[m] = model.predict(lgb_matrix(X[m], False))
        if np.isnan(out).any():
            raise ValueError("Type de bien sans modèle entraîné")
        return out


def suggest_params(trial: optuna.Trial) -> dict[str, Any]:
    return {
        "objective": trial.suggest_categorical("objective", ["regression", "huber"]),
        "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.15, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 200, 1200, step=100),
        "num_leaves": trial.suggest_int("num_leaves", 15, 255, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 10, 200, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "subsample_freq": 1,
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 30.0, log=True),
    }


def mae_eur(y_log: FloatArray, pred_log: FloatArray) -> float:
    return float(np.mean(np.abs(np.exp(y_log) - np.exp(pred_log))))


def group_cv_mae(
    factory: Callable[[], LogPriceModel],
    X: pd.DataFrame,
    y: FloatArray,
    groups: np.ndarray[Any, Any],
    n_splits: int,
) -> float:
    """MAE €/m² moyenne en GroupKFold (communes)."""
    maes = []
    for tr, va in GroupKFold(n_splits=n_splits).split(X, y, groups):
        model = factory().fit(X.iloc[tr], y[tr])
        maes.append(mae_eur(y[va], model.predict(X.iloc[va])))
    return float(np.mean(maes))


def tune_lgb(
    X: pd.DataFrame,
    y: FloatArray,
    groups: np.ndarray[Any, Any],
    strategy: Strategy,
    n_trials: int,
    n_splits: int = 3,
    seed: int = 0,
) -> tuple[dict[str, Any], float]:
    """Recherche Optuna (TPE) ; renvoie (meilleurs paramètres, MAE €/m² interne)."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial)
        return group_cv_mae(lambda: LgbModel(strategy, params, seed), X, y, groups, n_splits)

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial({k: v for k, v in DEFAULT_LGB.items() if k != "subsample_freq"})
    study.optimize(objective, n_trials=n_trials)
    best = {**study.best_params, "subsample_freq": 1}
    logger.info(
        "Optuna %s : MAE interne %.0f €/m² (%d essais)", strategy, study.best_value, n_trials
    )
    return best, float(study.best_value)
