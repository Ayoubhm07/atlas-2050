"""Rendu de ml/report.md depuis results.json : chaque chiffre vient du run."""

from __future__ import annotations

import math
from typing import Any


def _fr(x: float, nd: int = 0) -> str:
    s = f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")
    return s.replace("-", "−")


def _pct(x: float, nd: int = 1) -> str:
    return _fr(100 * x, nd) + " %"


def _score_rows(ev: dict[str, Any]) -> list[str]:
    rows = []
    groups: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("Toutes", ev["ridge"]["tous"], ev["lgb"]["tous"])
    ]
    for grp in ("par_type", "par_urbain"):
        for k in ev["lgb"][grp]:
            groups.append((k, ev["ridge"][grp][k], ev["lgb"][grp][k]))
    for name, r, g in groups:
        rows.append(
            f"| {name} | {_fr(g['n'])} | {_fr(r['mae'])} | {_fr(g['mae'])} | "
            f"{_pct(r['mape'])} | {_pct(g['mape'])} | {_fr(r['r2'], 3)} | {_fr(g['r2'], 3)} |"
        )
    return rows


def _scores_table(ev: dict[str, Any]) -> str:
    head = [
        "| Groupe | Ventes | MAE Ridge | MAE LightGBM | MAPE Ridge | MAPE LightGBM "
        "| R² Ridge | R² LightGBM |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    return "\n".join(head + _score_rows(ev))


def _diff(d: dict[str, Any]) -> str:
    return (
        f"{_fr(d['diff'])} €/m² ({_pct(d['rel_diff'])}), IC 95 % [{_fr(d['low'])} ; "
        f"{_fr(d['high'])}] ({_fr(d['n_boot'])} tirages, {_fr(d['n_groups'])} communes) : "
        + ("**significatif**" if d["significatif"] else "**NON significatif**")
    )


def _effects_table(effects: list[dict[str, Any]]) -> str:
    rows = [
        "| Terme | Écart central | IC 95 % | Ventes | Communes |",
        "|---|---:|---:|---:|---:|",
    ]
    for e in effects:
        rows.append(
            f"| `{e['term']}` | {_pct(e['factor'] - 1)} | [{_pct(e['factor_low'] - 1)} ; "
            f"{_pct(e['factor_high'] - 1)}] | {_fr(e['n_obs'])} | {_fr(e['n_groups'])} |"
        )
    return "\n".join(rows)


def _local(te: dict[str, Any]) -> str:
    out = []
    for typ, loc in te["shap_local"].items():
        b = loc["bien"]
        top = list(loc["contributions"].items())[:5]
        contrib = ", ".join(f"`{k}` {_pct(math.exp(v) - 1)}" for k, v in top)
        genre = "fictive" if typ == "Maison" else "fictif"
        out.append(
            f"- **{typ} {genre}** (surface {_fr(math.exp(b['log_surface']))} m², "
            f"{_fr(b['pieces'])} pièces ; chaque variable = médiane des ventes {typ.lower()} du "
            f"test) : base {_fr(loc['base_m2'])} €/m² → prédiction "
            f"{_fr(loc['prediction_m2'])} €/m². Principales contributions : {contrib}."
        )
    return "\n".join(out)


def _sensitivity(c: dict[str, Any]) -> str:
    sens = c.get("sensibilite_risques")
    if not sens:
        return "—"
    a, b = sens["avec_voisinage"], sens["sans_voisinage"]
    return (
        f"{sens['statut']} : avec voisinage {_fr(a[0])} à {_fr(a[2])} (P50 {_fr(a[1])}) ; "
        f"sans voisinage {_fr(b[0])} à {_fr(b[2])} (P50 {_fr(b[1])})"
    )


def _projections(cases: list[dict[str, Any]]) -> str:
    rows = [
        "| Hypothèse | €/m² P10 | P50 | P90 | Bornes du risque (€/m²) | Location interdite "
        "depuis | Non inclus |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for c in cases:
        if "erreur" in c:
            rows.append(f"| {c['cas']} | refus explicite : {c['erreur'][:120]}… | | | | | |")
            continue
        p10, p50, p90 = c["prix_m2_p10_p50_p90"]
        ban = c["location_interdite_depuis"] or "—"
        rows.append(
            f"| {c['cas']} | {_fr(p10)} | {_fr(p50)} | {_fr(p90)} | {_sensitivity(c)} | {ban} | "
            f"{' ; '.join(c['non_inclus'])} |"
        )
    return "\n".join(rows)


def _example(te: dict[str, Any]) -> str:
    ex = te["bien_exemple"]
    risks = ", ".join(f"`{r}`" for r in ex["risques_actuels"]) or "aucun"
    return (
        "**Bien fictif** : maison « type », médianes des maisons du test 2024 situées dans "
        f"des communes **sans PPRI** ; {_fr(ex['surface'])} m², terrain "
        f"{_fr(ex['surface_terrain'])} m², prix estimé {_fr(ex['prediction_m2'])} €/m² ; "
        f"risques actuels : {risks}. Supposée en classe G."
    )


def _mix_offset(ef: dict[str, Any]) -> float:
    betas = {str(e["term"])[4:]: float(e["coef"]) for e in ef["dpe"]}
    return -float(sum(share * betas.get(c, 0.0) for c, share in ef["parts_dpe"].items()))


def _shares(ef: dict[str, Any]) -> str:
    return ", ".join(f"{c} {_pct(v)}" for c, v in ef["parts_dpe"].items())


def _residual_spread(te: dict[str, Any]) -> str:
    out = []
    for typ, q in te["residus_quantiles_par_type"].items():
        p10, p90 = q[20], q[180]
        out.append(f"{typ.lower()}s {_pct(math.exp(p10) - 1)} / +{_pct(math.exp(p90) - 1)}")
    return " ; ".join(out)


def render(res: dict[str, Any]) -> str:
    m, te, sp, ef = res["meta"], res["temporel"], res["spatial"], res["effets"]
    shap_top = list(te["shap_global"].items())[:8]
    porte = "PASSÉE" if res["porte"]["passe"] else "ÉCHOUÉE (bloquant)"
    choice = m["choix_strategie_mae"]
    part_dpe = _pct(ef["n_dpe_apparies"] / m["n_ventes"])
    part_maisons = _pct(ef["n_dpe_apparies_maisons"] / max(ef["n_dpe_apparies"], 1))
    rr = m.get("rerendu")
    rerendu = (
        f"\nEffets, erreurs par type, exemples et rapport recalculés le {rr['date']} par "
        "`python -m atlas_pipelines.ml.rerender`, **sans réentraînement** (modèle rechargé, "
        "résidus du test 2024 vérifiés identiques)."
        if rr
        else ""
    )
    n_excl = m.get("n_exclues_terrain", 0)
    n_rural = m.get("n_exclues_terrain_sans_iris", 0)
    return f"""# Modèle de prix/m² — rapport du sprint 3

Entraîné le {m["date"]} par `python -m atlas_pipelines.ml.train` ; tous les chiffres
viennent de [results.json](results.json) (aucune saisie manuelle). Suivi MLflow :
`{m.get("mlflow", "non journalisé")}`.{rerendu}

## Données
- Gironde (33), DVF {m["annees"][0]}-{m["annees"][-1]} (2021 = second semestre seulement),
  {_fr(m["n_ventes"])} ventes de logements, {_fr(m["n_communes"])} communes, après
  exclusion de {_fr(n_excl)} maisons avec plus d'un hectare de terrain (le prix y paie
  surtout le foncier, data-contract §1). {_pct(n_rural / max(n_excl, 1), 0)} d'entre
  elles ({_fr(n_rural)}) sont dans des communes sans IRIS : l'exclusion retire surtout
  du rural, et la projection refuse un terrain de plus de 10 000 m².
- Cible : log(prix/m²). Métriques après retour en €/m².
- Variables : surface (log), pièces, terrain (log), dépendances, revenu médian et Gini
  de l'IRIS (manquants hors IRIS diffusés), exposition RGA, TRI, PPRI, arrêtés Cat-Nat
  des 10 ans avant la vente, prix de voisinage H3 (voir ci-dessous), longitude,
  latitude, mois. Le DPE n'est pas une variable : {part_dpe}
  des ventes seulement ont un DPE rattaché, dont {part_maisons}
  de maisons.
- **Voisinage sans fuite** : médiane lissée du log-prix des 30 ventes du même type les
  plus récentes de l'anneau H3 r7, **strictement antérieures** à la vente et prises
  dans le **seul ensemble d'entraînement** du pli.
- Longitude/latitude : gardées, car elles donnent au modèle la position d'une commune
  jamais vue quand l'anneau H3 n'a pas de vente antérieure ; elles ne contiennent aucun prix.

## Protocole
- **Temporel** : entraînement ≤ 2023 ({_fr(te["n_train"])} ventes), test 2024
  ({_fr(te["n_test"])} ventes). Optuna ({m["trials"]} essais, GroupKFold 3 plis par
  commune sur le train seul).
- **Spatial** : GroupKFold {m["folds"]} plis par commune sur toutes les années ; Optuna
  ({m["cv_trials"]} essais) refait dans chaque pli d'entraînement (validation imbriquée).
- **Limite connue (hyperparamètres)** : dans les plis internes d'Optuna et dans le choix
  global / par type, la variable de voisinage est calculée une fois sur tout l'ensemble
  d'entraînement, sans être recalculée par pli interne. Les scores de test finaux n'en
  sont pas affectés (voisinage recalculé sur le seul train) ; seul le choix des
  hyperparamètres est optimiste. Correction (réentraînement) reportée.
- **Un modèle global ou un par type ?** MAE GroupKFold sur le train ≤ 2023, paramètres
  par défaut : global {_fr(choice["global"])} €/m², par type {_fr(choice["par_type"])}
  €/m² → **{m["strategie"]}**.
- Zones : « commune à IRIS » (≥ ~5 000 habitants, découpée par l'INSEE) contre
  « commune sans IRIS » ; c'est une approximation urbain/rural, pas la grille de densité.

## Résultats
### Test temporel (2024)
{_scores_table(te)}

### Validation spatiale (communes jamais vues)
{_scores_table(sp)}

![MAE](figures/mae_baseline_vs_lgb.png)
![MAPE temporel](figures/mape_groupes_temporel.png)
![MAPE spatial](figures/mape_groupes_spatial.png)
![Calibration](figures/calibration_test_2024.png)

## Porte bloquante : {porte}
Différence de MAE LightGBM − Ridge, bootstrap par commune (paire) :
- temporel : {_diff(te["diff"])}
- spatial : {_diff(sp["diff"])}

![Bootstrap](figures/mae_diff_bootstrap.png)

## Explications SHAP
Importance globale (moyenne |SHAP| en log-prix, 3 000 ventes de test tirées au hasard) :
{", ".join(f"`{k}` {_fr(v, 3)}" for k, v in shap_top)}.

![SHAP global](figures/shap_global.png)

Exemples locaux sur des **biens fictifs** (aucune vente réelle, ADR 0005) :
{_local(te)}

![SHAP maison](figures/shap_local_maison_fictif.png)
![SHAP appartement](figures/shap_local_appartement_fictif.png)

## Effets prix des risques et du DPE (entrée de la projection 2050)
Régression hédonique sur log(prix/m²), contrôles : surface, pièces, terrain, type,
année, revenu et Gini IRIS, avec ou sans le prix de voisinage H3 antérieur. IC
bootstrap par commune. Ce sont des **associations**, pas des effets causaux.

Risques (ventes ayant un prix de voisinage), publiés comme **deux bornes** :

**Avec contrôle de voisinage** (borne basse en valeur absolue). Les risques sont
communaux et le prix de voisinage est fait des ventes de la même zone, exposées aux
mêmes risques : il absorbe une partie de l'effet.

{_effects_table(ef["risques_avec_voisinage"])}

**Sans contrôle de voisinage** (borne haute). Le coefficient mêle l'effet du risque et
tout ce qui distingue les communes exposées (bord de l'eau, centre urbain, etc.) : il
est confondu par la localisation, au point de changer de signe pour le TRI.

{_effects_table(ef["risques_sans_voisinage"])}

DPE, classe D en référence, avec contrôle de voisinage
({_fr(ef["n_dpe_apparies_maisons"])} maisons appariées sur {_fr(ef["n_dpe_apparies"])}
ventes appariées, échantillon non représentatif) :

{_effects_table(ef["dpe"])}

Répartition des classes de ces maisons : {_shares(ef)}. Le modèle de prix n'utilisant
pas le DPE, sa prédiction correspond à ce mix : la projection applique
β_classe − Σ part·β. Rénover en D vaut ainsi {_pct(math.exp(_mix_offset(ef)) - 1)} par
rapport au prix estimé (point central), et non 0.

![Effets](figures/effets_risques_dpe.png)

## Exemple de projection 2050
{_example(te)}

Euros constants, sans tendance de marché ; méthode : docs/methodology.md. Erreur du
modèle tirée dans les résidus du test 2024 **du même type de bien** (P10 / P90 :
{_residual_spread(te)}). L'hypothèse de nouveau risque est une **sensibilité, non
causale** : la fourchette publiée va du P10 le plus bas au P90 le plus haut des deux
bornes.

{_projections(res.get("projection_exemples", []))}

## Limites
- Gironde seule ; les départements 13 et 59 ne sont pas encore ingérés.
- Le gold a été reconstruit sur 2021-2024 : les bornes d'outliers (IQR par commune et
  type) portent maintenant sur 4 ans, d'où un léger écart avec les effectifs 2024 du
  sprint 2.
- PPRI et TRI sont l'état actuel (GASPAR ne donne pas de date d'effet exploitable) :
  pour une vente de 2021, un PPRI approuvé ensuite est une information future.
- Les ventes d'une même commune restent corrélées ; les IC par commune en tiennent
  compte, pas la corrélation entre communes voisines.
- Hyperparamètres choisis avec un voisinage non recalculé dans les plis internes
  (voir Protocole) : choix optimiste, scores de test non affectés.
- Méthode et usage de la projection : [docs/methodology.md](../docs/methodology.md).
"""
