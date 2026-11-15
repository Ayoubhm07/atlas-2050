"""Métriques en €/m² et intervalle bootstrap par grappes (communes).

Le modèle prédit log(prix/m²) ; les métriques sont calculées après retour à l'échelle
€/m² (exp), celle que lit l'utilisateur. Le bootstrap rééchantillonne des COMMUNES
entières, pas des ventes : les erreurs d'une même commune sont corrélées, un bootstrap
par vente donnerait des intervalles trop étroits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

FloatArray = np.ndarray[Any, np.dtype[np.float64]]


@dataclass(frozen=True)
class Scores:
    n: int
    mae: float
    mape: float
    r2: float
    medae: float

    def as_dict(self) -> dict[str, float]:
        return {
            "n": float(self.n),
            "mae": self.mae,
            "mape": self.mape,
            "r2": self.r2,
            "medae": self.medae,
        }


def scores(y_true: FloatArray, y_pred: FloatArray) -> Scores:
    """y en €/m² (strictement positif)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if y_true.shape != y_pred.shape or y_true.size == 0:
        raise ValueError("y_true et y_pred : mêmes dimensions, non vides")
    if np.any(y_true <= 0):
        raise ValueError("prix/m² observés strictement positifs attendus")
    err = np.abs(y_true - y_pred)
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return Scores(
        n=int(y_true.size),
        mae=float(err.mean()),
        mape=float(np.mean(err / y_true)),
        r2=1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        medae=float(np.median(err)),
    )


@dataclass(frozen=True)
class DiffCI:
    """Différence de MAE (candidat − référence) en €/m², IC percentile."""

    diff: float
    low: float
    high: float
    rel_diff: float
    n_boot: int
    n_groups: int

    @property
    def significant_improvement(self) -> bool:
        return self.high < 0

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "diff": self.diff,
            "low": self.low,
            "high": self.high,
            "rel_diff": self.rel_diff,
            "n_boot": self.n_boot,
            "n_groups": self.n_groups,
            "significatif": self.significant_improvement,
        }


def cluster_bootstrap_mae_diff(
    y_true: FloatArray,
    pred_candidate: FloatArray,
    pred_reference: FloatArray,
    groups: np.ndarray[Any, Any],
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> DiffCI:
    """IC de MAE(candidat) − MAE(référence), communes tirées avec remise (apparié)."""
    y_true = np.asarray(y_true, dtype=float)
    e_c = np.abs(y_true - np.asarray(pred_candidate, dtype=float))
    e_r = np.abs(y_true - np.asarray(pred_reference, dtype=float))
    if not (e_c.shape == e_r.shape == np.shape(groups)):
        raise ValueError("Dimensions incohérentes")
    _, codes = np.unique(np.asarray(groups), return_inverse=True)
    n_groups = int(codes.max()) + 1
    if n_groups < 2:
        raise ValueError("Au moins deux groupes pour un bootstrap par grappes")
    sum_c = np.bincount(codes, weights=e_c, minlength=n_groups)
    sum_r = np.bincount(codes, weights=e_r, minlength=n_groups)
    cnt = np.bincount(codes, minlength=n_groups).astype(float)
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        w = np.bincount(rng.integers(0, n_groups, n_groups), minlength=n_groups)
        n = float(w @ cnt)
        draws[b] = (w @ sum_c - w @ sum_r) / n
    diff = float(e_c.mean() - e_r.mean())
    return DiffCI(
        diff=diff,
        low=float(np.quantile(draws, alpha / 2)),
        high=float(np.quantile(draws, 1 - alpha / 2)),
        rel_diff=diff / float(e_r.mean()),
        n_boot=n_boot,
        n_groups=n_groups,
    )
