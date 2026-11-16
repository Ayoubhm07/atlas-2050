#!/bin/sh
# Premier démarrage du conteneur PostGIS (docker-entrypoint-initdb.d) : crée les rôles
# en lecture seule atlas_api et atlas_tiles (roles.sql). Base existante : make db-roles.
set -eu
: "${ATLAS_API_DB_PASSWORD:?ATLAS_API_DB_PASSWORD manquant (.env)}"
: "${ATLAS_TILES_DB_PASSWORD:?ATLAS_TILES_DB_PASSWORD manquant (.env)}"
psql -v ON_ERROR_STOP=1 --no-psqlrc \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v api_password="$ATLAS_API_DB_PASSWORD" \
    -v tiles_password="$ATLAS_TILES_DB_PASSWORD" \
    -f /opt/atlas-db/roles.sql
