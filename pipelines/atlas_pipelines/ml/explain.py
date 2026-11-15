"""SHAP global et exemple local sur un bien FICTIF (ADR 0005).

L'exemple local n'est pas une vente : c'est un « bien type » dont chaque variable est la
médiane (ou la modalité la plus fréquente) des ventes de test du groupe choisi. Aucune
vente réelle n'est expliquée ni affichée.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import shap

from atlas_pipelines.ml.models import LgbModel, lgb_matrix


def _explain(model: LgbModel, X: pd.DataFrame) -> tuple[np.ndarray[Any, Any], pd.DataFrame, float]:
    """Valeurs SHAP (log-prix) de X, alignées sur une matrice commune ; base moyenne."""
    if model.strategy == "global":
        mat = lgb_matrix(X, True)
        exp = shap.TreeExplainer(model.models["*"])
        return np.asarray(exp.shap_values(mat)), mat, float(np.ravel(exp.expected_value)[0])
    values, mats, bases = [], [], []
    for typ, booster in model.models.items():
        m = (X["type_local"] == typ).to_numpy()
        if not m.any():
            continue
        mat = lgb_matrix(X[m], False)
        exp = shap.TreeExplainer(booster)
        values.append(np.asarray(exp.shap_values(mat)))
        mats.append(mat)
        bases.append(float(np.ravel(exp.expected_value)[0]) * m.sum())
    return np.vstack(values), pd.concat(mats), sum(bases) / len(X)


def global_importance(model: LgbModel, X: pd.DataFrame, n: int = 3000, seed: int = 0) -> pd.Series:
    """Moyenne des |SHAP| (en log-prix) par variable, décroissante."""
    sample = X.sample(min(n, len(X)), random_state=seed)
    values, mat, _ = _explain(model, sample)
    return pd.Series(np.abs(values).mean(axis=0), index=mat.columns).sort_values(ascending=False)


def archetype(X: pd.DataFrame, type_local: str, min_sales: int = 50) -> pd.DataFrame:
    """Bien fictif : médiane des variables des ventes de `type_local` (≥ min_sales)."""
    sub = X.loc[X["type_local"] == type_local]
    if len(sub) < min_sales:
        raise ValueError(f"Moins de {min_sales} ventes {type_local} : pas de bien type")
    row = sub.median(numeric_only=True).to_frame().T
    for col in ("in_tri", "ppri", "rga_code", "pieces", "n_dependances", "n_catnat_10ans"):
        if col in row.columns:
            row[col] = sub[col].mode(dropna=True).iloc[0] if sub[col].notna().any() else np.nan
    row["type_local"] = type_local
    return row


def local_explanation(model: LgbModel, row: pd.DataFrame) -> tuple[pd.Series, float]:
    """Contributions SHAP du bien fictif et valeur de base (log-prix)."""
    values, mat, base = _explain(model, row)
    if model.strategy != "global":
        base = float(
            np.ravel(
                shap.TreeExplainer(model.models[str(row["type_local"].iloc[0])]).expected_value
            )[0]
        )
    return pd.Series(values[0], index=mat.columns), base
