# ADR 0001 — Lakehouse Parquet bronze/silver/gold avec PySpark

**Statut :** accepté — 2026-11-15

## Contexte
DVF (~20 M lignes France) et DPE (~10 M) dépassent ce qu'un pandas en mémoire traite
confortablement, et le sujet demande une architecture Big Data.

## Décision
Stocker en Parquet partitionné (`dep`, `annee`) en trois couches. PySpark pour
bronze → silver (gros volumes, jointures lourdes). DuckDB via dbt pour silver → gold.

## Conséquences
- + Passage à la France entière sans réécriture.
- + DuckDB est très rapide sur Parquet ; un benchmark PySpark vs DuckDB est fourni (question jury probable).
- − Java requis pour Spark : tourne dans Docker, pas sur le poste.
