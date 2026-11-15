# ADR 0002 — PostgreSQL + PostGIS + H3 comme base de service

**Statut :** accepté — 2026-11-15

## Contexte
La web app interroge par zone (bbox), par adresse et par agrégats hexagonaux. Il faut
des jointures spatiales (parcelle × zone inondable × IRIS) et des tuiles vectorielles.

## Décision
PostgreSQL 16 + PostGIS (index GIST), extension `h3-pg` pour les agrégats, Martin
pour servir les tuiles directement depuis PostGIS.

## Alternatives écartées
- Cassandra : pas de requêtes spatiales natives.
- MongoDB géo : jointures spatiales polygon × polygon limitées.

## Conséquences
Chaque requête de l'API doit passer sous 100 ms (vérifié par `EXPLAIN ANALYZE` au sprint 2).
