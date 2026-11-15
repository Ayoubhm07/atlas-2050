"""Projection 2050 : calendrier loi Climat, fourchettes, DRIAS absent = échec explicite."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atlas_pipelines.ml.climate import (
    ClimatePriceEffectNotEstimated,
    DriasClimate,
    DriasUnavailableError,
    climate_price_factor,
)
from atlas_pipelines.ml.effects import Effect
from atlas_pipelines.ml.projection import (
    NON_CAUSAL,
    Bien,
    EffetsPrix,
    Hypotheses,
    dpe_offset_vs_mix,
    project,
    rental_ban_year,
)

_RNG = np.random.default_rng(0)
RESID = {"Maison": _RNG.normal(0, 0.15, 2000), "Appartement": _RNG.normal(0, 0.05, 2000)}


def _fixed(term: str, coef: float) -> Effect:
    """Effet sans incertitude (IC de largeur nulle) : calculs exacts dans les tests."""
    return Effect(term, coef, coef, coef, 1000, 100)


DPE_BETAS = {"A": 0.20, "B": 0.15, "C": 0.10, "E": -0.10, "F": -0.17, "G": -0.25}
BETAS = {f"dpe_{c}": b for c, b in DPE_BETAS.items()}
PARTS = {"A": 0.05, "B": 0.10, "C": 0.30, "D": 0.30, "E": 0.15, "F": 0.06, "G": 0.04}
EFFETS = EffetsPrix(
    dpe={k: Effect(k, b, b - 0.05, b + 0.05, 1000, 100) for k, b in BETAS.items()},
    parts_dpe=PARTS,
    risques_avec_voisinage={"ppri": Effect("ppri", -0.004, -0.033, 0.020, 50000, 500)},
    risques_sans_voisinage={"ppri": Effect("ppri", -0.189, -0.25, -0.13, 50000, 500)},
)
EXACT = EffetsPrix(
    dpe={k: _fixed(k, b) for k, b in BETAS.items()},
    parts_dpe=PARTS,
    risques_avec_voisinage={},
    risques_sans_voisinage={},
)
MIX = sum(PARTS[c] * DPE_BETAS.get(c, 0.0) for c in PARTS)


def maison(
    dpe: str | None = "D",
    surface_terrain: float | None = None,
    risques_actuels: tuple[str, ...] = (),
) -> Bien:
    return Bien(3000.0, 100.0, "Maison", dpe, surface_terrain, risques_actuels)


def test_climate_law_calendar() -> None:
    assert rental_ban_year("G") == 2025
    assert rental_ban_year("F") == 2028
    assert rental_ban_year("E") == 2034
    assert rental_ban_year("D") is None
    assert rental_ban_year(None) is None
    with pytest.raises(ValueError):
        rental_ban_year("H")


def test_projection_is_always_a_range() -> None:
    p = project(maison("D"), Hypotheses(), EFFETS, RESID)
    lo, mid, hi = p.prix_m2
    assert lo < mid < hi
    assert p.valeur == pytest.approx((lo * 100, mid * 100, hi * 100))
    assert p.location_interdite_depuis is None
    assert p.sensibilite_risques is None
    assert any("climat" in x for x in p.non_inclus)
    assert set(p.as_dict()) >= {"prix_m2_p10_p50_p90", "non_inclus", "sensibilite_risques"}


def test_dpe_offset_is_relative_to_the_sales_mix() -> None:
    """Le modèle ne voit pas le DPE : sa prédiction vaut pour le mix moyen, pas pour D."""
    assert dpe_offset_vs_mix("D", BETAS, PARTS) == pytest.approx(-MIX)
    assert dpe_offset_vs_mix("G", BETAS, PARTS) == pytest.approx(-0.25 - MIX)
    unknown = project(maison(None), Hypotheses(), EXACT, RESID)
    d = project(maison("D"), Hypotheses(), EXACT, RESID)
    reno = project(maison("G"), Hypotheses(scenario_dpe="renovation_D"), EXACT, RESID)
    g = project(maison("G"), Hypotheses(), EXACT, RESID)
    # mêmes tirages de résidus : les rapports de quantiles sont exacts
    assert d.prix_m2[1] / unknown.prix_m2[1] == pytest.approx(np.exp(-MIX))
    assert reno.prix_m2[1] == pytest.approx(d.prix_m2[1])
    assert g.prix_m2[1] / unknown.prix_m2[1] == pytest.approx(np.exp(-0.25 - MIX))
    assert "DPE inconnu" in " ".join(unknown.non_inclus)
    assert any("mix" in c for c in d.composantes)


def test_dpe_g_statu_quo_lowers_value_and_flags_ban() -> None:
    base = project(maison("D"), Hypotheses(horizon=2050), EFFETS, RESID)
    g = project(maison("G"), Hypotheses(horizon=2050), EFFETS, RESID)
    assert g.prix_m2[1] < base.prix_m2[1]
    assert g.location_interdite_depuis == 2025
    reno = project(maison("G"), Hypotheses(scenario_dpe="renovation_D"), EFFETS, RESID)
    assert "coût de la rénovation" in reno.non_inclus
    e = project(maison(None), Hypotheses(horizon=2030), EFFETS, RESID)
    assert e.location_interdite_depuis is None


def test_dpe_requires_every_class_of_the_mix() -> None:
    partial = EffetsPrix({"dpe_G": _fixed("dpe_G", -0.2)}, PARTS, {}, {})
    with pytest.raises(KeyError, match="dpe_A"):
        project(maison("G"), Hypotheses(), partial, RESID)
    with pytest.raises(ValueError, match="somme"):
        EffetsPrix({}, {"D": 0.5}, {}, {})
    with pytest.raises(ValueError, match="classe"):
        EffetsPrix({}, {"H": 1.0}, {}, {})


def test_new_risk_is_a_sensitivity_range_spanning_both_bounds() -> None:
    hyp = Hypotheses(nouveaux_risques=("ppri",))
    p = project(maison("D"), hyp, EFFETS, RESID)
    base = project(maison("D"), Hypotheses(), EFFETS, RESID)
    sens = p.sensibilite_risques
    assert sens is not None and sens["statut"] == NON_CAUSAL
    low_b, high_b = sens["avec_voisinage"], sens["sans_voisinage"]
    # borne « avec voisinage » ≈ aucun effet ; « sans voisinage » ≈ −17 %
    assert low_b[1] == pytest.approx(base.prix_m2[1], rel=0.03)
    assert high_b[1] / base.prix_m2[1] == pytest.approx(np.exp(-0.189), rel=0.03)
    # la fourchette publiée couvre les deux bornes, erreur du modèle comprise
    assert p.prix_m2[0] == pytest.approx(min(low_b[0], high_b[0]))
    assert p.prix_m2[2] == pytest.approx(max(low_b[2], high_b[2]))
    assert p.prix_m2[0] < high_b[1] < low_b[1] < p.prix_m2[2]
    assert any(NON_CAUSAL in c for c in p.composantes)
    assert p.as_dict()["sensibilite_risques"]["statut"] == NON_CAUSAL


def test_new_risk_needs_both_bounds() -> None:
    only_low = EffetsPrix(EFFETS.dpe, PARTS, EFFETS.risques_avec_voisinage, {})
    with pytest.raises(KeyError, match="sans voisinage"):
        project(maison("D"), Hypotheses(nouveaux_risques=("ppri",)), only_low, RESID)
    with pytest.raises(KeyError, match="in_tri"):
        project(maison("D"), Hypotheses(nouveaux_risques=("in_tri",)), EFFETS, RESID)


def test_new_risk_already_present_is_rejected() -> None:
    bien = maison("D", risques_actuels=("ppri",))
    with pytest.raises(ValueError, match="déjà"):
        project(bien, Hypotheses(nouveaux_risques=("ppri",)), EFFETS, RESID)
    # un risque actuel n'est jamais appliqué une seconde fois
    same = project(bien, Hypotheses(), EFFETS, RESID)
    assert same.prix_m2 == project(maison("D"), Hypotheses(), EFFETS, RESID).prix_m2


def test_model_error_is_per_property_type() -> None:
    flat = project(Bien(3000.0, 50.0, "Appartement"), Hypotheses(), EFFETS, RESID)
    house = project(Bien(3000.0, 50.0, "Maison"), Hypotheses(), EFFETS, RESID)
    assert flat.prix_m2[2] - flat.prix_m2[0] < 0.5 * (house.prix_m2[2] - house.prix_m2[0])
    only_houses = {"Maison": RESID["Maison"]}
    with pytest.raises(KeyError, match="Appartement"):
        project(Bien(3000.0, 50.0, "Appartement"), Hypotheses(), EFFETS, only_houses)


def test_plot_over_one_hectare_is_refused() -> None:
    assert maison("D", surface_terrain=10_000.0).surface_terrain == 10_000.0
    with pytest.raises(ValueError, match="10 000 m²"):
        maison("D", surface_terrain=10_001.0)
    with pytest.raises(ValueError, match="terrain"):
        maison("D", surface_terrain=-1.0)


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        Bien(0.0, 10.0, "Maison")
    with pytest.raises(ValueError, match="type"):
        Bien(3000.0, 10.0, "Château")
    with pytest.raises(ValueError, match="Risques"):
        maison("D", risques_actuels=("tsunami",))
    with pytest.raises(ValueError):
        Hypotheses(horizon=2020)
    with pytest.raises(ValueError):
        Hypotheses(nouveaux_risques=("tsunami",))
    with pytest.raises(ValueError, match="30 résidus"):
        project(maison(None), Hypotheses(), EFFETS, {"Maison": np.zeros(5)})
    with pytest.raises(ArithmeticError):
        project(maison("D"), Hypotheses(), EXACT, {"Maison": np.zeros(100)})


def test_rcp_scenario_without_drias_fails_explicitly(tmp_path: Path) -> None:
    hyp = Hypotheses(scenario_climat="rcp85")
    with pytest.raises(DriasUnavailableError, match="DRIAS"):
        project(maison("D"), hyp, EFFETS, RESID)
    with pytest.raises(DriasUnavailableError, match="Aucun fichier"):
        project(maison("D"), hyp, EFFETS, RESID, climate=DriasClimate(tmp_path))


def test_drias_reader(tmp_path: Path) -> None:
    clim = DriasClimate(tmp_path)
    with pytest.raises(DriasUnavailableError, match="compte"):
        clim.load("jours_35", "rcp45", "2050")
    with pytest.raises(ValueError):
        clim.path("jours_35", "rcp26", "2050")
    with pytest.raises(ValueError):
        clim.path("jours_35", "rcp45", "2070")
    grid = {"latitude": [44.8, 45.5], "longitude": [-0.6, 0.5], "valeur": [12.0, 30.0]}
    pd.DataFrame(grid).to_parquet(tmp_path / "jours_35_rcp45_2050.parquet")
    assert clim.value_at(-0.58, 44.84, "jours_35", "rcp45", "2050", "valeur") == 12.0
    with pytest.raises(DriasUnavailableError, match="Colonne"):
        clim.value_at(-0.58, 44.84, "jours_35", "rcp45", "2050", "absente")
    pd.DataFrame({"x": [1]}).to_parquet(tmp_path / "jours_35_rcp85_2050.parquet")
    with pytest.raises(DriasUnavailableError, match="colonnes"):
        clim.load("jours_35", "rcp85", "2050")
    # fichiers présents : la relation prix ↔ climat n'est pas estimée → échec explicite
    with pytest.raises(ClimatePriceEffectNotEstimated):
        climate_price_factor(clim, "rcp45", 2050)
    with pytest.raises(DriasUnavailableError):
        climate_price_factor(None, "rcp45", 2050)
