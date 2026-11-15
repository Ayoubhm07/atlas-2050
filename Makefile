COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml

.PHONY: help env up up-pipeline down api-install api-test api-run lint pipe-install pipe-test ingest

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

api-install:     ## Installe l'API en mode dev
	cd apps/api && pip install -e ".[dev]"

api-test:        ## Tests API + couverture (seuil 80 %)
	cd apps/api && pytest

api-run:         ## API en local sur :8000
	cd apps/api && uvicorn atlas_api.main:app --reload

lint:            ## Ruff + mypy
	cd apps/api && ruff check . && mypy src
	cd pipelines && ruff check . && mypy atlas_pipelines

pipe-install:    ## Installe les pipelines (Java 17 requis pour PySpark)
	cd pipelines && pip install -e ".[dev,spark]"

pipe-test:       ## Tests pipelines + couverture (seuil 80 %)
	cd pipelines && pytest

ingest:          ## Ingestion sans Airflow (ex. make ingest SOURCES="dvf ban")
	cd pipelines && python -m atlas_pipelines.cli $(SOURCES)
