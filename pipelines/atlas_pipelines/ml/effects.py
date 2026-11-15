"""Effet prix des risques et du DPE, estimé sur les ventes, avec IC bootstrap.

Régression hédonique (moindres carrés) de log(prix/m²) sur les variables d'intérêt et
des contrôles : surface, pièces, terrain, type, année, revenu et Gini de l'IRIS, et
(au choix) le prix de voisinage H3 antérieur. Le coefficient β d'une variable binaire se
lit comme un écart de prix exp(β) − 1 à caractéristiques égales. C'est une association
conditionnelle, pas un effet causal.

Risques : deux estimations, publiées comme BORNES (docs/methodology.md §4.1).
- AVEC le contrôle de voisinage : TRI, PPRI, Cat-Nat sont communaux et le prix de
  voisinage est fait des ventes de la même zone, donc des mêmes risques ; il absorbe une
  partie de l'effet. Borne basse (en valeur absolue).
- SANS ce contrôle : le coefficient mêle l'effet du risque et tout ce qui distingue les
  communes exposées (bord de l'eau, centre urbain…). Borne haute, confondue par la
  localisation.
Les deux sont estimées sur le même échantillon (ventes ayant un prix de voisinage).

Intervalles : bootstrap par grappes (communes tirées avec remise), percentile 2,5-97,5.

DPE : estimé sur les seules ventes appariées à un DPE (maisons uniquement, les
appartements appariés étant trop rares), classe D en référence, avec contrôle de
voisinage. `dpe_shares` donne la répartition des classes de cet échantillon : le
modèle de prix n'utilisant pas le DPE, sa prédiction correspond à ce mix moyen.
Échantillon biaisé : voir docs/methodology.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

FloatArray = np.ndarray[Any, np.dtype[np.float64]]

RISK_TERMS: tuple[str, ...] = ("ppri", "in_tri", "catnat_3plus", "rga_forte")
DPE_CLASSES: tuple[str, ...] = ("A", "B", "C", "E", "F", "G")  # D = référence
NEIGHBOUR_CONTROL = "voisinage_log_prix"
_CONTROLS_NUM = ("log_surface", "pieces", NEIGHBOUR_CONTROL, "revenu_median", "gini")


@dataclass(frozen=True)
class Effect:
    term: str
    coef: float
    low: float
    high: float
    n_obs: int
    n_groups: int

    @property
    def factor(self) -> tuple[float, float, float]:
        """(bas, central, haut) du multiplicateur de prix exp(β)."""
        return float(np.exp(self.low)), float(np.exp(self.coef)), float(np.exp(self.high))

    def as_dict(self) -> dict[str, float | str]:
        lo, mid, hi = self.factor
        return {
            "term": self.term,
            "coef": self.coef,
            "low": self.low,
            "high": self.high,
            "factor_low": lo,
            "factor": mid,
            "factor_high": hi,
            "n_obs": self.n_obs,
            "n_groups": self.n_groups,
        }


def _design(
    df: pd.DataFrame, terms: dict[str, FloatArray], neighbourhood_control: bool = True
) -> tuple[FloatArray, list[str]]:
    cols: dict[str, FloatArray] = {"const": np.ones(len(df))}
    cols.update(terms)
    controls = [c for c in _CONTROLS_NUM if neighbourhood_control or c != NEIGHBOUR_CONTROL]
    for c in controls:
        v = df[c].to_numpy(dtype=float)
        miss = np.isnan(v)
        if miss.any():
            cols[f"{c}_manquant"] = miss.astype(float)
            v = np.where(miss, np.nanmedian(v) if (~miss).any() else 0.0, v)
        cols[c] = v
    terrain = df["log_terrain"].to_numpy(dtype=float)
    cols["log_terrain"] = np.nan_to_num(terrain, nan=0.0)
    if df["type_local"].nunique() > 1:
        cols["est_maison"] = (df["type_local"] == "Maison").to_numpy(dtype=float)
    years = sorted(df["annee"].unique().tolist())
    for y in years[1:]:
        cols[f"annee_{y}"] = (df["annee"] == y).to_numpy(dtype=float)
    names = [n for n, v in cols.items() if np.ptp(v) > 0 or n == "const"]
    return np.column_stack([cols[n] for n in names]), names


def _ols(X: FloatArray, y: FloatArray) -> FloatArray:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return np.asarray(beta, dtype=float)


def bootstrap_ols(
    df: pd.DataFrame,
    terms: dict[str, FloatArray],
    n_boot: int = 300,
    seed: int = 0,
    neighbourhood_control: bool = True,
) -> list[Effect]:
    """Coefficients de `terms` et leur IC bootstrap par commune.

    L'échantillon (ventes ayant un prix de voisinage) ne dépend pas de
    `neighbourhood_control` : les deux bornes portent sur les mêmes ventes.
    """
    keep = ~np.isnan(df[NEIGHBOUR_CONTROL].to_numpy(dtype=float))
    sub = df.loc[keep].reset_index(drop=True)
    terms = {k: np.asarray(v, dtype=float)[keep] for k, v in terms.items()}
    X, names = _design(sub, terms, neighbourhood_control)
    y = sub["log_prix_m2"].to_numpy(dtype=float)
    present = [t for t in terms if t in names]
    idx = [names.index(t) for t in present]
    beta = _ols(X, y)[idx]
    _, codes = np.unique(sub["code_commune"].to_numpy(), return_inverse=True)
    n_groups = int(codes.max()) + 1
    members = [np.flatnonzero(codes == g) for g in range(n_groups)]
    rng = np.random.default_rng(seed)
    draws = np.empty((n_boot, len(idx)))
    for b in range(n_boot):
        rows = np.concatenate([members[g] for g in rng.integers(0, n_groups, n_groups)])
        draws[b] = _ols(X[rows], y[rows])[idx]
    low, high = np.quantile(draws, [0.025, 0.975], axis=0)
    return [
        Effect(t, float(beta[i]), float(low[i]), float(high[i]), len(sub), n_groups)
        for i, t in enumerate(present)
    ]


def risk_terms(df: pd.DataFrame) -> dict[str, FloatArray]:
    """Indicateurs binaires (NaN → 0 : commune non couverte = risque non signalé)."""
    return {
        "ppri": np.nan_to_num(df["ppri"].to_numpy(dtype=float)),
        "in_tri": np.nan_to_num(df["in_tri"].to_numpy(dtype=float)),
        "catnat_3plus": (df["n_catnat_10ans"].to_numpy(dtype=float) >= 3).astype(float),
        "rga_forte": (df["rga_code"].to_numpy(dtype=float) == 3).astype(float),
    }


def estimate_risk_effects(
    df: pd.DataFrame, n_boot: int = 300, seed: int = 0, neighbourhood_control: bool = True
) -> list[Effect]:
    """Effets des risques ; `neighbourhood_control=False` donne la borne haute."""
    return bootstrap_ols(
        df, risk_terms(df), n_boot=n_boot, seed=seed, neighbourhood_control=neighbourhood_control
    )


def _dpe_sample(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[
        (df["type_local"] == "Maison") & df["dpe_etiquette"].isin([*DPE_CLASSES, "D"])
    ].reset_index(drop=True)


def dpe_shares(df: pd.DataFrame) -> dict[str, float]:
    """Part de chaque classe A-G dans l'échantillon d'estimation des effets DPE."""
    sub = _dpe_sample(df)
    sub = sub.loc[~np.isnan(sub[NEIGHBOUR_CONTROL].to_numpy(dtype=float))]
    if sub.empty:
        raise ValueError("Aucune maison appariée à un DPE : répartition des classes inconnue")
    counts = sub["dpe_etiquette"].value_counts()
    return {c: float(counts.get(c, 0)) / len(sub) for c in sorted([*DPE_CLASSES, "D"])}


def estimate_dpe_effects(df: pd.DataFrame, n_boot: int = 300, seed: int = 0) -> list[Effect]:
    sub = _dpe_sample(df)
    terms = {f"dpe_{c}": (sub["dpe_etiquette"] == c).to_numpy(dtype=float) for c in DPE_CLASSES}
    return bootstrap_ols(sub, terms, n_boot=n_boot, seed=seed)
