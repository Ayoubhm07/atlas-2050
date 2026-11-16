"""Estimation d'un bien FICTIF : prix actuel, projection 2050 et facteurs SHAP.

Réutilise le paquet ML du sprint 3 (atlas_pipelines.ml), sans le dupliquer :
- `rerender.SavedModel` recharge le booster LightGBM sauvegardé (une fois, au démarrage) ;
- `features.neighbourhood_log_price` calcule le prix de voisinage sur des ventes de
  référence du gold STRICTEMENT antérieures à la date de valeur ;
- `models.lgb_matrix` construit la matrice exacte du modèle ;
- `projection.project` produit les fourchettes (statu quo, rénovation, sensibilité
  nouveaux risques à deux bornes, climat → erreur explicite DRIAS) ;
- `examples` lit effets et résidus de `results.json` et les risques actuels du bien.

Les valeurs SHAP sont les contributions TreeSHAP natives de LightGBM
(`pred_contrib=True`, même algorithme que shap.TreeExplainer), en log-prix.

ADR 0005 : aucune vente n'est renvoyée ; les variables de voisinage (dérivées de ventes
voisines) sont restituées comme contribution, jamais comme valeur. Sous 5 ventes dans
l'anneau, la médiane des voisins n'est pas utilisée (a priori seul, même règle qu'à
l'entraînement) : le prix d'une vente isolée ne peut pas se lire dans l'estimation.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
from atlas_pipelines.ml.climate import ClimatePriceEffectNotEstimated, DriasUnavailableError
from atlas_pipelines.ml.effects import RISK_TERMS
from atlas_pipelines.ml.examples import (
    current_risks,
    effets_from_results,
    residuals_from_quantiles,
)
from atlas_pipelines.ml.features import MIN_NEIGHBOUR_SALES, neighbourhood_log_price
from atlas_pipelines.ml.models import lgb_matrix
from atlas_pipelines.ml.projection import (
    NON_CAUSAL,
    Bien,
    EffetsPrix,
    Hypotheses,
    Projection,
    project,
)
from atlas_pipelines.ml.rerender import SavedModel

from atlas_api.db import PointContext, ReferenceSale
from atlas_api.schemas import (
    EstimateQuery,
    Estimation,
    Facteur,
    Fourchette,
    Localisation,
    RisquesActuels,
    Scenario,
    Sensibilite,
)

logger = logging.getLogger("atlas_api.estimator")

HORIZON = 2050
NEIGHBOUR_K = 30  # mêmes réglages que l'entraînement (features.neighbourhood_log_price)
NEIGHBOUR_PRIOR = 500
TOP_FACTORS = 6
H3_RES = 7
_EPOCH = (2021, 1)
_DPE_RENOVABLE = ("E", "F", "G")
_CLIMATE_MESSAGE = (
    "Projection climatique non calculée : données DRIAS non disponibles (compte requis, "
    "pas d'API) et relation prix ↔ climat non estimée. Aucun chiffre n'est publié."
)
LABELS: dict[str, str] = {
    "log_surface": "surface habitable",
    "pieces": "nombre de pièces",
    "log_terrain": "surface de terrain",
    "n_dependances": "dépendances",
    "revenu_median": "revenu médian de l'IRIS",
    "gini": "inégalités de revenu de l'IRIS (Gini)",
    "rga_code": "exposition retrait-gonflement des argiles",
    "in_tri": "commune en territoire à risque d'inondation (TRI)",
    "ppri": "commune couverte par un PPRI",
    "n_catnat_10ans": "arrêtés Cat-Nat sur 10 ans",
    "voisinage_log_prix": "prix des ventes antérieures du voisinage",
    "voisinage_n": "nombre de ventes de voisinage",
    "lon": "position (longitude)",
    "lat": "position (latitude)",
    "t_mois": "date de valeur",
    "est_maison": "type de bien",
}
_HIDDEN_VALUES = frozenset({"voisinage_log_prix", "voisinage_n", "lon", "lat", "t_mois"})
RISK_LABELS: dict[str, str] = {
    "ppri": "si la commune entrait en PPRI",
    "in_tri": "si la commune entrait en TRI",
    "catnat_3plus": "si la commune comptait 3 arrêtés Cat-Nat ou plus sur 10 ans",
    "rga_forte": "si l'exposition aux argiles devenait forte",
}


class ModelUnavailableError(RuntimeError):
    """Modèle ou results.json absent / incohérent (503 côté API)."""


@dataclass(frozen=True)
class ModelBundle:
    model: SavedModel
    effets: EffetsPrix
    residus: dict[str, np.ndarray[Any, Any]]


def load_bundle(ml_dir: Path) -> ModelBundle:
    """Charge results.json et le booster sauvegardé (appelé une fois au démarrage)."""
    try:
        res: dict[str, Any] = json.loads((ml_dir / "results.json").read_text(encoding="utf-8"))
        model = SavedModel(ml_dir / "models", str(res["meta"]["strategie"]))
        residus = {
            str(t): residuals_from_quantiles(q)
            for t, q in res["temporel"]["residus_quantiles_par_type"].items()
        }
        return ModelBundle(model, effets_from_results(res), residus)
    except (OSError, KeyError, ValueError) as exc:
        raise ModelUnavailableError(f"Modèle de prix non chargé : {type(exc).__name__}") from exc


def t_mois(day: dt.date) -> int:
    return (day.year - _EPOCH[0]) * 12 + (day.month - _EPOCH[1])


def _flag(value: bool | None) -> float:
    return float("nan") if value is None else float(value)


def _opt(value: float | int | None) -> float:
    return float("nan") if value is None else float(value)


def neighbour_features(
    sales: Sequence[ReferenceSale], cell: str, type_local: str, valuation_date: dt.date
) -> tuple[float, int]:
    """(voisinage_log_prix, voisinage_n) du bien, calculés par la fonction d'entraînement."""
    rows = [(s.date_mutation, s.h3_r7, math.log(s.prix_m2)) for s in sales if s.prix_m2 > 0]
    rows.append((valuation_date, cell, float("nan")))
    df = pd.DataFrame(rows, columns=["date_mutation", "h3_r7", "log_prix_m2"])
    df["type_local"] = type_local
    reference = np.ones(len(df), dtype=bool)
    reference[-1] = False  # le bien n'est jamais sa propre référence
    out = neighbourhood_log_price(
        df,
        reference=reference,
        k=NEIGHBOUR_K,
        n_prior=NEIGHBOUR_PRIOR,
        min_sales=MIN_NEIGHBOUR_SALES,
    )
    return float(out["voisinage_log_prix"].iloc[-1]), int(out["voisinage_n"].iloc[-1])


