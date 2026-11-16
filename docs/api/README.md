# API ATLAS 2050 (sprint 4)

Schéma complet : [`openapi.json`](openapi.json) (régénéré par `make api-openapi`, un test
échoue s'il n'est plus à jour). Code : `apps/api/src/atlas_api/`.

Toutes les réponses : `{success, data, error, meta}`, y compris 404, 422, 429 et 503.
En-tête `X-Robots-Tag: noindex, nofollow` partout, `robots.txt` interdit tout (ADR 0005).

| Route | Source | Cache |
|---|---|---|
| `GET /communes?q=` | `gold.dim_commune.nom_recherche` (préfixe, sans casse ni accents, jokers LIKE neutralisés) | ETag + `max-age` |
| `GET /hex?bbox=&res=7\|9&type=&dpe=&annee=` | `gold.agg_hex` seulement (jamais à la volée) ; bbox finie, ordonnée, aire max 4 deg² (r7) / 0,25 deg² (r9), plafond 5 000 lignes (400 au-delà) | ETag + `max-age` |
| `GET /communes/{code}/stats` | ventes de la commune, groupes ≥ 5, quartiles ≥ 11, arrondi 10 €/m², surface **médiane** arrondie à 5 m² | ETag + `max-age` |
| `GET /communes/{code}/risques` | `gold.fact_risques_commune` + RGA des IRIS | ETag + `max-age` |
| `GET /estimate?lat=&lon=&…` | coordonnées seulement ; modèle LightGBM du sprint 3 + projection (`atlas_pipelines.ml`) | `no-store` |
| `POST /estimate` (JSON) | adresse **ou** coordonnées dans le corps ; même calcul | `no-store` |
| `GET /health` | `SELECT 1` sur le pool + état du modèle ; 503 si la base est injoignable | `no-store` |

SQL : source unique `apps/api/src/atlas_api/sql/api_queries.sql`, copie identique dans
`docs/sql/api_queries.sql` (test `test_sql_docs_in_sync`). Paramètres liés par psycopg,
connexions en lecture seule avec `statement_timeout`.

## /estimate

Entrée : `type_local`, `surface`, `pieces`, `surface_terrain`, `dependances`, `dpe`
(facultatif) et la position :
- `GET /estimate` : `lat`+`lon` seulement. Un paramètre `address` est refusé (422) ;
- `POST /estimate`, corps JSON : `lat`+`lon` **ou** `address`. L'adresse ne passe donc
  jamais dans une URL (journaux de proxy, historique du navigateur, en-tête Referer).

