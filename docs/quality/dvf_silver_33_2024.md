# Qualité DVF silver — Gironde (33), 2024

Source : DVF géolocalisées `full-2024.csv.gz` (data.gouv.fr), exécution locale le 2026-11-15 en 43 s (PySpark local).

| Étape | Lignes | Rejetées |
|---|---:|---:|
| Bronze (toutes lignes) | 82 948 |  |
| Ventes d'un logement unique (lignes regroupées en 1/vente) | 18 239 | 64 709 |
| Prix ≥ 1000 €, surface ≥ 9 m² | 18 200 | 39 |
| Avec coordonnées | 18 003 | 197 |
| Sans prix/m² aberrant (IQR × 3 sur log) | 17 766 | 237 |

## Lecture

- L'écart de l'étape 2 mélange deux choses : les lignes regroupées (une vente occupe
  plusieurs lignes) et les ventes rejetées (plusieurs logements, local professionnel).
- Prix/m² médian après nettoyage : maisons ≈ 3 180 €/m² (10 384 ventes), appartements
  ≈ 3 680 €/m² (7 382 ventes).
- Ventes sous 300 €/m² restantes : 23 (88 avant le passage de l'IQR en log).
- Valeurs hautes conservées volontairement : Lège-Cap-Ferret et domaines avec plusieurs
  hectares de terrain (jusqu'à ~74 000 €/m² bâti). Voir la limite connue dans
  [data-contract.md](../data-contract.md) §1.
- Écriture Parquet : Spark sous Windows sans `winutils` ne peut pas écrire ; le job
  `atlas_silver_dvf` écrit le Parquet silver dans le conteneur Airflow.