def feature_row(
    q: EstimateQuery,
    ctx: PointContext,
    lon: float,
    lat: float,
    valuation_date: dt.date,
    voisinage: tuple[float, int],
) -> pd.DataFrame:
    terrain = q.surface_terrain if q.type_local == "Maison" else None
    row: dict[str, Any] = {
        "type_local": q.type_local,
        "log_surface": math.log(q.surface),
        "pieces": float(q.pieces),
        "log_terrain": math.log1p(terrain) if terrain is not None else float("nan"),
        "n_dependances": float(q.dependances),
        "revenu_median": _opt(ctx.revenu_median),
        "gini": _opt(ctx.gini),
        "rga_code": _opt(ctx.rga_code),
        "in_tri": _flag(ctx.in_tri),
        "ppri": _flag(ctx.ppri),
        "n_catnat_10ans": _opt(ctx.n_catnat_10ans),
        "voisinage_log_prix": voisinage[0],
        "voisinage_n": float(voisinage[1]),
        "lon": lon,
        "lat": lat,
        "t_mois": float(t_mois(valuation_date)),
    }
    return pd.DataFrame([row])


def _round(x: float, step: float) -> float:
    return float(round(x / step) * step)


def fourchette(t: Sequence[float], step: float) -> Fourchette:
    return Fourchette(p10=_round(t[0], step), p50=_round(t[1], step), p90=_round(t[2], step))


