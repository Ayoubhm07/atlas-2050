# ATLAS 2050

> Combien vaudra ce logement quand le climat aura changé ?

ATLAS 2050 croise six jeux de données publics français pour estimer le prix d'un
logement aujourd'hui, mesurer son exposition aux risques climatiques et à la loi
Climat (DPE), et projeter une **fourchette** de valeur en 2030 et 2050 sous deux
scénarios du GIEC (RCP 4.5 et 8.5), avec une explication lisible de chaque décote.

Projet IPSSI — module Open Data (sujet libre).

## Sources Open Data
Voir [docs/sources.md](docs/sources.md) : URL, licence, volume, fraîcheur et pièges de chaque source.

## Architecture
Voir [docs/architecture.md](docs/architecture.md) et les décisions dans [docs/adr/](docs/adr/).

```
apps/api      FastAPI (estimation, agrégats H3, tuiles)
apps/web      Next.js + MapLibre + deck.gl (sprint 5)
pipelines/    DAGs Airflow + jobs PySpark (bronze → silver)
dbt/          Modèles gold (sprint 2)
ml/           Entraînement LightGBM, SHAP, projection 2050 (sprint 3)
infra/        docker-compose : PostGIS, Martin, MLflow, Airflow
docs/         Architecture, ADR, sources, méthodologie, plan des sprints
```

## Démarrer

Prérequis : Docker Desktop, Python 3.10+, GNU make (ou lancer les commandes à la main).

```bash
make up            # PostGIS + Martin + MLflow
make api-install
make api-test
make api-run       # http://localhost:8000/docs
make up-pipeline   # Airflow sur http://localhost:8080
```

## Données et confidentialité
Les données DVF sont utilisées selon leurs conditions : pas de ré-identification,
pas d'indexation par les moteurs de recherche, uniquement des agrégats d'au moins
5 ventes ou des estimations du modèle (voir [ADR 0005](docs/adr/0005-dvf-confidentialite.md)).
