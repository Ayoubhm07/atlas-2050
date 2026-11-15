# Modèle de prix/m² — rapport du sprint 3

Entraîné le 2026-11-15 par `python -m atlas_pipelines.ml.train` ; tous les chiffres
viennent de [results.json](results.json) (aucune saisie manuelle). Suivi MLflow :
`mlruns/ local, expérience atlas-prix-m2, run b283e02b0ce5468699192c5e0c76b735`.
Effets, erreurs par type, exemples et rapport recalculés le 2026-11-15 par `python -m atlas_pipelines.ml.rerender`, **sans réentraînement** (modèle rechargé, résidus du test 2024 vérifiés identiques).

## Données
- Gironde (33), DVF 2021-2024 (2021 = second semestre seulement),
  78 358 ventes de logements, 530 communes, après
  exclusion de 1 291 maisons avec plus d'un hectare de terrain (le prix y paie
  surtout le foncier, data-contract §1). 91 % d'entre
  elles (1 173) sont dans des communes sans IRIS : l'exclusion retire surtout
  du rural, et la projection refuse un terrain de plus de 10 000 m².
- Cible : log(prix/m²). Métriques après retour en €/m².
- Variables : surface (log), pièces, terrain (log), dépendances, revenu médian et Gini
  de l'IRIS (manquants hors IRIS diffusés), exposition RGA, TRI, PPRI, arrêtés Cat-Nat
  des 10 ans avant la vente, prix de voisinage H3 (voir ci-dessous), longitude,
  latitude, mois. Le DPE n'est pas une variable : 7,5 %
  des ventes seulement ont un DPE rattaché, dont 93,8 %
  de maisons.
- **Voisinage sans fuite** : médiane lissée du log-prix des 30 ventes du même type les
  plus récentes de l'anneau H3 r7, **strictement antérieures** à la vente et prises
  dans le **seul ensemble d'entraînement** du pli.
- Longitude/latitude : gardées, car elles donnent au modèle la position d'une commune
  jamais vue quand l'anneau H3 n'a pas de vente antérieure ; elles ne contiennent aucun prix.

## Protocole
- **Temporel** : entraînement ≤ 2023 (60 940 ventes), test 2024
  (17 418 ventes). Optuna (30 essais, GroupKFold 3 plis par
  commune sur le train seul).
- **Spatial** : GroupKFold 5 plis par commune sur toutes les années ; Optuna
  (12 essais) refait dans chaque pli d'entraînement (validation imbriquée).
- **Limite connue (hyperparamètres)** : dans les plis internes d'Optuna et dans le choix
  global / par type, la variable de voisinage est calculée une fois sur tout l'ensemble
  d'entraînement, sans être recalculée par pli interne. Les scores de test finaux n'en
  sont pas affectés (voisinage recalculé sur le seul train) ; seul le choix des
  hyperparamètres est optimiste. Correction (réentraînement) reportée.
- **Un modèle global ou un par type ?** MAE GroupKFold sur le train ≤ 2023, paramètres
  par défaut : global 848 €/m², par type 867
  €/m² → **global**.