def _scenario(sid: str, libelle: str, p: Projection) -> Scenario:
    sens = None
    if p.sensibilite_risques is not None:
        s = p.sensibilite_risques
        sens = Sensibilite(
            statut=str(s["statut"]),
            risques=tuple(s["risques"]),
            avec_voisinage=fourchette(s["avec_voisinage"], 10),
            sans_voisinage=fourchette(s["sans_voisinage"], 10),
        )
    return Scenario(
        id=sid,
        libelle=libelle,
        statut="calcule",
        prix_m2=fourchette(p.prix_m2, 10),
        valeur=fourchette(p.valeur, 1000),
        location_interdite_depuis=p.location_interdite_depuis,
        composantes=p.composantes,
        non_inclus=p.non_inclus,
        sensibilite=sens,
    )


class Estimator:
    def __init__(self, bundle: ModelBundle, n_draws: int = 20_000) -> None:
        self.bundle = bundle
        self.n_draws = n_draws

    # -- prédiction et explication ---------------------------------------------------

    def _matrix(self, X: pd.DataFrame) -> tuple[Any, pd.DataFrame]:
        model = self.bundle.model
        if model.strategy == "global":
            return model.boosters["global"], lgb_matrix(X, True)
        typ = str(X["type_local"].iloc[0])
        return model.boosters[typ], lgb_matrix(X, False)

    def predict_log(self, X: pd.DataFrame) -> float:
        return float(np.asarray(self.bundle.model.predict(X), dtype=float)[0])

    def factors(self, X: pd.DataFrame, q: EstimateQuery) -> tuple[Facteur, ...]:
        booster, mat = self._matrix(X)
        contrib = np.asarray(booster.predict(mat, pred_contrib=True), dtype=float)[0][:-1]
        shown: dict[str, float | None] = {
            "log_surface": q.surface,
            "log_terrain": q.surface_terrain if q.type_local == "Maison" else None,
            "est_maison": 1.0 if q.type_local == "Maison" else 0.0,
        }
        order = np.argsort(-np.abs(contrib))[:TOP_FACTORS]
        out: list[Facteur] = []
        for i in order:
            name = str(mat.columns[i])
            raw = mat.iloc[0, i]
            value: float | None
            if name in _HIDDEN_VALUES:
                value = None
            elif name in shown:
                value = shown[name]
            else:
                value = None if pd.isna(raw) else float(raw)
            out.append(
                Facteur(
                    variable=name,
                    libelle=LABELS.get(name, name),
                    contribution_pct=round(float(np.expm1(contrib[i])) * 100, 1),
                    valeur=value,
                )
            )
        return tuple(out)

    # -- projection ------------------------------------------------------------------

    def _project(self, bien: Bien, hyp: Hypotheses) -> Projection:
        return project(bien, hyp, self.bundle.effets, self.bundle.residus, n_draws=self.n_draws)

    def scenarios(self, bien: Bien) -> tuple[Scenario, ...]:
        out = [
            _scenario(
                "statu_quo",
                f"{HORIZON}, statu quo"
                + (f" (DPE {bien.dpe})" if bien.dpe else " (DPE inconnu : mix moyen)"),
                self._project(bien, Hypotheses(HORIZON, "statu_quo")),
            )
        ]
        if bien.dpe in _DPE_RENOVABLE:
            out.append(
                _scenario(
                    "renovation_D",
                    f"{HORIZON}, DPE {bien.dpe} rénové en D (coût des travaux non inclus)",
                    self._project(bien, Hypotheses(HORIZON, "renovation_D")),
                )
            )
        else:
            out.append(
                Scenario(
                    id="renovation_D",
                    libelle=f"{HORIZON}, rénovation en D",
                    statut="non_applicable",
                    message="DPE inconnu ou déjà D ou mieux : rénovation en D non simulée",
                )
            )
        for risk in RISK_TERMS:
            sid, label = f"nouveau_risque_{risk}", f"{HORIZON}, {RISK_LABELS[risk]} ({NON_CAUSAL})"
            if risk in bien.risques_actuels:
                out.append(
                    Scenario(
                        id=sid,
                        libelle=label,
                        statut="non_applicable",
                        message="Risque déjà présent : il est déjà dans le prix estimé",
                    )
                )
                continue
            try:
                hyp = Hypotheses(HORIZON, "statu_quo", (risk,))
                out.append(_scenario(sid, label, self._project(bien, hyp)))
            except KeyError:
                out.append(
                    Scenario(id=sid, libelle=label, statut="effet_non_estime",
                             message="Effet de ce risque non estimé sur les ventes")
                )
        for rcp, nom in (("rcp45", "RCP 4.5"), ("rcp85", "RCP 8.5")):
            try:
                self._project(bien, Hypotheses(HORIZON, "statu_quo", (), rcp))
            except (DriasUnavailableError, ClimatePriceEffectNotEstimated):
                out.append(
                    Scenario(
                        id=f"climat_{rcp}",
                        libelle=f"{HORIZON}, climat {nom}",
                        statut="indisponible (DRIAS)",
                        message=_CLIMATE_MESSAGE,
                    )
                )
            else:  # pragma: no cover - garde-fou : le module climat ne doit jamais chiffrer
                raise RuntimeError("Le module climat a renvoyé un chiffre : refus de publier")
        return tuple(out)

    # -- point d'entrée --------------------------------------------------------------

    def estimate(
        self,
        q: EstimateQuery,
        ctx: PointContext,
        lon: float,
        lat: float,
        valuation_date: dt.date,
        sales: Sequence[ReferenceSale],
        localisation: Localisation,
    ) -> Estimation:
        cell = h3.latlng_to_cell(lat, lon, H3_RES)
        voisinage = neighbour_features(sales, cell, q.type_local, valuation_date)
        X = feature_row(q, ctx, lon, lat, valuation_date, voisinage)
        prix = math.exp(self.predict_log(X))
        risques = tuple(current_risks(X.iloc[0].to_dict()))
        terrain = q.surface_terrain if q.type_local == "Maison" else None
        base = Bien(prix, q.surface, q.type_local, None, terrain, risques)
        actuel = self._project(base, Hypotheses(HORIZON))
        bien = Bien(prix, q.surface, q.type_local, q.dpe, terrain, risques)
        return Estimation(
            localisation=localisation,
            date_valeur=valuation_date,
            type_local=q.type_local,
            surface=q.surface,
            prix_m2=fourchette(actuel.prix_m2, 10),
            valeur=fourchette(actuel.valeur, 1000),
            risques_actuels=RisquesActuels(
                termes=risques,
                n_catnat_10ans=ctx.n_catnat_10ans,
                in_tri=ctx.in_tri,
                ppri=ctx.ppri,
                azi=ctx.azi,
                rga_exposition=ctx.rga_exposition,
            ),
            horizon=HORIZON,
            scenarios=self.scenarios(bien),
            facteurs=self.factors(X, q),
            avertissements=self._warnings(valuation_date),
        )

    @staticmethod
    def _warnings(valuation_date: dt.date) -> tuple[str, ...]:
        # Liste identique quel que soit le nombre de ventes voisines : un avertissement
        # conditionnel servirait d'oracle (ajout/retrait d'une vente détectable).
        return (
            "Estimation par modèle pour un bien fictif : ce n'est le prix d'aucune vente "
            "(ADR 0005).",
            "Prix actuel : modèle sans DPE (mix moyen des classes) ; fourchette P10-P90 issue "
            "des erreurs du modèle sur les ventes 2024 du même type.",
            f"Date de valeur {valuation_date.isoformat()} : lendemain de la dernière vente du "
            "gold. Euros constants, aucune tendance de marché.",
            "Cat-Nat : compteur sur 10 ans à la date de référence du gold.",
            f"Prix de voisinage : médiane d'au moins {MIN_NEIGHBOUR_SALES} ventes antérieures "
            "du voisinage H3 ; en dessous, a priori départemental seul (ADR 0005).",
        )
