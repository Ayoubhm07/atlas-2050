# Sprint 4 — API

**Date :** 2026-11-16 · **Statut :** API livrée et testée sans base ; intégration PostGIS
et mesure de latence de bout en bout à relancer (moteur Docker en panne pendant la mesure)

## Livré
- **Routes** (`apps/api/src/atlas_api/routes.py`, détail : [docs/api/README.md](../api/README.md)) :
  `GET /communes?q=`, `GET /hex`, `GET /communes/{code}/stats`,
  `GET /communes/{code}/risques`, `GET /estimate` (coordonnées), `POST /estimate`
  (adresse ou coordonnées, corps JSON), `GET /health`, toutes dans
  l'enveloppe `{success, data, error, meta}` (Pydantic v2, `schemas.py`).
- **Données** (`db.py`, `sql/api_queries.sql`) : pool psycopg 3, requêtes nommées
  paramétrées, connexions en lecture seule avec `statement_timeout` ; la copie
  `docs/sql/api_queries.sql` est vérifiée identique par un test. Deux requêtes nouvelles :
  `valuation_date`, `neighbour_sales` ; `point_lookup` lit aussi Gini et code RGA ;
  `hex_aggregates` est triée et plafonnée.
- **Estimation** (`estimator.py`) : réutilise `atlas_pipelines.ml` (SavedModel,
  `neighbourhood_log_price`, `lgb_matrix`, `project`, `effets_from_results`,
  `current_risks`) ; modèle chargé une fois au démarrage ; voisinage calculé sur les
  ventes du gold strictement antérieures à la date de valeur ; scénarios statu quo,
  rénovation en D, sensibilité nouveaux risques à deux bornes « non causal », climat
  « indisponible (DRIAS) » sans chiffre ; 6 facteurs TreeSHAP.
- **Géocodage** (`geocode.py`) : BAN, délai, nouvelles tentatives, réponse validée ;
  l'adresse n'est ni renvoyée ni journalisée (y compris par `httpx`, qui écrit l'URL en
  INFO : trouvé par un test, corrigé).
- **Protection** : seau à jetons par IP (`ratelimit.py`, 429 dans l'enveloppe avec
  `Retry-After`, `/estimate` coûte 5 jetons), ETag + `Cache-Control` sur les agrégats,
  `no-store` sur l'estimation, CORS GET seulement depuis la configuration, erreurs sans
  détail interne, journal d'accès sans chaîne de requête.
- **OpenAPI** : [docs/api/openapi.json](../api/openapi.json) (`make api-openapi`).
- **Tuiles** : Martin exposé directement avec `infra/martin/config.yaml`
  (`auto_publish: false`, `agg_hex`, communes, IRIS seulement). Avant ce sprint, la
  configuration par défaut auto-publiait `gold.fact_transactions` : ventes isolées
  servies en tuiles.
- **Infra** : `apps/api/Dockerfile`, service `api` (profil `api`) dans docker-compose,
  CI installe `pipelines[ml]` avant l'API et type aussi les tests.

## Vérifications
| Contrôle | Résultat |
|---|---|
| `pytest` (apps/api, après revue sécurité) | 148 réussis hors intégration, couverture 93 % ; `-m integration` : 18 réussis (PostGIS réel) |
| `pytest` (pipelines) | 115 réussis, couverture 94,5 % |
| `ruff check .` | propre |
| `mypy src tests scripts` (strict) | propre, 23 fichiers ; pipelines : `ruff` et `mypy` propres (43 fichiers) |
| Estimateur seul, vrai modèle, 30 appels | p50 75 ms, p95 88 ms (Maison 96 m², DPE G, Bordeaux) |

## Latence par route
Voir « Latence par route (mesurée) » en fin de document. Les requêtes SQL elles-mêmes
sont mesurées par EXPLAIN ANALYZE dans [gold_33_2024.md](../quality/gold_33_2024.md).

## Ouvert
1. Fait le 2026-11-16 (intégration 18/18, latence mesurée, voir plus bas).
2. Démarrage lent (≈ 20 s à froid sous Windows) : `rerender` importe `train` → MLflow,
   et `examples` importe `explain` → shap. Déplacer `SavedModel` et les aides de
   `examples` dans des modules légers côté pipelines.
3. Le limiteur est par processus : plusieurs workers ou instances multiplient la limite
   (Redis ou proxy).
