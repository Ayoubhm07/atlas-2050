# Image de l'API ATLAS 2050. Contexte de build : racine du dépôt (paquet pipelines requis).
#   docker build -f apps/api/Dockerfile -t atlas-api .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/atlas
COPY pipelines/pyproject.toml pipelines/
COPY pipelines/atlas_pipelines pipelines/atlas_pipelines
RUN pip install "./pipelines[ml]"
COPY apps/api/pyproject.toml apps/api/
COPY apps/api/src apps/api/src
RUN pip install ./apps/api && useradd --system --uid 10001 atlas
USER atlas
EXPOSE 8000
# IP client : uvicorn ne remplace l'IP de la socket par X-Forwarded-For que si le pair est
# dans FORWARDED_ALLOW_IPS (variable native d'uvicorn). Défaut 127.0.0.1 ; y mettre l'IP du
# proxy de confiance, jamais « * » si l'API est joignable sans lui (docs/api/README.md).
ENV FORWARDED_ALLOW_IPS=127.0.0.1
# --no-access-log : AccessLogMiddleware journalise sans chaîne de requête.
# Pas de --forwarded-allow-ips : l'option écraserait la variable d'environnement.
CMD ["uvicorn", "atlas_api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--proxy-headers"]
