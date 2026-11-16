"""Configuration de déploiement : rôles PostgreSQL au moindre privilège, ports, secrets.

Vérifications statiques (sans Docker). Le comportement réel des rôles sur PostGIS est
couvert par test_integration_pg.py (ignoré si la base est injoignable).
"""

import re

import pytest

from tests.conftest import REPO_ROOT

INFRA = REPO_ROOT / "infra"
ROLES = (INFRA / "db" / "roles.sql").read_text(encoding="utf-8")
INIT_SH = (INFRA / "db" / "02-roles.sh").read_text(encoding="utf-8")
COMPOSE = (INFRA / "docker-compose.yml").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")


def _service(name: str) -> str:
    """Bloc YAML d'un service (jusqu'au service suivant, indentation 2)."""
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", COMPOSE, re.M | re.S)
    assert m, name
    return m.group(1)


def _sql(pattern: str) -> list[str]:
    """Instructions qui commencent en début de ligne par `pattern` (→ « ; » ou « \\gexec »)."""
    return re.findall(rf"^{pattern}.*?(?:;|\\gexec)", ROLES, re.M | re.S)


def test_roles_are_not_superusers_and_read_only() -> None:
    for role in ("atlas_api", "atlas_tiles"):
        (alter,) = _sql(f"ALTER ROLE {role} WITH")
        for flag in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION",
                     "NOBYPASSRLS", "LOGIN"):
            assert flag in alter, (role, flag)
        assert f"ALTER ROLE {role} SET default_transaction_read_only = on" in ROLES
    assert not re.search(r"(?<!NO)SUPERUSER", ROLES.replace("NOSUPERUSER", ""))
    assert "GRANT ALL" not in ROLES.upper()
    assert not re.search(r"GRANT\s+(INSERT|UPDATE|DELETE|TRUNCATE)", ROLES, re.I)


def test_api_reads_gold_only_and_tiles_three_tables() -> None:
    grants = _sql("GRANT SELECT") + _sql(r"SELECT format\('GRANT SELECT")
    api = [g for g in grants if "atlas_api" in g]
    tiles = [g for g in grants if "atlas_tiles" in g]
    assert any("ALL TABLES IN SCHEMA gold" in g for g in api)
    assert all("gold" in g for g in api)
    assert len(tiles) == 1 and "ALL TABLES" not in tiles[0]
    assert "ARRAY['agg_hex', 'dim_commune', 'dim_iris']" in tiles[0]
    assert "fact_transactions" not in " ".join(tiles)


def test_roles_script_is_idempotent_and_has_no_secret() -> None:
    assert "WHERE NOT EXISTS (SELECT 1 FROM pg_roles" in ROLES  # pas de CREATE ROLE nu
    assert "CREATE SCHEMA IF NOT EXISTS gold" in ROLES
    assert "PASSWORD :'api_password'" in ROLES and "PASSWORD :'tiles_password'" in ROLES
    assert not re.search(r"PASSWORD\s+'", ROLES)  # aucun mot de passe littéral
    assert "ON_ERROR_STOP" in ROLES and "length(:'api_password') < 16" in ROLES
    assert "$ATLAS_API_DB_PASSWORD" in INIT_SH and "$ATLAS_TILES_DB_PASSWORD" in INIT_SH
    assert "\r" not in INIT_SH  # exécuté par sh dans un conteneur Linux


def test_compose_wires_least_privilege_roles() -> None:
    api, tiles, airflow = _service("api"), _service("tiles"), _service("airflow")
    assert "POSTGRES_USER: atlas_api" in api
    assert "POSTGRES_PASSWORD: ${ATLAS_API_DB_PASSWORD}" in api
    assert "postgresql://atlas_tiles:${ATLAS_TILES_DB_PASSWORD}@db" in tiles
    assert "${POSTGRES_PASSWORD}" not in api and "${POSTGRES_PASSWORD}" not in tiles
    assert "POSTGRES_USER: ${POSTGRES_USER}" in airflow  # le chargeur garde le propriétaire
    assert "FORWARDED_ALLOW_IPS: ${API_FORWARDED_ALLOW_IPS:-127.0.0.1}" in api
    assert "02-roles.sh:/docker-entrypoint-initdb.d/02-roles.sh:ro" in _service("db")


@pytest.mark.parametrize("service", ["db", "tiles", "api", "mlflow", "airflow"])
def test_published_ports_bound_to_loopback(service: str) -> None:
    ports = re.findall(r'ports:\s*\["([^"]+)"\]', _service(service))
    assert ports, service
    assert all(p.startswith("127.0.0.1:") for p in ports), (service, ports)


def test_env_example_has_placeholders_only() -> None:
    values = dict(
        line.split("=", 1) for line in ENV_EXAMPLE.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for key in ("ATLAS_API_DB_PASSWORD", "ATLAS_TILES_DB_PASSWORD", "POSTGRES_PASSWORD"):
        assert values[key].startswith("change-me"), key
    assert values["ATLAS_API_DB_PASSWORD"] != values["ATLAS_TILES_DB_PASSWORD"]
    assert len(values["ATLAS_API_DB_PASSWORD"]) >= 16  # le script refuse plus court
    assert values["API_FORWARDED_ALLOW_IPS"] == "127.0.0.1"
