"""Protocoles de validation : GroupKFold par commune et split temporel.

Dans les deux protocoles la variable de voisinage est RECALCULÉE pour chaque pli, avec
comme ventes de référence le seul ensemble d'entraînement (et toujours strictement
antérieures à la vente). Un hyperparamétrage Optuna est fait DANS chaque pli
d'entraînement (validation imbriquée) : aucune vente de test ne sert au choix des
paramètres.

Limite connue (non corrigée, docs/methodology.md §4.9) : dans les plis INTERNES
d'Optuna (`make_tuner`) et dans `choose_strategy`, la variable de voisinage n'est pas
recalculée par pli interne (elle est faite sur tout l'ensemble d'entraînement). Les
scores de test ne sont pas affectés ; seul le choix des hyperparamètres est optimiste.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from atlas_pipelines.ml.features import NEIGHBOUR_COLUMNS, neighbourhood_log_price
from atlas_pipelines.ml.metrics import scores
from atlas_pipelines.ml.models import LgbModel, RidgeModel, Strategy, group_cv_mae, tune_lgb

logger = logging.getLogger(__name__)

Tuner = Callable[[pd.DataFrame, Any, Any], dict[str, Any]]


def with_neighbours(df: pd.DataFrame, reference: np.ndarray[Any, Any]) -> pd.DataFrame:
    feats = neighbourhood_log_price(df, reference=reference)
    return df.drop(columns=[c for c in NEIGHBOUR_COLUMNS if c in df.columns]).join(feats)


@dataclass(frozen=True)
class FoldResult:
    """Prédictions €/m² alignées sur les lignes évaluées."""

    test_index: np.ndarray[Any, Any]
    pred_ridge: np.ndarray[Any, Any]
    pred_lgb: np.ndarray[Any, Any]
    params: dict[str, Any]


def fit_predict(
    df: pd.DataFrame,
    train: np.ndarray[Any, Any],
    test: np.ndarray[Any, Any],
    strategy: Strategy,
    tuner: Tuner | None,
) -> tuple[FoldResult, LgbModel, pd.DataFrame]:
    """Entraîne Ridge et LightGBM sur `train`, prédit `test` (masques booléens)."""
    feat = with_neighbours(df, reference=train)
    X_tr, X_te = feat.loc[train], feat.loc[test]
    y_tr = X_tr["log_prix_m2"].to_numpy()
    params = tuner(X_tr, y_tr, X_tr["code_commune"].to_numpy()) if tuner else {}
    ridge = RidgeModel().fit(X_tr, y_tr)
    lgbm = LgbModel(strategy, params) if params else LgbModel(strategy)
    lgbm.fit(X_tr, y_tr)
    result = FoldResult(
        test_index=np.flatnonzero(test),
        pred_ridge=np.exp(ridge.predict(X_te)),
        pred_lgb=np.exp(lgbm.predict(X_te)),
        params=dict(lgbm.params),
    )
    return result, lgbm, X_te


def spatial_cv(
    df: pd.DataFrame, strategy: Strategy, tuner: Tuner | None, n_splits: int = 5
) -> pd.DataFrame:
    """Prédictions hors pli (une par vente), plis = communes disjointes."""
    pred_r = np.full(len(df), np.nan)
    pred_l = np.full(len(df), np.nan)
    fold = np.full(len(df), -1)
    groups = df["code_commune"].to_numpy()
    for k, (tr, te) in enumerate(GroupKFold(n_splits=n_splits).split(df, groups=groups)):
        train = np.zeros(len(df), bool)
        train[tr] = True
        res, _, _ = fit_predict(df, train, ~train, strategy, tuner)
        pred_r[res.test_index] = res.pred_ridge
        pred_l[res.test_index] = res.pred_lgb
        fold[res.test_index] = k
        logger.info("Pli %d/%d : %d ventes de test", k + 1, n_splits, len(te))
    return pd.DataFrame({"pred_ridge": pred_r, "pred_lgb": pred_l, "fold": fold}, index=df.index)


def choose_strategy(df_train: pd.DataFrame, n_splits: int = 3) -> dict[str, float]:
    """MAE GroupKFold (paramètres par défaut) des deux stratégies, sur le train seul."""
    feat = with_neighbours(df_train, reference=np.ones(len(df_train), bool))
    y = feat["log_prix_m2"].to_numpy()
    groups = feat["code_commune"].to_numpy()
    strategies: tuple[Strategy, ...] = ("global", "par_type")
    out: dict[str, float] = {}
    for strategy in strategies:

        def factory(strategy: Strategy = strategy) -> LgbModel:
            return LgbModel(strategy)

        out[strategy] = group_cv_mae(factory, feat, y, groups, n_splits)
    return out


def make_tuner(strategy: Strategy, n_trials: int, seed: int = 0) -> Tuner:
    def tuner(X: pd.DataFrame, y: Any, groups: Any) -> dict[str, Any]:
        params, _ = tune_lgb(X, y, groups, strategy, n_trials=n_trials, seed=seed)
        return params

    return tuner


def scores_by(
    df: pd.DataFrame, y: np.ndarray[Any, Any], pred: np.ndarray[Any, Any], col: str | None
) -> dict[str, dict[str, float]]:
    """Scores globaux (`col=None`) ou par modalité de `col`."""
    if col is None:
        return {"tous": scores(y, pred).as_dict()}
    out: dict[str, dict[str, float]] = {}
    for value in sorted(df[col].dropna().unique().tolist(), key=str):
        m = (df[col] == value).to_numpy()
        out[str(value)] = scores(y[m], pred[m]).as_dict()
    return out
