COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml
DBT ?= .venv/Scripts/dbt  # Linux/macOS : make gold DBT=.venv/bin/dbt

.PHONY: help env up up-pipeline down db-roles api-install api-test api-run api-openapi api-latency lint pipe-install pipe-test ingest silver dbt-install gold load model web-install web web-dev web-test web-e2e

help:            ## Liste des commandes
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

env:             ## Crée .env depuis .env.example s'il n'existe pas
	@test -f .env || cp .env.example .env

up: env          ## Lance PostGIS, Martin, MLflow
	$(COMPOSE) up -d

up-pipeline: env ## Lance aussi Airflow (build PySpark)
	$(COMPOSE) --profile pipeline up -d --build

down:            ## Arrête tout
	$(COMPOSE) --profile pipeline down

db-roles:        ## Crée/met à jour les rôles atlas_api et atlas_tiles (base existante)
	$(COMPOSE) exec -T db sh /docker-entrypoint-initdb.d/02-roles.sh

api-install:     ## Installe l'API en mode dev (avec le paquet ML des pipelines)
	cd apps/api && pip install -e "../../pipelines[ml]" && pip install -e ".[dev]"

api-test:        ## Tests API + couverture (seuil 80 %)
	cd apps/api && pytest

api-run:         ## API en local sur :8000
	cd apps/api && uvicorn atlas_api.main:app --reload --no-access-log

api-openapi:     ## Exporte docs/api/openapi.json
	cd apps/api && python -m atlas_api.export_openapi

api-latency:     ## p50/p95 des routes (PostGIS et modèle réels)
	cd apps/api && python scripts/measure_latency.py

lint:            ## Ruff + mypy
	cd apps/api && ruff check . && mypy src tests
	cd pipelines && ruff check . && mypy atlas_pipelines

pipe-install:    ## Installe les pipelines (Java 17 requis pour PySpark)
	cd pipelines && pip install -e ".[dev,spark,ml]"

pipe-test:       ## Tests pipelines + couverture (seuil 80 %)
	cd pipelines && pytest

ingest:          ## Ingestion sans Airflow (ex. make ingest SOURCES="dvf ban")
	cd pipelines && python -m atlas_pipelines.cli $(SOURCES)

silver:          ## Silver DuckDB (ex. make silver SOURCES="ban dpe georisques")
	cd pipelines && python -m atlas_pipelines.silver.run_duck $(SOURCES)

dbt-install:     ## venv dbt séparé (dbt/.venv)
	cd dbt && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt

gold:            ## dbt build -> data/gold_build, promu vers data/gold si tout passe (ATLAS_DATA_DIR absolu)
	mkdir -p "$(ATLAS_DATA_DIR)/gold_build"
	cd dbt && $(DBT) build --profiles-dir .
	cd pipelines && python -m atlas_pipelines.load.promote

load:            ## Charge le gold dans PostGIS (variables POSTGRES_* de .env)
	cd pipelines && python -m atlas_pipelines.load.postgis

model:           ## Modèle de prix + rapport ml/report.md (gold dans ATLAS_DATA_DIR, MLflow ou mlruns/)
	cd pipelines && python -m atlas_pipelines.ml.train --out ../ml

web-install:     ## Installe le front (apps/web, Node 20.9+)
	cd apps/web && npm ci

web:             ## Front en production sur :3000 (API sur :8000 et Martin sur :3001 requis : make api-run, make up)
	cd apps/web && npm run build && npm run start

web-dev:         ## Front en développement sur :3000
	cd apps/web && npm run dev

web-test:        ## Front : types, lint, tests unitaires
	cd apps/web && npm run typecheck && npm run lint && npm test

web-e2e:         ## Front : parcours Playwright (build fait, API et Martin lancés)
	cd apps/web && npx playwright test
