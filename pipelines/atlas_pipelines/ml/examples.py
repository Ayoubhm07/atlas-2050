"""Bien FICTIF d'exemple, erreurs du modèle par type, et projections 2050 du rapport.

Le bien d'exemple est une maison « type » (médianes des ventes de maisons du test 2024)
prise parmi les communes SANS PPRI, pour que l'hypothèse « + PPRI » soit un vrai
changement d'exposition. Ses risques actuels sont lus sur ses variables.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from atlas_pipelines.ml.climate import ClimatePriceEffectNotEstimated, DriasUnavailableError
from atlas_pipelines.ml.effects import Effect
from atlas_pipelines.ml.explain import archetype
from atlas_pipelines.ml.projection import Bien, EffetsPrix, Hypotheses, project

QUANTILE_GRID = np.linspace(0, 1, 201)
PredictLog = Callable[[pd.DataFrame], Any]


def _effect(e: Mapping[str, Any]) -> Effect:
    return Effect(
        str(e["term"]),
        float(e["coef"]),
        float(e["low"]),
        float(e["high"]),
        int(e["n_obs"]),
        int(e["n_groups"]),
    )


def effets_from_results(res: Mapping[str, Any]) -> EffetsPrix:
    ef = res["effets"]
    return EffetsPrix(
        dpe={str(e["term"]): _effect(e) for e in ef["dpe"]},
        parts_dpe={str(k): float(v) for k, v in ef["parts_dpe"].items()},
        risques_avec_voisinage={str(e["term"]): _effect(e) for e in ef["risques_avec_voisinage"]},
        risques_sans_voisinage={str(e["term"]): _effect(e) for e in ef["risques_sans_voisinage"]},
    )


def residuals_from_quantiles(quantiles: list[float], n: int = 2001) -> np.ndarray[Any, Any]:
    """Échantillon reconstitué par interpolation des quantiles publiés (0, 0,5 %, … 100 %)."""
    grid = np.linspace(0, 1, len(quantiles))
    values = np.interp(np.linspace(0, 1, n), grid, np.asarray(quantiles, dtype=float))
    return np.asarray(values, dtype=float)


def residual_quantiles_by_type(
    types: pd.Series, resid: np.ndarray[Any, Any]
) -> dict[str, list[float]]:
    """Quantiles 0-100 % (pas 0,5 %) des résidus log du test, par type de bien."""
    out: dict[str, list[float]] = {}
    for typ in sorted(types.unique().tolist()):
        m = (types == typ).to_numpy()
        out[str(typ)] = np.quantile(resid[m], QUANTILE_GRID).tolist()
    return out


def current_risks(row: Mapping[str, Any]) -> list[str]:
    """Risques actuels lus sur les variables du bien (mêmes seuils que effects.risk_terms)."""

    def val(k: str) -> float:
        v = row.get(k)
        return float("nan") if v is None or pd.isna(v) else float(v)

    flags = {
        "ppri": val("ppri") == 1,
        "in_tri": val("in_tri") == 1,
        "catnat_3plus": val("n_catnat_10ans") >= 3,
        "rga_forte": val("rga_code") == 3,
    }
    return [k for k, on in flags.items() if on]


def example_house(X_test: pd.DataFrame, predict_log: PredictLog) -> dict[str, Any]:
    """Maison fictive : médianes des maisons du test situées hors PPRI, et sa prédiction."""
    row = archetype(X_test.loc[X_test["ppri"] == 0], "Maison")
    variables = {k: (None if pd.isna(v) else v) for k, v in row.iloc[0].to_dict().items()}
    return {
        "type_local": "Maison",
        "prediction_m2": float(np.exp(np.asarray(predict_log(row), dtype=float)[0])),
        "surface": float(np.exp(float(row["log_surface"].iloc[0]))),
        "surface_terrain": float(np.expm1(float(row["log_terrain"].iloc[0]))),
        "risques_actuels": current_risks(variables),
        "variables": variables,
    }


def example_projections(res: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Maison fictive hors PPRI, supposée en classe G, sous plusieurs hypothèses."""
    effets = effets_from_results(res)
    resid = {
        typ: residuals_from_quantiles(q)
        for typ, q in res["temporel"]["residus_quantiles_par_type"].items()
    }
    ex = res["temporel"]["bien_exemple"]
    bien = Bien(
        float(ex["prediction_m2"]),
        float(ex["surface"]),
        str(ex["type_local"]),
        "G",
        float(ex["surface_terrain"]),
        tuple(ex["risques_actuels"]),
    )
    cases: list[tuple[str, Hypotheses]] = [
        ("G, statu quo, 2050", Hypotheses(2050, "statu_quo")),
        ("G rénovée en D, 2050", Hypotheses(2050, "renovation_D")),
        (
            "G, statu quo, si la commune entrait en PPRI (sensibilité, non causal)",
            Hypotheses(2050, "statu_quo", ("ppri",)),
        ),
        ("G, statu quo, RCP 8.5", Hypotheses(2050, "statu_quo", (), "rcp85")),
    ]
    out: list[dict[str, Any]] = []
    for label, hyp in cases:
        try:
            out.append({"cas": label, **project(bien, hyp, effets, resid).as_dict()})
        except (DriasUnavailableError, ClimatePriceEffectNotEstimated) as exc:
            out.append({"cas": label, "erreur": str(exc)})
    return out