4. Cat-Nat 10 ans lu à la date de référence du gold, pas recalculé à la date de valeur.
5. Configuration Martin non testée contre l'image v0.14.2 (Docker indisponible).
6. **agg_hex : soustractions multiples et r7/r9 (revue sécurité, LOW 7, non corrigé).**
   La suppression secondaire de `dbt/models/gold/agg_hex.sql` ne regarde que des
   **paires** (un total et UN sous-groupe, même hexagone, même résolution). Restent
   possibles : (a) total − somme de plusieurs sous-groupes publiés (ex. « tous » −
   Maison − Appartement, ou une année « tous » − la somme des années publiées) qui peut
   isoler 1 à 4 ventes ; (b) un hexagone r7 − ses 7 enfants r9 publiés (les deux
   résolutions ne sont jamais comparées). Les médianes ne se soustraient pas : la fuite
   porte surtout sur les effectifs, mais une médiane de groupe isolé de 1 à 2 ventes
   reste approchable par recoupement. À traiter au sprint 5 : contrôle par ensembles
   (somme des enfants, toutes dimensions et résolutions) dans le modèle dbt et dans son
   test `agg_hex_pas_de_differenciation.sql`.

## Revue sécurité (2026-11-16)

| # | Sévérité | Constat | Correction | Preuve |
|---|---|---|---|---|
| 1 | HAUTE | `/estimate` révélait le prix d'**une** vente voisine : la médiane d'anneau servait dès 1 vente (`features.py`, `estimator.py`) ; l'avertissement « Moins de 5 ventes » servait d'oracle | `neighbourhood_log_price(min_sales=5)` (ADR 0005) : sous 5 ventes, a priori seul et `voisinage_n` = 0, à l'entraînement et en service ; avertissement remplacé par un texte constant ; modèle réentraîné (voir ci-dessous) | `test_single_sale_price_cannot_be_read_below_five` (échoue avec l'ancienne règle, vérifié), `test_warnings_do_not_depend_on_neighbour_count`, `test_below_min_sales_uses_prior_only` |
| 2 | MOYENNE | API et Martin connectés en superutilisateur | `infra/db/roles.sql` (idempotent) + `02-roles.sh` + `make db-roles` : `atlas_api` (SELECT gold), `atlas_tiles` (SELECT agg_hex, dim_commune, dim_iris), non superutilisateurs, `default_transaction_read_only=on` ; mots de passe dans `.env` ; compose câblé ; le chargeur garde le propriétaire et redonne les SELECT à chaque bascule | `tests/test_deploy_config.py`, `test_swap_regrants_least_privilege_readers` ; tests d'intégration des rôles **en attente de Docker** |
| 3 | MOYENNE | Clé du limiteur lue dans `X-Forwarded-For` par l'API ; `--forwarded-allow-ips` figé dans l'image | clé = `scope["client"]` seulement ; `FORWARDED_ALLOW_IPS` (env, défaut 127.0.0.1, compose `API_FORWARDED_ALLOW_IPS`) ; IPv6 groupée par /64 | `test_client_key_*`, `test_rate_limit_ignores_spoofed_forwarded_for`, `test_dockerfile_forwarded_ips_come_from_env` |
| 4 | BASSE | Garde « pas de pile » de `/estimate` inopérante : Starlette relance, uvicorn journalise pile et message | `QuietErrorsMiddleware`, enveloppe la plus externe (`AtlasApi.build_middleware_stack`) : exception absorbée sur `/estimate`, type seul journalisé | `test_estimate_error_logs_no_traceback_nor_message` (échoue sans le middleware, vérifié) |
| 5 | BASSE | Adresse dans la chaîne de requête de `GET /estimate` | `POST /estimate` (JSON) pour l'adresse ; `GET` n'accepte plus que lat/lon (`address` → 422) ; CORS POST + Content-Type ; OpenAPI régénéré | `test_estimate_post_*`, `test_estimate_validation` |
| 6 | BASSE | `surface_moyenne` (moyenne exacte, inversible par différence) | `surface_mediane`, médiane arrondie à 5 m² (`api_queries.sql`, copie docs identique) | `test_commune_stats`, `test_sql_docs_in_sync` ; contrôle PostGIS en attente |
| 7 | BASSE | agg_hex : soustractions multiples, r7/r9 | **ouvert** (point 6 ci-dessus) | — |
| 8 | BASSE | BAN : nouvelle tentative sur 429, pas d'échéance globale, pas de cache | aucun réessai sur 429 ; échéance globale ≤ 3 s (délai de chaque tentative borné au temps restant) ; cache LRU 256 en mémoire (succès seulement) | `test_ban_does_not_retry_on_429`, `test_ban_overall_deadline_caps_attempts_and_timeouts`, `test_ban_lru_cache_*` |
| — | infra | db 5432, MLflow 5000, Airflow 8080 exposés sur toutes les interfaces | liés à `127.0.0.1` | `test_published_ports_bound_to_loopback` |

