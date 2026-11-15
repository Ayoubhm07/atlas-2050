"""Projection 2050 (ADR 0004) : valeur = prix estimé actuel × facteurs, en fourchette.

Ce que calcule ce module, et rien d'autre :
1. incertitude du prix actuel : résidus log du test temporel (2024) du modèle POUR LE
   TYPE DU BIEN (maison ou appartement), tirés avec remise ;
2. facteur DPE : le modèle de prix n'utilise pas le DPE, sa prédiction correspond donc
   au mix moyen des classes, pas à la classe D. Le facteur appliqué est l'écart de la
   classe visée À CE MIX : β_classe − Σ part_k · β_k (β_D = 0, parts des maisons
   appariées). Scénarios :
     - `statu_quo` : le bien garde sa classe ; l'écart observé aujourd'hui persiste ;
     - `renovation_D` : le bien est rénové en D (coût des travaux NON inclus) ;
   DPE inconnu : aucun facteur (le bien reste au mix moyen).
   Le calendrier loi Climat et résilience (location interdite G 2025, F 2028, E 2034)
   est restitué comme statut réglementaire à l'horizon, pas converti en prix ;
3. nouveaux risques : seulement ceux que l'appelant déclare comme hypothèse et que le
   bien n'a PAS déjà (`Bien.risques_actuels`, déjà dans le prix estimé). Résultat publié
   comme SENSIBILITÉ, NON CAUSAL : la fourchette couvre les deux bornes de l'effet
   (avec contrôle de voisinage, qui en absorbe une partie ; sans, confondu par la
   localisation), chacune combinée à l'erreur du modèle ;
4. climat RCP 4.5 / 8.5 : délégué à `climate.climate_price_factor`, qui échoue
   explicitement (DRIAS bloqué ; relation prix ↔ climat non estimée).

Domaine : terrain ≤ 1 ha (les maisons au-delà sont exclues de l'entraînement) ;
au-delà, refus explicite.

Euros constants, aucune tendance de marché : la projection répond à « que vaudrait ce
bien aux prix d'aujourd'hui si ces facteurs s'appliquaient », pas « à quel prix se
vendra-t-il en 2050 ».
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from atlas_pipelines.ml.climate import DriasClimate, Scenario, climate_price_factor
from atlas_pipelines.ml.data import MAX_TERRAIN_M2
from atlas_pipelines.ml.effects import RISK_TERMS, Effect

CLIMATE_LAW_RENTAL_BAN: Mapping[str, int] = {"G": 2025, "F": 2028, "E": 2034}
DPE_LABELS = ("A", "B", "C", "D", "E", "F", "G")
PROPERTY_TYPES = ("Maison", "Appartement")
DpeScenario = Literal["statu_quo", "renovation_D"]
QUANTILES = (0.10, 0.50, 0.90)
NON_CAUSAL = "sensibilité, non causal"
FloatArray = np.ndarray[Any, np.dtype[np.float64]]


def rental_ban_year(etiquette: str | None) -> int | None:
    """Année d'interdiction à la location (loi Climat et résilience), None sinon."""
    if etiquette is not None and etiquette not in DPE_LABELS:
        raise ValueError(f"Étiquette DPE invalide : {etiquette!r}")
    return CLIMATE_LAW_RENTAL_BAN.get(etiquette) if etiquette else None


@dataclass(frozen=True)
class Bien:
    prix_m2_estime: float
    surface: float
    type_local: str
    dpe: str | None = None  # None = inconnu
    surface_terrain: float | None = None
    risques_actuels: tuple[str, ...] = ()  # sous-ensemble de RISK_TERMS

    def __post_init__(self) -> None:
        if self.prix_m2_estime <= 0 or self.surface <= 0:
            raise ValueError("prix_m2_estime et surface doivent être > 0")
        if self.type_local not in PROPERTY_TYPES:
            raise ValueError(f"type_local {self.type_local!r} : attendu {PROPERTY_TYPES}")
        rental_ban_year(self.dpe)
        if self.surface_terrain is not None:
            if self.surface_terrain < 0:
                raise ValueError("surface_terrain doit être ≥ 0")
            if self.surface_terrain > MAX_TERRAIN_M2:
                raise ValueError(
                    f"Terrain de {self.surface_terrain:.0f} m² > 10 000 m² : hors du domaine "
                    "du modèle (maisons de plus d'un hectare exclues de l'entraînement)"
                )
        unknown = [r for r in self.risques_actuels if r not in RISK_TERMS]
        if unknown:
            raise ValueError(f"Risques inconnus : {unknown} (attendu {RISK_TERMS})")


