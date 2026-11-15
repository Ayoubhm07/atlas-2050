# Sprint 3 — Modèle de prix/m² et projection 2050

**Date :** 2026-11-15 · **Statut :** livré pour la Gironde 2021-2024 ; climat bloqué (DRIAS)

## Livré
- **Modèle** (`pipelines/atlas_pipelines/ml/`) : jeu de modélisation DuckDB (`data.py`,
  Cat-Nat à la date de vente), variables sans fuite dont le prix de voisinage H3
  (`features.py`), baseline Ridge et LightGBM + Optuna (`models.py`), validation
  temporelle et spatiale (`experiment.py`), SHAP sur biens fictifs (`explain.py`),
  MLflow (`tracking.py`), rapport généré (`report.py`).
- **Effets prix** (`effects.py`) : risques en deux bornes (avec / sans contrôle de
  voisinage), DPE par classe, IC bootstrap par commune.
- **Projection 2050** (`projection.py`, `climate.py`) : fourchette P10-P50-P90, DPE
  relatif au mix, nouveaux risques en sensibilité non causale, refus explicites
  (DRIAS absent, terrain > 1 ha, risque déjà présent, effet non estimé).
- **Re-rendu sans réentraînement** : `python -m atlas_pipelines.ml.rerender --out ../ml`
  (recharge `ml/models/lgb_global.txt`, vérifie les résidus du test 2024, recalcule
  effets, exemples et rapport).
- Sorties : [ml/report.md](../../ml/report.md), `ml/results.json`, `ml/figures/` ;
  méthode : [methodology.md](../methodology.md).

## Métriques réelles (ml/results.json)
78 358 ventes, 530 communes ; 1 291 maisons > 1 ha exclues (91 % en commune sans IRIS).

| Validation | Ventes | MAE Ridge | MAE LightGBM | MAPE LightGBM | R² LightGBM | ΔMAE (IC 95 %, bootstrap communes) |
|---|---:|---:|---:|---:|---:|---|
| Temporelle (train ≤ 2023, test 2024) | 17 418 | 794 €/m² | 721 €/m² | 22,3 % | 0,666 | −73 [−88 ; −54] |
| Spatiale (GroupKFold 5 plis, communes) | 78 358 | 958 €/m² | 887 €/m² | 23,7 % | 0,501 | −72 [−136 ; −29] |

Porte bloquante : **passée** dans les deux validations. MAPE temporelle : appartements
16,9 %, maisons 26,3 % ; communes à IRIS 19,3 %, sans IRIS 28,5 %.

Effets des risques, bornes avec / sans contrôle de voisinage (IC 95 %) :

| Risque | Avec voisinage | Sans voisinage |
|---|---|---|
| PPRI | −0,4 % [−3,3 ; +2,0] | −17,2 % [−26,7 ; −6,3] |
| TRI | +2,6 % [−0,0 ; +5,9] | +28,8 % [+15,8 ; +47,8] |
| Cat-Nat ≥ 3 en 10 ans | +0,8 % [−0,7 ; +2,6] | +3,3 % [−7,5 ; +17,4] |
| RGA fort | −0,8 % [−2,1 ; +0,9] | −11,4 % [−15,0 ; −5,8] |

DPE (5 536 maisons appariées, D = référence) : A +23,2 %, G −22,1 %. Rénover en D :
−3,2 % par rapport au prix estimé (mix DPE moyen).

Exemple (maison fictive hors PPRI, 96 m², 3 725 €/m², supposée G), €/m² P10-P50-P90 :
statu quo 1 874 / 2 850 / 3 924 ; rénovée en D 2 424 / 3 658 / 4 990 ; si la commune
entrait en PPRI (sensibilité, non causal) 1 539 / 2 581 / 3 909 (borne avec voisinage
1 866-3 909, sans voisinage 1 539-3 287) ; RCP 8.5 : refus explicite.

## Décisions
| Sujet | Décision | Pourquoi |
|---|---|---|
| Stratégie | modèle global (type en variable) | MAE GroupKFold sur le train : 848 contre 867 €/m² par type |
| Effets des risques | deux bornes publiées, chacune avec IC bootstrap par commune | le voisinage absorbe un risque communal ; sans lui, confusion par le lieu |
| Nouveau risque en projection | sensibilité non causale, fourchette couvrant les deux bornes | aucun effet d'intervention identifiable sans date d'approbation des PPRI |
| DPE en projection | écart au mix (β_classe − Σ part·β) | le modèle ne voit pas le DPE : il prédit le mix, pas D |
| Erreur du modèle | résidus du test 2024 par type | maisons nettement plus dispersées que les appartements |
| Terrains > 1 ha | exclus et refusés par la projection | prix du foncier ; exclusion à 91 % rurale, documentée |

## Revue adverse ML (2026-11-15)
Revue indépendante ; correctifs test d'abord, sans réentraîner le modèle.

| # | Gravité | Défaut | Correctif | Preuve |
|---|---|---|---|---|
| M1 | MAJEURE | effets des risques estimés avec le voisinage (qui les absorbe) puis appliqués comme effets d'intervention | deux bornes (avec / sans voisinage), projection en sensibilité non causale couvrant les deux | PPRI −0,4 % contre −17,2 % ; `test_risk_bounds_with_and_without_neighbourhood_control`, `test_new_risk_is_a_sensitivity_range_spanning_both_bounds` |
| m1 | MINEURE | `Bien` sans risques actuels ; l'exemple ajoutait un PPRI à une maison déjà en PPRI | `Bien.risques_actuels`, refus d'un nouveau risque déjà présent ; exemple sur une maison hors PPRI | `test_new_risk_already_present_is_rejected` |
| m2 | MINEURE | DPE appliqué par rapport à D alors que la prédiction vaut pour le mix | β_classe − Σ part·β | rénovation en D : 0 → −3,2 % ; `test_dpe_offset_is_relative_to_the_sales_mix` |
| m3 | MINEURE | quantiles d'erreur communs à tous les types | résidus par type, recalculés avec le modèle rechargé | P10/P90 maisons −32 % / +38 %, appartements −23 % / +27 % ; quantiles globaux reproduits à 0,0 près ; `test_model_error_is_per_property_type` |
| m4 | MINEURE | voisinage non recalculé dans les plis internes d'Optuna et le choix de stratégie | documenté (report.md, methodology §4.9), non corrigé | scores de test non affectés ; seul le choix des hyperparamètres est optimiste |
| m5 | MINEURE | exclusion > 1 ha surtout rurale, non dite ; projection acceptait un grand terrain | §4.8 ; refus explicite > 10 000 m² | 1 173 / 1 291 exclues sans IRIS ; `test_plot_over_one_hectare_is_refused` |
| — | BASSE | docstring `models.py` : 10,7 % de DPE rattachés | 7,5 % (5 905 / 78 358) | results.json |

## Reste ouvert
- **DRIAS** : aucun fichier ; tout scénario RCP échoue explicitement.
- **Départements 13 et 59** à ingérer avant d'étendre le modèle.
- **m4** : recalculer le voisinage dans chaque pli interne puis réentraîner (~2 h 20).
- Effet causal d'une entrée en PPRI : demande des dates d'approbation (absentes de GASPAR).
- Les écarts DPE, estimés sur les maisons, sont aussi appliqués à un appartement si un
  DPE est fourni : à restreindre ou à documenter.
