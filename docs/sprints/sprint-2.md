# Sprint 2 — Gold (dbt-duckdb) et service PostGIS

**Date :** 2026-11-15 · **Statut :** livré pour la Gironde 2024, `fact_climat` bloqué (DRIAS)

## Livré
- **Bronze** : `sources/iris.py` (Contours IRIS IGN 2026, 7z → GPKG → Parquet WKB),
  `sources/ppr.py` (Géorisques `gaspar/pprn`), `sources/rga.py` (RGA au point intérieur
  de chaque IRIS). CLI : `python -m atlas_pipelines.cli iris ppr rga`.
- **Silver DuckDB** (`silver/ban.py`, `silver/dpe.py`, `silver/georisques.py`,
  `python -m atlas_pipelines.silver.run_duck ban dpe georisques`). DVF reste en PySpark.
- **Gold dbt-duckdb** (`dbt/`) : `dim_commune`, `dim_iris`, `fact_transactions`,
  `fact_risques_commune`, `agg_hex` ; extensions DuckDB `spatial` et `h3` ; 35 tests
  (unique, not_null, relationships, accepted_values + anti-fuite DPE, différenciation
  ADR 0005, emprise, comptes silver = gold).
- **PostGIS** : `python -m atlas_pipelines.load.postgis` (psycopg 3, COPY, tables
  `__new` puis bascule atomique, GIST + btree) ; 5 requêtes API dans
  `docs/sql/api_queries.sql`, mesurées par `docs/sql/explain_api_queries.py`.
- **Airflow** : `dags/atlas_gold.py` (silver BAN / DPE / Géorisques, puis gold :
  dbt build → chargement), chaîné par Datasets ; `iris`, `ppr`, `rga` ajoutés aux DAGs
  d'ingestion. Image : dbt dans un venv dédié `/opt/dbt-venv`.

Chiffres réels : [quality/gold_33_2024.md](../quality/gold_33_2024.md).

## Décisions
| Sujet | Décision | Pourquoi |
|---|---|---|
| Édition IRIS | 2026-01-01 | 339/339 codes Filosofi 2021 retrouvés en Gironde |
| Extraction 7z | seul le `.gpkg`, vers un nom fixé par nous | chemins IGN > 260 car. sous Windows ; pas de traversée |
| PPRI | `modeleProcedure` ∈ {PPRN-I, PPRN-L} | seules valeurs inondation observées (225 + 10) |
| AZI | oui / non / inconnu, « non » seulement si le département a des AZI | Gironde sans aucun AZI : vide ≠ pas de risque |
| DPE ↔ vente | rattaché seulement si un DPE unique, du même type de bien ; appartement : adresse à un seul DPE | le plus récent d'un immeuble n'est pas celui du lot vendu |
| H3 | extension DuckDB `h3` (communautaire) ; texte en PostGIS | `h3-pg` absent de l'image postgis 16-3.4 |
| Carte hexagones | table `agg_hex` pré-agrégée (≥ 5 ventes, suppression secondaire) | calcul à la volée 198–402 ms, `agg_hex` 1,1 à 5,7 ms ; pas de fenêtre de dates libre (ADR 0005) |
| dbt | venv séparé, dbt-core 1.10 / dbt-duckdb 1.9.6 | dbt-core 2.x télécharge un binaire GitHub (échec SSL) ; 1.10 épingle pathspec < 0.13, incompatible avec mypy |

## Reste ouvert
- **DPE** : 10,8 % des ventes seulement ; cause : `cad_parcelles` vide pour 57 % des
  adresses BAN. Piste : repli spatial DPE ↔ parcelle cadastrale (sprint 3).
- Secret statistique : différenciation à plusieurs cellules (44 totaux) et entre
  résolutions r7/r9 non traitée (voir quality/gold_33_2024.md).
- **fact_climat** : bloqué tant que les fichiers DRIAS ne sont pas déposés.
- Départements 13 et 59 à ingérer ; mesures de temps à refaire sur une machine au repos.

## Revue adverse (2026-11-15)
Revue indépendante ; défauts reproduits puis corrigés, test d'abord (avant → après).

| # | Gravité | Défaut | Correctif | Preuve |
|---|---|---|---|---|
| 1 | HAUTE | DPE le plus récent rattaché quelle que soit sa date : 174 ventes avec `dpe_date > date_mutation` | silver garde l'historique ; gold : DPE ≤ date de vente, le plus récent, unicité évaluée à cette date | test dbt `fact_transactions_dpe_anterieur_vente` : 174 → 0 ; appariés 1 926 → 1 905 |
| 2 | HAUTE | `hex_aggregates_brut` (fenêtre de dates libre) ; quartiles dès 5 ventes ; prix exacts | requête retirée ; médiane ≥ 5, quartiles ≥ 11 ventes ; arrondi 10 €/m² (API et `agg_hex`) | 0 quartile sur les 136 groupes < 11 ventes ; 0 prix non arrondi |
| 3 | MOYENNE | `agg_hex` : total − sous-groupe de 1 à 4 ventes | suppression secondaire dans dbt (sous-groupe retiré) | test `agg_hex_pas_de_differenciation` : 4 872 paires → 0 ; 2 312 lignes retirées |
| 4 | MOYENNE | collation « C » sur tout le texte : `lower('Étauliers')` inopérant | « C » sur les codes seulement ; `nom_recherche` (dbt) indexé | « étau » et « Étau » → Étauliers |
| 5 | MOYENNE | dbt écrit `data/gold` avant ses tests | build dans `data/gold_build`, promotion tout-ou-rien après succès (`load/promote.py`, Makefile, DAG) | `tests/test_promote.py` (8 cas, dont retour arrière) |
| 6 | BASSE | tests qui ne peuvent pas échouer (seuil 5 ventes, relation `code_iris`, `accepted_values` DPE) | remplacés : nb lignes = silver DVF, emprise du département, `not_null type_local`, tests 1 et 3 | test d'emprise : 17 766 échecs si lon/lat inversés |
| 7 | BASSE | `atlas_gold` sans IRIS/INSEE ; URI Postgres mal formée | datasets bronze iris et insee ajoutés ; `postgres://db:5432/atlas/gold/fact_transactions` | DAG importé dans l'image Airflow 2.10.3 sans avertissement |
| 8 | BASSE | `.part` IRIS laissé en cas d'échec ; départements vides acceptés ; `point_lookup` non déterministe | nettoyage du `.part`, `ValueError` ; `ORDER BY code_iris` | 2 tests pytest |

## Analyse exploratoire
[analysis/eda.ipynb](../analysis/eda.ipynb), exécuté sur le gold Gironde 2024 :
- Prix médian : maisons 3 182 €/m², appartements 3 680 €/m².
- DPE (1 905 ventes appariées, 97 % de maisons) : A 3 440 → G 2 000 €/m², Spearman −0,19.
- Communes en TRI plus chères (3 892 contre 2 906) : effet de localisation, pas prix du risque.
- Revenu médian IRIS : Spearman 0,38 (vente), 0,56 (IRIS).
- Pour le sprint 3 : log-prix, un modèle par type, pas de DPE en variable directe, ingérer 2021-2023 pour le test temporel.

## Confidentialité : reste ouvert
44 totaux restent reconstituables par soustraction de plusieurs cellules ; le croisement r7/r9 n'est pas mesuré. Décision au sprint 3 : publier moins de ventilations par hexagone.