@dataclass(frozen=True)
class EffetsPrix:
    """Entrées estimées de la projection (results.json → effets)."""

    dpe: Mapping[str, Effect]  # dpe_A … dpe_G, D = référence
    parts_dpe: Mapping[str, float]  # A … G, somme 1
    risques_avec_voisinage: Mapping[str, Effect]  # borne basse (effet en partie absorbé)
    risques_sans_voisinage: Mapping[str, Effect]  # borne haute (confondue par le lieu)

    def __post_init__(self) -> None:
        bad = [c for c in self.parts_dpe if c not in DPE_LABELS]
        if bad:
            raise ValueError(f"Parts DPE : classe inconnue {bad}")
        if self.parts_dpe and (
            min(self.parts_dpe.values()) < 0 or abs(sum(self.parts_dpe.values()) - 1) > 1e-6
        ):
            raise ValueError("Parts DPE : valeurs ≥ 0 de somme 1 attendues")


@dataclass(frozen=True)
class Hypotheses:
    horizon: int = 2050
    scenario_dpe: DpeScenario = "statu_quo"
    nouveaux_risques: tuple[str, ...] = ()
    scenario_climat: Scenario | None = None

    def __post_init__(self) -> None:
        if not 2025 <= self.horizon <= 2100:
            raise ValueError("horizon entre 2025 et 2100")
        unknown = [r for r in self.nouveaux_risques if r not in RISK_TERMS]
        if unknown:
            raise ValueError(f"Risques inconnus : {unknown} (attendu {RISK_TERMS})")


@dataclass(frozen=True)
class Projection:
    prix_m2: tuple[float, float, float]  # P10, P50, P90
    valeur: tuple[float, float, float]
    location_interdite_depuis: int | None
    composantes: tuple[str, ...]
    non_inclus: tuple[str, ...] = field(default_factory=tuple)
    sensibilite_risques: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "prix_m2_p10_p50_p90": self.prix_m2,
            "valeur_p10_p50_p90": self.valeur,
            "location_interdite_depuis": self.location_interdite_depuis,
            "composantes": list(self.composantes),
            "non_inclus": list(self.non_inclus),
            "sensibilite_risques": (
                None if self.sensibilite_risques is None else dict(self.sensibilite_risques)
            ),
        }


def _draw(effect: Effect, rng: np.random.Generator, n: int) -> FloatArray:
    """Approximation normale de la loi bootstrap du coefficient (IC 95 % → écart-type)."""
    sd = max((effect.high - effect.low) / (2 * 1.959964), 0.0)
    return rng.normal(effect.coef, sd, n)


def dpe_offset_vs_mix(classe: str, betas: Mapping[str, Any], parts: Mapping[str, float]) -> Any:
    """β_classe − Σ part_k · β_k (β_D = 0) : écart de la classe au mix DPE moyen.

    `betas` : dpe_X → coefficient (nombre, ou tableau de tirages de même longueur).
    """

    def beta(c: str) -> Any:
        if c == "D":
            return 0.0
        key = f"dpe_{c}"
        if key not in betas:
            raise KeyError(f"Effet {key} non estimé : écart au mix DPE impossible")
        return betas[key]

    mix = sum(share * beta(c) for c, share in parts.items() if share > 0)
    return beta(classe) - mix


def _dpe_factor(
    bien: Bien, hyp: Hypotheses, effets: EffetsPrix, rng: np.random.Generator, n: int
) -> tuple[FloatArray | None, str, list[str]]:
    """(décalage log tiré ou None, composante, non inclus) du facteur DPE."""
    if bien.dpe is None:
        return None, "", ["DPE inconnu : bien laissé au mix DPE moyen (aucun facteur)"]
    if not effets.parts_dpe:
        raise KeyError("Parts DPE absentes : écart au mix impossible")
    target = "D" if hyp.scenario_dpe == "renovation_D" else bien.dpe
    draws = {k: _draw(e, rng, n) for k, e in sorted(effets.dpe.items())}
    offset = np.asarray(dpe_offset_vs_mix(target, draws, effets.parts_dpe), dtype=float)
    if hyp.scenario_dpe == "renovation_D":
        part = f"DPE {bien.dpe} rénové en D, relatif au mix DPE moyen"
        return offset, part, ["coût de la rénovation"]
    return offset, f"DPE {bien.dpe} relatif au mix DPE moyen, statu quo (écart ≤ 2024)", []


