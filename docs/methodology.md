# Méthodologie : estimation du prix et projection 2050

Document de référence de la soutenance (ADR 0003, 0004, 0005). Les chiffres cités
viennent du run décrit dans [ml/report.md](../ml/report.md) (fichier généré depuis
`ml/results.json`) ; ce document décrit la méthode, ses hypothèses et ses limites.

## 1. Ce que fait le modèle de prix

**Question posée :** quel est le prix au m² d'un logement (maison ou appartement) en
Gironde, compte tenu de ses caractéristiques et des ventes antérieures de son voisinage ?

- **Données :** DVF géolocalisées 2021 (second semestre) à 2024, ventes d'un logement
  unique nettoyées en silver (docs/data-contract.md §1). Les maisons avec plus d'un
  hectare de terrain sont exclues du modèle (le prix paie alors surtout le foncier ;
  conséquence pour le rural : §4.8).
- **Cible :** log(prix/m²). Les erreurs sont mesurées en €/m² après retour à l'échelle.
- **Variables :** surface, pièces, terrain, dépendances ; revenu médian et Gini de
  l'IRIS (Filosofi 2021, manquants hors IRIS diffusés) ; exposition au retrait-gonflement
  des argiles de l'IRIS ; commune en TRI, en PPRI ; arrêtés Cat-Nat publiés dans les 10
  ans précédant la vente ; prix de voisinage ; longitude, latitude, mois de vente.
- **Prix de voisinage :** médiane des log-prix des 30 ventes du même type les plus
  récentes dans la cellule H3 r7 de la vente et ses 6 voisines (environ 5 km² chacune),
  lissée vers la médiane départementale. Seules comptent les ventes **strictement
  antérieures** à la date de la vente et appartenant à **l'ensemble d'entraînement** :
  le prix d'une vente ne peut pas entrer dans sa propre variable (tests
  `tests/test_ml_features.py`).
- **Modèles :** baseline Ridge (même jeu de variables, manquants imputés par la médiane
  du train + indicateur) ; LightGBM réglé par Optuna (TPE). Un modèle global avec le
  type en variable, ou un modèle par type : choix fait sur le train ≤ 2023 seul.
- **Validation :** (a) temporelle, apprentissage ≤ 2023, test sur toutes les ventes 2024 ;
  (b) spatiale, GroupKFold à 5 plis par commune : le modèle est évalué sur des communes
  qu'il n'a jamais vues. Optuna est relancé dans chaque pli (validation imbriquée).
- **Porte bloquante :** LightGBM n'est retenu que si sa MAE est inférieure à celle de
  Ridge avec un intervalle de confiance à 95 % entièrement négatif, obtenu par bootstrap
  des communes (2 000 tirages), dans les deux validations.

## 2. Ce que fait la projection 2050

`atlas_pipelines/ml/projection.py`, conformément à l'ADR 0004 :

**valeur projetée = prix estimé aujourd'hui × facteurs**, restituée en fourchette
P10-P50-P90, jamais en chiffre unique (le code refuse une fourchette dégénérée).

| Composante | Source | Statut |
|---|---|---|
| Incertitude du prix actuel | résidus du modèle sur le test 2024 (ventes jamais vues), **du même type de bien** (maison ou appartement) | calculée |
| DPE | écart de prix de la classe **au mix DPE moyen** (β_classe − Σ part·β, β_D = 0), régression hédonique sur les maisons appariées, IC bootstrap par commune | calculée, échantillon biaisé (§4) |
| Loi Climat et résilience | location interdite G 2025, F 2028, E 2034 | statut réglementaire affiché, **pas converti en prix** |
| Nouveaux risques (PPRI, TRI, Cat-Nat ≥ 3, RGA fort) | régression hédonique, toutes ventes, **deux bornes** : avec et sans contrôle du prix de voisinage (§4.1) | **sensibilité, non causal** : seulement en hypothèse, seulement pour un risque que le bien n'a pas déjà ; fourchette couvrant les deux bornes |
| Climat RCP 4.5 / 8.5 | DRIAS | **bloqué** : erreur explicite (§3) |
| Tendance du marché, inflation | — | **non incluse** : euros constants |

