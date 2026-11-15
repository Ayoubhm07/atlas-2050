# Sprint 1 — Ingestion Big Data (bronze → silver)

**Date :** 2026-11-15 · **Statut :** terminé

## Livré
- `pipelines/atlas_pipelines/` : client HTTP (streaming, checksum, retries, ETag,
  limiteur de débit), un collecteur par source, nettoyage DVF silver en PySpark, CLI.
- `pipelines/dags/atlas_ingestion.py` : 6 DAGs d'ingestion + `atlas_silver_dvf`,
  chaînés par Datasets (BAN → Géorisques, DVF → silver).
- Image Airflow + Java + PySpark construite ; les 7 DAGs se chargent sans erreur.
- 49 tests (dont 2 PySpark), couverture 85 %, ruff et mypy strict propres.

## Exécution réelle — Gironde (33), DVF 2024
| Source | Résultat |
|---|---|
| DVF 2024 (bronze) | 82 948 lignes → **17 766 ventes** en silver |
| BAN | 534 communes |
| DPE ADEME | fichier bronze de 12,7 Mo |
| INSEE Filosofi IRIS 2021 | fichier bronze écrit |
| Géorisques | 7 972 arrêtés Cat-Nat, 65 communes en TRI, AZI vide (voir plus bas) |

Rapport qualité : [quality/dvf_silver_33_2024.md](../quality/dvf_silver_33_2024.md).

## Défauts trouvés et corrigés
| Origine | Défaut | Correction |
|---|---|---|
| Exécution réelle | CSV DVF : guillemets non détectés → crash ligne 584 909 | quote/escape explicites + test de régression |
| Revue adverse | Terrain compté 2 à 32 fois (produit cartésien local × culture) | somme par groupe de local, max par parcelle |
| Revue adverse | Borne basse IQR négative → ventes à 8 €/m² gardées | IQR sur log(prix/m²) : 88 → 23 ventes < 300 €/m² |
| Revue adverse | BAN jamais rafraîchie (URL fixe `latest/`) | requêtes conditionnelles ETag / Last-Modified |
| Revue adverse | Fichiers DRIAS qui s'écrasent, nom non validé | champ `horizon`, nom validé, doublons refusés |
| Revue adverse | DAG INSEE lancé en 2028 seulement | `@once`, start_date antérieur |
| Revue adverse | Fichiers partiels lisibles par Spark, silver non atomique | fichiers temporaires cachés, bascule par dossier |
| Revue adverse | `"null"` texte au lieu de NULL ; code `97` ambigu ; curseur DPE http/en boucle | corrigés + tests |

## Reste ouvert (sprints suivants)
- **DRIAS** : compte et dépôt manuel des fichiers requis (bloquant pour la projection 2050).
- **Inondation en Gironde** : AZI absent → ajouter les PPRI (sprint 2).
- **Biens atypiques** (domaines viticoles, Cap-Ferret) : marquer ou exclure au sprint 3.
- Ingestion des 3 départements × 6 périodes complètes : pas encore lancée.
- Licences INSEE Filosofi et IGN Contours-IRIS à confirmer.
- Fichiers DRIAS : présence éventuelle de lignes de commentaire `#` à vérifier sur un vrai fichier.