def _risk_bounds(
    risks: tuple[str, ...], effets: EffetsPrix, rng: np.random.Generator, n: int
) -> tuple[FloatArray, FloatArray]:
    """Décalages log tirés pour les deux bornes (avec / sans contrôle de voisinage)."""
    low: FloatArray = np.zeros(n)
    high: FloatArray = np.zeros(n)
    for risk in risks:
        if risk not in effets.risques_avec_voisinage:
            raise KeyError(f"Effet {risk} (avec voisinage) non estimé")
        if risk not in effets.risques_sans_voisinage:
            raise KeyError(f"Effet {risk} (sans voisinage) non estimé")
        low = low + _draw(effets.risques_avec_voisinage[risk], rng, n)
        high = high + _draw(effets.risques_sans_voisinage[risk], rng, n)
    return low, high


def _quantiles(log_p: FloatArray) -> tuple[float, float, float]:
    q = np.exp(np.quantile(log_p, QUANTILES))
    return float(q[0]), float(q[1]), float(q[2])


def _residuals(bien: Bien, residus_par_type: Mapping[str, Any]) -> FloatArray:
    if bien.type_local not in residus_par_type:
        raise KeyError(f"Aucun résidu de test pour le type {bien.type_local!r}")
    raw = np.asarray(residus_par_type[bien.type_local], dtype=float)
    residus: FloatArray = raw[np.isfinite(raw)]
    if residus.size < 30:
        raise ValueError("Au moins 30 résidus de test pour la fourchette du prix actuel")
    return residus


def project(
    bien: Bien,
    hyp: Hypotheses,
    effets: EffetsPrix,
    residus_par_type: Mapping[str, Any],
    climate: DriasClimate | None = None,
    n_draws: int = 20_000,
    seed: int = 0,
) -> Projection:
    """Fourchette P10-P50-P90. Lève une erreur explicite si un facteur demandé manque."""
    residus = _residuals(bien, residus_par_type)
    already = sorted(set(hyp.nouveaux_risques) & set(bien.risques_actuels))
    if already:
        raise ValueError(f"Risques déjà présents sur le bien (déjà dans le prix) : {already}")
    if hyp.scenario_climat is not None:
        # lève DriasUnavailableError ou ClimatePriceEffectNotEstimated : jamais de chiffre
        climate_price_factor(climate, hyp.scenario_climat, hyp.horizon)

    rng = np.random.default_rng(seed)
    log_p = np.log(bien.prix_m2_estime) + rng.choice(residus, n_draws, replace=True)
    parts = [f"incertitude du modèle (résidus du test temporel 2024, {bien.type_local})"]
    absent = ["tendance du marché (euros constants)"]
    if hyp.scenario_climat is None:
        absent.append("climat RCP 4.5 / 8.5 (DRIAS non disponible)")

    offset, part, missing = _dpe_factor(bien, hyp, effets, rng, n_draws)
    absent.extend(missing)
    if offset is not None:
        log_p = log_p + offset
        parts.append(part)

    sensibilite: dict[str, Any] | None = None
    if hyp.nouveaux_risques:
        low, high = _risk_bounds(hyp.nouveaux_risques, effets, rng, n_draws)
        q_low, q_high = _quantiles(log_p + low), _quantiles(log_p + high)
        pooled = _quantiles(np.concatenate([log_p + low, log_p + high]))
        p10, p50, p90 = min(q_low[0], q_high[0]), pooled[1], max(q_low[2], q_high[2])
        sensibilite = {
            "statut": NON_CAUSAL,
            "risques": list(hyp.nouveaux_risques),
            "avec_voisinage": q_low,
            "sans_voisinage": q_high,
        }
        parts.append(
            f"nouveau risque supposé : {', '.join(hyp.nouveaux_risques)} "
            f"({NON_CAUSAL} ; bornes avec et sans contrôle de voisinage)"
        )
    else:
        p10, p50, p90 = _quantiles(log_p)

    if not p10 < p90:
        raise ArithmeticError("Fourchette dégénérée : refus de publier un chiffre unique")
    ban = rental_ban_year(bien.dpe)
    return Projection(
        prix_m2=(p10, p50, p90),
        valeur=(p10 * bien.surface, p50 * bien.surface, p90 * bien.surface),
        location_interdite_depuis=ban if ban is not None and ban <= hyp.horizon else None,
        composantes=tuple(parts),
        non_inclus=tuple(absent),
        sensibilite_risques=sensibilite,
    )