Géocodage BAN : échéance globale de 3 s toutes tentatives comprises (chaque tentative a
pour délai le temps restant), 2 nouvelles tentatives sur erreur réseau ou 5xx, **aucune**
sur 429 (quota BAN : insister l'aggraverait), réponse validée, score ≥ 0,5. Petit cache
LRU en mémoire (256 adresses normalisées → point, `API_BAN_CACHE_SIZE`, 0 = désactivé),
jamais écrit ni journalisé ; les échecs ne sont pas mis en cache.

- L'adresse n'est ni renvoyée ni journalisée : uvicorn tourne avec `--no-access-log`,
  `AccessLogMiddleware` écrit le chemin sans chaîne de requête, les journaux `httpx`
  (qui écrivent l'URL) sont limités aux avertissements, la pile d'appel d'une erreur
  500 sur `/estimate` n'est pas journalisée. Starlette relance l'exception après avoir
  envoyé la 500, et uvicorn écrirait alors la pile et le message (« Exception in ASGI
  application ») : `QuietErrorsMiddleware`, enveloppe la plus externe (`AtlasApi`),
  absorbe l'exception sur `/estimate` et n'en journalise que le type.
- Date de valeur = lendemain de la dernière vente du gold. Prix de voisinage calculé par
  `features.neighbourhood_log_price` sur les ventes du gold STRICTEMENT antérieures
  (30 plus récentes par cellule de l'anneau r7, 500 plus récentes du type pour l'a
  priori), exactement comme à l'entraînement. **Seuil ADR 0005** : sous 5 ventes dans
  l'anneau, la médiane des voisins n'est pas utilisée (a priori départemental seul,
  `voisinage_n` = 0), à l'entraînement comme en service. Sans ce seuil, une vente
  isolée se lisait dans l'estimation (sonde : prix d'une seule vente voisine → P50).
  Les avertissements renvoyés ne dépendent pas du nombre de voisins (un avertissement
  « moins de 5 ventes » servait d'oracle).
- Sortie : prix/m² et valeur P10-P50-P90 (arrondis 10 € / 1 000 €), risques actuels,
  scénarios 2050 (`statu_quo`, `renovation_D`, `nouveau_risque_*` en sensibilité « non
  causal » avec les bornes avec / sans voisinage, `climat_rcp45|85` au statut
  « indisponible (DRIAS) » sans aucun chiffre), 6 facteurs SHAP (TreeSHAP natif de
  LightGBM). Les variables de voisinage et la position sont données en contribution,
  jamais en valeur.
- `explication` (sprint 5, waterfall du front) : `base_prix_m2` (valeur attendue du
  modèle, constante, arrondie à 10 €), `autres_pct` (effet cumulé des variables hors des
  6 facteurs) et `prix_m2_modele` (prédiction ponctuelle, arrondie à 10 €). TreeSHAP est
  additif en log-prix : base × Π(1 + facteur) × (1 + autres) = prédiction, aux arrondis
  près (test `test_estimate_waterfall_closes_on_model_prediction`). La prédiction
  ponctuelle diffère de la médiane P50 de la fourchette, tirée avec les résidus.
- Une estimation coûte 5 jetons du limiteur (60/minute par IP par défaut).

## Limitation de débit et IP client

La clé du limiteur est `scope["client"]` ; l'API ne lit jamais `X-Forwarded-For`
elle-même. Derrière un reverse proxy, uvicorn (`--proxy-headers`) remplace l'IP de la
socket par celle de `X-Forwarded-For` **seulement** si le pair est dans
`FORWARDED_ALLOW_IPS` (variable native d'uvicorn ; image : `127.0.0.1` ; compose :
`API_FORWARDED_ALLOW_IPS`, défaut `127.0.0.1`). Y mettre l'IP ou le CIDR du proxy de
confiance ; jamais `*` si l'API est joignable sans passer par lui, sinon chaque client
choisit son identité et contourne la limite. Les adresses IPv6 sont groupées par /64
(un abonné dispose en général d'un /64 entier) ; une IPv4 mappée en IPv6 compte comme
l'IPv4.

## Base de données : rôles au moindre privilège

`infra/db/roles.sql` (idempotent ; premier démarrage : `infra/db/02-roles.sh`, base
existante : `make db-roles`) crée deux rôles non superutilisateurs, en
`default_transaction_read_only = on`, mots de passe lus dans `.env`
(`ATLAS_API_DB_PASSWORD`, `ATLAS_TILES_DB_PASSWORD`, 16 caractères au moins) :

| Rôle | Service | Droits |
|---|---|---|
| `atlas_api` | `api` | `SELECT` sur tout le schéma `gold` (privilèges par défaut compris) |
| `atlas_tiles` | `tiles` (Martin) | `SELECT` sur `gold.agg_hex`, `gold.dim_commune`, `gold.dim_iris` seulement |
| propriétaire (`POSTGRES_USER`) | chargeur (`make load`, Airflow) | inchangé |

Le chargeur recrée les tables à chaque bascule : il redonne ces `SELECT` dans la même
transaction (`load/postgis.py`, `grant_sql`). Ports de db (5432), MLflow (5000) et
Airflow (8080) liés à `127.0.0.1`, comme l'API et Martin.

## Tuiles vectorielles : Martin, exposé directement

Choix : Martin sert lui-même les tuiles (`infra/martin/config.yaml`), sans proxy par
l'API. Plus simple (pas de flux binaire à relayer, cache HTTP de Martin) et sûr parce
que la sécurité tient à la **configuration**, pas au chemin réseau :

- `auto_publish: false` : sans cette ligne Martin publierait toutes les tables
  géométriques du gold, dont `gold.fact_transactions` (une ligne par vente, avec prix et
  parcelle). Ce serait une fuite directe de ventes isolées ;
- sources publiées : `agg_hex` (agrégats déjà filtrés par dbt : ≥ 5 ventes, suppression
  secondaire, arrondi), `communes` et `iris` (contours, sans vente), avec la liste
  explicite des colonnes ;
- port lié à `127.0.0.1` dans docker-compose : en production, Martin passe derrière le
  même reverse proxy que l'API (TLS, `X-Robots-Tag`, limitation de débit).

URL : `http://localhost:3001/agg_hex/{z}/{x}/{y}` (catalogue : `/catalog`).
Défense supplémentaire : Martin se connecte avec le rôle `atlas_tiles`, qui ne peut
lire que ces trois tables. Même si `auto_publish` était réactivé par erreur,
`gold.fact_transactions` resterait illisible.