### Réentraînement (seuil de 5 ventes)
`python -m atlas_pipelines.ml.train --out ../ml` (2 h 20 min passé, 00:46 → 03:46), puis
`rerender` (quantiles de résidus du run vérifiés identiques). Stratégie : global.

| Validation | MAE Ridge avant → après | MAE LightGBM avant → après | R² LightGBM | Écart LGB − Ridge (IC 95 %) |
|---|---|---|---|---|
| Temporelle (test 2024, 17 418 ventes) | 794 → 793 | **721 → 726** €/m² | 0,666 → 0,656 | −73 [−88 ; −54] → −67 [−81 ; −52] |
| Spatiale (5 plis par commune, 78 358) | 958 → 964 | **887 → 871** €/m² | 0,501 → 0,519 | −72 [−136 ; −29] → −93 [−165 ; −49] |

Porte bloquante : **toujours passée** (spatiale et temporelle, IC entièrement négatif).
Le seuil coûte 5 €/m² en temporel et en fait gagner 16 en spatial (une médiane de 1 à
4 ventes était surtout du bruit). Sonde rejouée sur le vrai modèle : P50 = 3 180 €/m²
quel que soit le prix (1 500 à 6 000 €/m²) de l'unique vente voisine, et identique à
l'absence de vente. `ml/results.json` et `ml/report.md` régénérés ; les chiffres du
sprint 3 (`sprint-3.md`) restent ceux du modèle d'alors.

### Contrôles base de données (Docker revenu, 2026-11-16)
- `make db-roles` sur la base existante : rôles créés, 2e passage sans erreur
  (idempotent), mots de passe trop courts refusés. `atlas_api` : SELECT sur les 5 tables
  du gold ; `atlas_tiles` : agg_hex, dim_commune, dim_iris ; `rolsuper = f`,
  `default_transaction_read_only=on`.
- `make load` (gold rechargé, bascule) : les SELECT des deux rôles sont redonnés.
- `pytest -m integration` : **18 réussis**, 0 ignoré (rôles, `surface_mediane`, estimation
  avec le modèle réentraîné).
- Martin (`docker compose up tiles`) connecté en `atlas_tiles` (pg_stat_activity) ;
  `/catalog` = `agg_hex`, `communes`, `iris` seulement ; `/fact_transactions/...` → 404.
- Trouvé en route : le port lié à `127.0.0.1` rendait `POSTGRES_HOST=localhost` lent sous
  Windows (`::1` essayé d'abord, ≈ 5,5 s par connexion → PoolTimeout). Défaut passé à
  `127.0.0.1` (API, chargeur, `.env.example`). **À faire** : `POSTGRES_HOST=127.0.0.1`
  dans le `.env` local (non modifié ici).

## Latence par route (mesurée)
`make api-latency`, rôle `atlas_api`, PostGIS Docker Desktop sous Windows, modèle
réentraîné, 50 appels après 3 à blanc, en processus (TestClient) :

| Route | n | p50 (ms) | p95 (ms) |
|---|---|---|---|
| GET /health | 50 | 59.8 | 67.0 |
| GET /communes?q=bord | 50 | 75.0 | 96.9 |
| GET /hex r9 Bordeaux | 50 | 1031.3 | 1942.0 |
| GET /hex r7 Gironde | 50 | 803.1 | 1200.6 |
| GET /communes/33063/stats | 50 | 228.0 | 419.4 |
| GET /communes/33063/risques | 50 | 56.5 | 70.1 |
| GET /estimate (lat/lon, maison G) | 50 | 1653.7 | 2765.7 |

Lecture : même `/health` coûte 60 ms, donc l'aller-retour vers Docker Desktop domine les
petites routes ; `/hex` (jusqu'à 5 000 hexagones sérialisés) et `/estimate` (une projection
de 20 000 tirages par scénario) dépassent la seconde au p95. Mesure faite juste après un
réentraînement de 2 h sur la même machine. Pistes sprint 5 : tuiles Martin plutôt que
/hex pour la carte, moins de tirages par scénario.
