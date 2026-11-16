-- Rôles en lecture seule d'ATLAS 2050 (moindre privilège). IDEMPOTENT : rejouable sur
-- une base neuve (02-roles.sh, premier démarrage) comme sur une base existante
-- (make db-roles). À exécuter avec psql par le rôle PROPRIÉTAIRE du gold (POSTGRES_USER,
-- celui du chargeur), avec les variables psql :
--   psql -v api_password=... -v tiles_password=... -f roles.sql
-- Les mots de passe viennent de .env (ATLAS_API_DB_PASSWORD, ATLAS_TILES_DB_PASSWORD) ;
-- ils ne sont jamais écrits dans ce fichier.
--
--   atlas_api   : SELECT sur tout le schéma gold, rien d'autre.
--   atlas_tiles : SELECT sur gold.agg_hex, gold.dim_commune, gold.dim_iris seulement
--                 (jamais gold.fact_transactions : une ligne par vente).
-- Aucun des deux n'est superutilisateur ; transactions en lecture seule par défaut.
-- Le chargeur (load/postgis.py) redonne ces SELECT à chaque bascule, les tables étant
-- recréées.

\set ON_ERROR_STOP on

\if :{?api_password}
\else
  \echo 'Variable psql api_password manquante (-v api_password=...)'
  SELECT 1 / 0 AS api_password_manquant;
\endif
\if :{?tiles_password}
\else
  \echo 'Variable psql tiles_password manquante (-v tiles_password=...)'
  SELECT 1 / 0 AS tiles_password_manquant;
\endif

SELECT length(:'api_password') < 16 OR length(:'tiles_password') < 16
       OR :'api_password' = :'tiles_password' AS mot_de_passe_faible \gset
\if :mot_de_passe_faible
  \echo 'Mots de passe des rôles : 16 caractères au moins, et différents l''un de l''autre'
  SELECT 1 / 0 AS mot_de_passe_faible;
\endif

BEGIN;

SELECT format('CREATE ROLE %I', r)
FROM unnest(ARRAY['atlas_api', 'atlas_tiles']) AS r
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec

ALTER ROLE atlas_api WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT CONNECTION LIMIT 40 PASSWORD :'api_password';
ALTER ROLE atlas_tiles WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    NOBYPASSRLS NOINHERIT CONNECTION LIMIT 20 PASSWORD :'tiles_password';
ALTER ROLE atlas_api SET default_transaction_read_only = on;
ALTER ROLE atlas_tiles SET default_transaction_read_only = on;
ALTER ROLE atlas_api SET statement_timeout = '5s';
ALTER ROLE atlas_tiles SET statement_timeout = '10s';

-- Aucun droit hérité de PUBLIC hors connexion explicite ; pas de création dans public.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO atlas_api, atlas_tiles', current_database()) \gexec

CREATE SCHEMA IF NOT EXISTS gold;
REVOKE ALL ON SCHEMA gold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA gold FROM atlas_api, atlas_tiles;
GRANT USAGE ON SCHEMA gold TO atlas_api, atlas_tiles;

-- API : tout le gold en lecture (les ventes servent au calcul de voisinage, jamais
-- renvoyées : ADR 0005), y compris les tables créées plus tard par le propriétaire.
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO atlas_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO atlas_api;

-- Tuiles : les trois tables publiées par Martin (infra/martin/config.yaml), pas plus.
SELECT format('GRANT SELECT ON gold.%I TO atlas_tiles', t)
FROM unnest(ARRAY['agg_hex', 'dim_commune', 'dim_iris']) AS t
WHERE to_regclass(format('gold.%I', t)) IS NOT NULL \gexec

COMMIT;