- Zones : « commune à IRIS » (≥ ~5 000 habitants, découpée par l'INSEE) contre
  « commune sans IRIS » ; c'est une approximation urbain/rural, pas la grille de densité.

## Résultats
### Test temporel (2024)
| Groupe | Ventes | MAE Ridge | MAE LightGBM | MAPE Ridge | MAPE LightGBM | R² Ridge | R² LightGBM |
|---|---:|---:|---:|---:|---:|---:|---:|
| Toutes | 17 418 | 794 | 721 | 24,8 % | 22,3 % | 0,623 | 0,666 |
| Appartement | 7 382 | 728 | 635 | 18,9 % | 16,9 % | 0,579 | 0,668 |
| Maison | 10 036 | 843 | 784 | 29,1 % | 26,3 % | 0,633 | 0,663 |
| commune sans IRIS | 5 658 | 627 | 584 | 32,1 % | 28,5 % | 0,596 | 0,636 |
| commune à IRIS | 11 760 | 875 | 787 | 21,2 % | 19,3 % | 0,580 | 0,628 |

### Validation spatiale (communes jamais vues)
| Groupe | Ventes | MAE Ridge | MAE LightGBM | MAPE Ridge | MAPE LightGBM | R² Ridge | R² LightGBM |
|---|---:|---:|---:|---:|---:|---:|---:|
| Toutes | 78 358 | 958 | 887 | 26,9 % | 23,7 % | 0,420 | 0,501 |
| Appartement | 32 161 | 892 | 859 | 21,6 % | 19,6 % | 0,391 | 0,388 |
| Maison | 46 197 | 1 005 | 907 | 30,5 % | 26,6 % | 0,425 | 0,528 |
| commune sans IRIS | 25 796 | 751 | 658 | 36,0 % | 29,8 % | 0,399 | 0,507 |
| commune à IRIS | 52 562 | 1 060 | 1 000 | 22,4 % | 20,8 % | 0,329 | 0,419 |

![MAE](figures/mae_baseline_vs_lgb.png)
![MAPE temporel](figures/mape_groupes_temporel.png)
![MAPE spatial](figures/mape_groupes_spatial.png)
![Calibration](figures/calibration_test_2024.png)

## Porte bloquante : PASSÉE
Différence de MAE LightGBM − Ridge, bootstrap par commune (paire) :
- temporel : −73 €/m² (−9,2 %), IC 95 % [−88 ; −54] (2 000 tirages, 486 communes) : **significatif**
- spatial : −72 €/m² (−7,5 %), IC 95 % [−136 ; −29] (2 000 tirages, 530 communes) : **significatif**

![Bootstrap](figures/mae_diff_bootstrap.png)

## Explications SHAP
Importance globale (moyenne |SHAP| en log-prix, 3 000 ventes de test tirées au hasard) :
`voisinage_log_prix` 0,172, `log_terrain` 0,102, `log_surface` 0,092, `lon` 0,073, `gini` 0,063, `lat` 0,051, `revenu_median` 0,047, `t_mois` 0,037.

![SHAP global](figures/shap_global.png)

Exemples locaux sur des **biens fictifs** (aucune vente réelle, ADR 0005) :
- **Maison fictive** (surface 94 m², 4 pièces ; chaque variable = médiane des ventes maison du test) : base 3 480 €/m² → prédiction 3 841 €/m². Principales contributions : `log_terrain` 10,5 %, `lat` 5,6 %, `t_mois` −4,0 %, `log_surface` −3,5 %, `lon` 3,4 %.
- **Appartement fictif** (surface 50 m², 2 pièces ; chaque variable = médiane des ventes appartement du test) : base 3 480 €/m² → prédiction 3 659 €/m². Principales contributions : `log_terrain` −11,5 %, `log_surface` 5,7 %, `lat` 5,0 %, `t_mois` −3,8 %, `revenu_median` 3,4 %.

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

| Terme | Écart central | IC 95 % | Ventes | Communes |
|---|---:|---:|---:|---:|
| `ppri` | −0,4 % | [−3,3 % ; 2,0 %] | 78 229 | 530 |
| `in_tri` | 2,6 % | [−0,0 % ; 5,9 %] | 78 229 | 530 |
| `catnat_3plus` | 0,8 % | [−0,7 % ; 2,6 %] | 78 229 | 530 |
| `rga_forte` | −0,8 % | [−2,1 % ; 0,9 %] | 78 229 | 530 |

**Sans contrôle de voisinage** (borne haute). Le coefficient mêle l'effet du risque et
tout ce qui distingue les communes exposées (bord de l'eau, centre urbain, etc.) : il
est confondu par la localisation, au point de changer de signe pour le TRI.

| Terme | Écart central | IC 95 % | Ventes | Communes |
|---|---:|---:|---:|---:|
| `ppri` | −17,2 % | [−26,7 % ; −6,3 %] | 78 229 | 530 |
| `in_tri` | 28,8 % | [15,8 % ; 47,8 %] | 78 229 | 530 |
| `catnat_3plus` | 3,3 % | [−7,5 % ; 17,4 %] | 78 229 | 530 |
| `rga_forte` | −11,4 % | [−15,0 % ; −5,8 %] | 78 229 | 530 |

DPE, classe D en référence, avec contrôle de voisinage
(5 536 maisons appariées sur 5 905
ventes appariées, échantillon non représentatif) :

| Terme | Écart central | IC 95 % | Ventes | Communes |
|---|---:|---:|---:|---:|
| `dpe_A` | 23,2 % | [19,3 % ; 27,4 %] | 5 536 | 250 |
| `dpe_B` | 16,8 % | [13,5 % ; 20,7 %] | 5 536 | 250 |
| `dpe_C` | 9,7 % | [7,1 % ; 11,9 %] | 5 536 | 250 |
| `dpe_E` | −10,0 % | [−13,4 % ; −6,4 %] | 5 536 | 250 |
| `dpe_F` | −16,0 % | [−21,2 % ; −10,0 %] | 5 536 | 250 |
| `dpe_G` | −22,1 % | [−31,1 % ; −12,6 %] | 5 536 | 250 |

Répartition des classes de ces maisons : A 8,1 %, B 7,6 %, C 35,6 %, D 27,9 %, E 13,3 %, F 5,1 %, G 2,4 %. Le modèle de prix n'utilisant
pas le DPE, sa prédiction correspond à ce mix : la projection applique
β_classe − Σ part·β. Rénover en D vaut ainsi −3,2 % par
rapport au prix estimé (point central), et non 0.

![Effets](figures/effets_risques_dpe.png)

## Exemple de projection 2050
**Bien fictif** : maison « type », médianes des maisons du test 2024 situées dans des communes **sans PPRI** ; 96 m², terrain 762 m², prix estimé 3 725 €/m² ; risques actuels : `rga_forte`. Supposée en classe G.

Euros constants, sans tendance de marché ; méthode : docs/methodology.md. Erreur du
modèle tirée dans les résidus du test 2024 **du même type de bien** (P10 / P90 :
appartements −23,1 % / +26,5 % ; maisons −32,2 % / +38,3 %). L'hypothèse de nouveau risque est une **sensibilité, non
causale** : la fourchette publiée va du P10 le plus bas au P90 le plus haut des deux
bornes.

| Hypothèse | €/m² P10 | P50 | P90 | Bornes du risque (€/m²) | Location interdite depuis | Non inclus |
|---|---:|---:|---:|---|---:|---|
| G, statu quo, 2050 | 1 874 | 2 850 | 3 924 | — | 2025 | tendance du marché (euros constants) ; climat RCP 4.5 / 8.5 (DRIAS non disponible) |
| G rénovée en D, 2050 | 2 424 | 3 658 | 4 990 | — | 2025 | tendance du marché (euros constants) ; climat RCP 4.5 / 8.5 (DRIAS non disponible) ; coût de la rénovation |
| G, statu quo, si la commune entrait en PPRI (sensibilité, non causal) | 1 539 | 2 581 | 3 909 | sensibilité, non causal : avec voisinage 1 866 à 3 909 (P50 2 840) ; sans voisinage 1 539 à 3 287 (P50 2 357) | 2025 | tendance du marché (euros constants) ; climat RCP 4.5 / 8.5 (DRIAS non disponible) |
| G, statu quo, RCP 8.5 | refus explicite : Scénario rcp85 2050 demandé sans données DRIAS (accès bloqué : compte requis). La projection climatique n'est pas calcul… | | | | | |

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