**DPE relatif au mix.** Le modèle de prix n'utilise pas le DPE : sa prédiction vaut
pour un bien au mix moyen des classes des ventes, pas pour un bien classé D. Le
facteur appliqué est donc l'écart de la classe visée à ce mix,
β_classe − Σ part_k · β_k, les parts étant celles des maisons appariées. Scénarios :
`statu_quo` (le bien garde sa classe, l'écart observé jusqu'en 2024 persiste) et
`renovation_D` (écart de D au mix, environ −3 % avec les parts actuelles ; le coût des
travaux n'est pas inclus car il n'est pas dans nos données). DPE inconnu : aucun
facteur, le bien reste au mix.

Les risques **actuels** du bien (`Bien.risques_actuels`) sont déjà dans le prix estimé
par le modèle : ils ne sont pas appliqués une seconde fois, et une hypothèse « nouveau
risque » portant sur un risque déjà présent est refusée. Seul un changement
d'exposition déclaré en hypothèse ajoute un facteur, publié comme sensibilité
non causale (§4.1) : la projection est calculée avec chacune des deux bornes, et la
fourchette publiée va du P10 le plus bas au P90 le plus haut (P50 : médiane des deux
simulations réunies) ; les deux fourchettes par borne sont aussi restituées.

Domaine : un terrain de plus de 10 000 m² est refusé avec une erreur explicite, le
modèle n'ayant vu aucune maison de plus d'un hectare.

Tirage : 20 000 simulations ; résidus tirés avec remise ; chaque coefficient tiré dans
une loi normale dont l'écart-type est déduit de son IC bootstrap à 95 % (approximation).

## 3. DRIAS : ce qui manque et comment le module se comporte

DRIAS n'a pas d'API et exige un compte : aucun fichier n'est disponible
(docs/data-contract.md §6). L'interface `atlas_pipelines/ml/climate.py` :
- lit `data/bronze/drias/{indicateur}_{rcp45|rcp85}_{2030|2050}.parquet` quand ils
  existent (point de grille SAFRAN le plus proche) ;
- lève `DriasUnavailableError` si un scénario climatique est demandé sans ces fichiers ;
- lève `ClimatePriceEffectNotEstimated` même quand les fichiers existent, tant que la
  relation entre un indicateur climatique et le prix n'a pas été estimée sur les ventes.

Aucune valeur climatique n'est inventée, interpolée depuis une autre source ou remplacée
par une valeur par défaut. Une projection sans climat le dit dans `non_inclus`.

## 4. Hypothèses et limites

1. **Associations, pas causalité ; les risques sont donnés en deux bornes.** TRI, PPRI
   et Cat-Nat sont mesurés à la commune, RGA à l'IRIS. Deux biais opposés :
   - **avec** le contrôle du prix de voisinage H3 antérieur, l'effet est en partie
     **absorbé** : ce prix est fait des ventes de la même zone, exposées au même risque
     communal ; si le risque fait baisser les prix, la baisse est déjà dans le prix de
     voisinage et le coefficient du risque tend vers 0. C'est la borne basse (en
     valeur absolue) ;
   - **sans** ce contrôle, le coefficient est **confondu** par la localisation : une
     commune en TRI peut être plus chère parce qu'elle est au bord de l'eau ou dans
     l'agglomération, pas « grâce » au risque. C'est la borne haute, dont le signe
     même peut être faux (TRI positif).
   Ordres de grandeur du run (chiffres exacts et IC dans ml/report.md) : PPRI −0,4 %
   avec contrôle contre −17 % sans ; TRI +2,6 % contre +29 % ; RGA fort −0,8 % contre
   −11 %. Aucune des deux n'est un effet causal ; l'effet vrai d'une entrée en PPRI
   n'est pas identifiable avec ces données (il faudrait des dates d'approbation pour
   comparer avant et après). La projection les publie donc comme **sensibilité, non
   causale**, jamais comme effet d'une intervention. Les écarts DPE sont estimés avec
   contrôle de voisinage (le DPE est propre au bien, le voisinage ne l'absorbe pas de
   la même façon).
