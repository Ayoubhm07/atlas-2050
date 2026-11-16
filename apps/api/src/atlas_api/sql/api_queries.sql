-- Requêtes de l'API ATLAS 2050 sur le schéma gold (PostGIS).
-- Source unique : apps/api/src/atlas_api/sql/api_queries.sql (chargé par l'API) ;
-- docs/sql/api_queries.sql en est une copie identique (test test_sql_docs_in_sync).
-- Paramètres positionnels ($1, $2...) convertis en paramètres psycopg côté API.
-- Règle ADR 0005 : jamais une vente isolée → agrégats d'au moins 5 ventes, quartiles
-- seulement à partir de 11 ventes, prix arrondis à 10 €/m², aucune fenêtre de dates
-- libre (une fenêtre étroite isolerait des ventes : seules les années sont servies).
-- Mesures EXPLAIN ANALYZE : docs/quality/gold_33_2024.md (script explain_api_queries.py).

-- name: hex_aggregates
-- Hexagones H3 dont le centre est dans l'emprise, lus dans gold.agg_hex (agrégats
-- pré-calculés par dbt : ≥ 5 ventes, suppression secondaire, prix arrondis à
-- 10 €/m²). Chaque filtre vaut une modalité ou 'tous'. $1 = résolution (7 ou 9) ;
-- $2..$5 = xmin, ymin, xmax, ymax (EPSG:4326) ;
-- $6 = type_local ; $7 = année ('2024') ; $8 = étiquette DPE ; $9 = plafond de lignes
-- (l'API demande plafond + 1 pour détecter le dépassement).
SELECT h3, n_ventes, prix_m2_median
FROM gold.agg_hex
WHERE geom && ST_MakeEnvelope($2, $3, $4, $5, 4326)
  AND resolution = $1
  AND type_local = $6
  AND annee = $7
  AND dpe_etiquette = $8
ORDER BY h3
LIMIT $9;

-- name: commune_search
-- Recherche de commune par préfixe de nom, insensible à la casse et aux accents
-- (« étau », « Étau », « ETAU » → Étauliers), 10 résultats. dim_commune.nom_recherche
-- = lower(strip_accents(nom)) calculé par dbt, index text_pattern_ops ; la saisie est
-- normalisée ici de la même façon (lower dans la collation de la base, puis accents
-- latins retirés). $1 = préfixe saisi (échappé côté API : % et _ neutralisés).
SELECT code_insee, nom_commune, code_departement, lon, lat
FROM gold.dim_commune
WHERE nom_recherche LIKE translate(lower($1::text),
          'àáâãäåçèéêëìíîïñòóôõöùúûüýÿ',
          'aaaaaaceeeeiiiinooooouuuuyy') || '%'
ORDER BY n_adresses DESC, code_insee
LIMIT 10;

-- name: point_lookup
-- Point (clic carte / adresse géocodée) → IRIS, revenus, RGA, risques de la commune.
-- Fournit aussi les variables du modèle de prix lues au point (Gini, code RGA).
-- $1 = lon, $2 = lat.
SELECT i.code_iris, i.nom_iris, i.code_insee, c.nom_commune,
       i.revenu_median, i.taux_pauvrete, i.gini,
       i.rga_code_exposition, i.rga_exposition,
       r.n_catnat, r.n_catnat_10ans, r.in_tri, r.ppri, r.azi
FROM gold.dim_iris AS i
JOIN gold.dim_commune AS c USING (code_insee)
LEFT JOIN gold.fact_risques_commune AS r USING (code_insee)
WHERE ST_Intersects(i.geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
ORDER BY i.code_iris  -- point sur une frontière : résultat déterministe (plus petit code)
LIMIT 1;

-- name: commune_transaction_stats
-- Statistiques de prix d'une commune par type de bien et année. ADR 0005 : groupe
-- publié à partir de 5 ventes (médiane) ; quartiles seulement à partir de 11 ventes
-- (sous ce seuil, Q1/Q3 tombent sur 1 à 2 ventes) ; prix arrondis à 10 €/m².
-- Surface : MÉDIANE arrondie à 5 m² (une moyenne non arrondie se laisse inverser : avec
-- deux publications avant/après une vente, n·moyenne donne sa surface exacte).
-- $1 = code INSEE.
SELECT type_local, annee,
       count(*) AS n_ventes,
       CASE WHEN count(*) >= 11 THEN
           round(percentile_cont(0.25) WITHIN GROUP (ORDER BY prix_m2) / 10) * 10
       END AS prix_m2_q1,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2) / 10) * 10
           AS prix_m2_median,
       CASE WHEN count(*) >= 11 THEN
           round(percentile_cont(0.75) WITHIN GROUP (ORDER BY prix_m2) / 10) * 10
       END AS prix_m2_q3,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY surface_bati) / 5) * 5
           AS surface_mediane
FROM gold.fact_transactions
WHERE code_commune = $1
GROUP BY type_local, annee
HAVING count(*) >= 5
ORDER BY type_local, annee;

-- name: commune_risks
-- Fiche risques d'une commune + répartition RGA de ses IRIS. $1 = code INSEE.
SELECT r.code_insee, c.nom_commune, r.n_catnat, r.n_catnat_10ans, r.date_reference,
       r.in_tri, r.ppri, r.n_ppr, r.azi,
       (SELECT jsonb_object_agg(rga_exposition, n) FROM (
            SELECT rga_exposition, count(*) AS n FROM gold.dim_iris
            WHERE code_insee = $1 GROUP BY rga_exposition) AS g) AS rga_iris
FROM gold.fact_risques_commune AS r
JOIN gold.dim_commune AS c USING (code_insee)
WHERE r.code_insee = $1;

-- name: valuation_date
-- Date de la dernière vente du gold : la date de valeur de l'estimation est le
-- lendemain (toutes les ventes du gold sont alors strictement antérieures).
SELECT max(date_mutation) AS derniere_vente FROM gold.fact_transactions;

-- name: neighbour_sales
-- Ventes de RÉFÉRENCE du prix de voisinage (atlas_pipelines.ml.features), toutes
-- strictement antérieures à la date de valeur, du même type de bien :
--   * les $4 plus récentes de chaque cellule H3 r7 de l'anneau ($2 = cellules) ;
--   * les $5 plus récentes du type (a priori du lissage).
-- UNION sur id_mutation : une vente des deux listes n'est comptée qu'une fois.
-- Usage INTERNE au calcul : l'API ne renvoie jamais ces lignes (ADR 0005).
-- $1 = type_local, $2 = cellules r7 (text[]), $3 = date de valeur, $4 = k, $5 = n_prior.
SELECT id_mutation, date_mutation, h3_r7, prix_m2 FROM (
    SELECT id_mutation, date_mutation, h3_r7, prix_m2,
           row_number() OVER (PARTITION BY h3_r7
                              ORDER BY date_mutation DESC, id_mutation) AS rang
    FROM gold.fact_transactions
    WHERE type_local = $1 AND h3_r7 = ANY($2::text[]) AND date_mutation < $3
) AS anneau
WHERE rang <= $4
UNION
(SELECT id_mutation, date_mutation, h3_r7, prix_m2
 FROM gold.fact_transactions
 WHERE type_local = $1 AND date_mutation < $3
 ORDER BY date_mutation DESC, id_mutation
 LIMIT $5);