2. **DPE biaisé.** 7,5 % des ventes 2021-2024 ont un DPE rattaché (94 % de
   maisons), et le rattachement dépend de la qualité de la BAN (parcelles renseignées pour
   43 % des adresses). L'écart par classe est estimé sur ces maisons seulement et ne vaut
   pas pour les appartements. Le modèle de prix n'utilise pas le DPE.
3. **Risques au niveau commune.** TRI, PPRI et Cat-Nat sont communaux, RGA est à l'IRIS :
   aucun n'indique si le bien lui-même est en zone inondable. PPRI et TRI sont l'état
   actuel (GASPAR ne donne pas de date d'effet exploitable) ; Cat-Nat est compté à la
   date de vente.
4. **Statu quo des écarts DPE.** Rien dans des ventes ≤ 2024 ne mesure l'effet des
   interdictions de 2028 et 2034 ; supposer que l'écart s'élargit ou se resserre serait
   une hypothèse non testée. Le calendrier est affiché, pas chiffré.
5. **Pas de tendance de marché.** La projection ne dit pas à quel prix un bien se vendra
   en 2050, mais ce que vaudrait le bien aux prix d'aujourd'hui sous les hypothèses
   posées.
6. **Périmètre.** Gironde seule (13 et 59 non ingérés), 2021 incomplet (second
   semestre), DVF n'inclut pas l'Alsace-Moselle ni Mayotte (sans effet ici).
7. **Erreur de base élevée.** DVF ne décrit ni l'état, ni l'étage, ni la vue, ni les
   travaux : une part importante de la variance du prix n'est pas observable. La MAPE
   publiée dans ml/report.md en donne l'ordre de grandeur, et la fourchette de projection
   en hérite, avec les résidus du type de bien (plus larges pour les maisons).
8. **Exclusion des terrains > 1 ha : surtout rurale.** 1 291 maisons exclues, dont
   91 % dans des communes sans IRIS (moins de ~5 000 habitants). Le modèle couvre donc
   mal le bâti rural à grand terrain ; la projection refuse explicitement un terrain
   de plus de 10 000 m².
9. **Choix des hyperparamètres optimiste (limite connue, non corrigée).** Dans les
   plis internes d'Optuna et dans le choix global / par type, la variable de voisinage
   est calculée une seule fois sur tout l'ensemble d'entraînement, sans être
   recalculée pour chaque pli interne : une vente de validation interne peut avoir
   des voisines dans son propre pli. Les scores de test finaux (temporel et spatial)
   ne sont pas affectés, le voisinage y étant recalculé sur le seul entraînement ;
   seul le choix des hyperparamètres est optimiste. La correction demande un
   réentraînement complet (environ 2 h 20), reporté.

## 5. Ce que le modèle NE dit PAS

- Il ne donne **pas** le prix de vente réel d'un bien ni d'un voisin (ADR 0005 : aucune
  vente individuelle n'est publiée, agrégats d'au moins 5 ventes ou estimation).
- Il ne dit **pas** qu'un bien est ou sera inondé, fissuré ou invendable.
- Il ne prédit **pas** le prix en 2050 (pas de tendance, pas d'inflation, pas de taux).
- Il ne chiffre **pas** l'effet du changement climatique tant que DRIAS manque.
- Il ne chiffre **pas** l'effet de l'interdiction de louer ni le coût d'une rénovation.
- Il n'est **pas** un avis de valeur au sens d'une expertise immobilière.

## 6. Reproduire

```
make gold                                   # gold 2021-2024 (après ingestion + silver)
make model                                  # ml/report.md, ml/results.json, ml/figures/
cd pipelines && python -m atlas_pipelines.ml.rerender --out ../ml
                                            # effets, exemples, rapport sans réentraîner
cd pipelines && pytest                      # dont tests/test_ml_*.py
```
MLflow : serveur du compose (`MLFLOW_TRACKING_URI`) s'il répond, sinon `mlruns/` local.
