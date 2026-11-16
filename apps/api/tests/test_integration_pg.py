"""Intégration contre le PostGIS réel (gold chargé par `make load`).

Ignorés proprement si la base est injoignable (CI sans service) ; l'estimation avec le
vrai modèle est ignorée si ml/models/lgb_global.txt est absent (non versionné).
"""

import datetime as dt
from collections.abc import Iterator

import h3
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from atlas_api.config import Settings
from atlas_api.db import PgRepository, open_pool
from atlas_api.main import create_app
from tests.conftest import BORDEAUX, REPO_ROOT, FakeGeocoder

pytestmark = pytest.mark.integration
MODEL = REPO_ROOT / "ml" / "models" / "lgb_global.txt"
BBOX = "-0.75,44.75,-0.45,44.95"


@pytest.fixture(scope="module")
def pg_settings() -> Settings:
    cfg = Settings(api_rate_limit="100000/minute", api_cors_origins="http://a")
    try:
        with psycopg.connect(cfg.conninfo(), connect_timeout=2) as conn:
            n = conn.execute("SELECT count(*) FROM gold.agg_hex").fetchone()
    except psycopg.Error as exc:
        pytest.skip(f"PostGIS injoignable ou gold absent : {type(exc).__name__}")
    if not n or not n[0]:
        pytest.skip("gold.agg_hex vide")
    return cfg


@pytest.fixture(scope="module")
def pg_client(pg_settings: Settings) -> Iterator[TestClient]:
    app = create_app(pg_settings, geocoder=FakeGeocoder(), load_model=MODEL.is_file())
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def pg_repo(pg_settings: Settings) -> Iterator[PgRepository]:
    pool = open_pool(pg_settings.conninfo(), 1, 2, 5.0)
    yield PgRepository(pool)
    pool.close()


def test_health_checks_database(pg_client: TestClient) -> None:
    res = pg_client.get("/health")
    assert res.status_code == 200
    assert res.json()["data"]["database"] == "ok"


@pytest.mark.parametrize("q", ["étau", "Étau", "ETAU", "etau"])
def test_search_accents_and_case(pg_client: TestClient, q: str) -> None:
    data = pg_client.get("/communes", params={"q": q}).json()["data"]
    assert data and all(c["nom_commune"].lower().startswith("étau") for c in data)


def test_search_wildcards_are_literal(pg_client: TestClient) -> None:
    assert pg_client.get("/communes", params={"q": "%%"}).json()["data"] == []
    assert pg_client.get("/communes", params={"q": "__"}).json()["data"] == []


def test_hex_respects_privacy_floor(pg_client: TestClient) -> None:
    res = pg_client.get("/hex", params={"bbox": BBOX, "res": 9, "annee": "2024"})
    assert res.status_code == 200, res.text
    cells = res.json()["data"]
    assert cells
    assert all(c["n_ventes"] >= 5 and c["prix_m2_median"] % 10 == 0 for c in cells)
    assert all(h3.get_resolution(c["h3"]) == 9 for c in cells)
    etag = res.headers["etag"]
    again = pg_client.get("/hex", params={"bbox": BBOX, "res": 9, "annee": "2024"},
                          headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_hex_row_cap_enforced(pg_settings: Settings) -> None:
    cfg = pg_settings.model_copy(update={"api_hex_max_rows": 5})
    with TestClient(create_app(cfg, geocoder=FakeGeocoder(), load_model=False)) as c:
        res = c.get("/hex", params={"bbox": BBOX, "res": 9})
    assert res.status_code == 400


def test_commune_stats_privacy_rules(pg_client: TestClient) -> None:
    groupes = pg_client.get("/communes/33063/stats").json()["data"]["groupes"]
    assert groupes
    for g in groupes:
        assert g["n_ventes"] >= 5
        assert g["prix_m2_median"] % 10 == 0
        assert g["surface_mediane"] % 5 == 0  # médiane arrondie à 5 m², pas une moyenne
        if g["n_ventes"] < 11:
            assert g["prix_m2_q1"] is None and g["prix_m2_q3"] is None


def test_commune_risks_and_404(pg_client: TestClient) -> None:
    body = pg_client.get("/communes/33063/risques").json()["data"]
    assert body["nom_commune"] == "Bordeaux"
    assert pg_client.get("/communes/99999/risques").status_code == 404
    assert pg_client.get("/communes/99999/stats").status_code == 404


def test_reference_sales_strictly_before_valuation(pg_repo: PgRepository) -> None:
    valuation = pg_repo.valuation_date()
    assert valuation is not None
    cell = h3.latlng_to_cell(BORDEAUX[1], BORDEAUX[0], 7)
    cells = sorted(h3.grid_disk(cell, 1))
    sales = pg_repo.reference_sales("Maison", cells, valuation, 30, 500)
    assert sales and all(s.date_mutation < valuation for s in sales)
    ring = [s for s in sales if s.h3_r7 in cells]
    assert ring and len(ring) <= 30 * len(cells)
    earlier = valuation - dt.timedelta(days=60)
    assert all(s.date_mutation < earlier
               for s in pg_repo.reference_sales("Maison", cells, earlier, 30, 500))


def test_point_outside_perimeter(pg_repo: PgRepository) -> None:
    assert pg_repo.point_context(2.35, 48.85) is None  # Paris : hors gold


def test_database_errors_become_503(pg_settings: Settings) -> None:
    cfg = pg_settings.model_copy(update={"postgres_port": 1, "api_db_timeout_s": 1.0})
    with TestClient(create_app(cfg, geocoder=FakeGeocoder(), load_model=False)) as c:
        assert c.get("/health").status_code == 503
        res = c.get("/communes/33063/risques")
    assert res.status_code == 503
    assert res.json()["error"] == "Base de données indisponible"


@pytest.mark.skipif(not MODEL.is_file(), reason="modèle sauvegardé absent (ml/models)")
def test_estimate_with_real_model(pg_client: TestClient) -> None:
    params = {"lat": BORDEAUX[1], "lon": BORDEAUX[0], "type_local": "Appartement",
              "surface": 60, "pieces": 3, "dpe": "F"}
    res = pg_client.get("/estimate", params=params)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    p = data["prix_m2"]
    assert 1500 < p["p50"] < 12000 and p["p10"] < p["p50"] < p["p90"]
    ids = {s["id"]: s for s in data["scenarios"]}
    assert ids["climat_rcp85"]["statut"] == "indisponible (DRIAS)"
    assert ids["renovation_D"]["statut"] == "calcule"
    assert data["facteurs"]
    assert data["localisation"]["code_insee"] == "33063"


# --- rôles au moindre privilège (infra/db/roles.sql) ----------------------------------


def _secret(key: str) -> str | None:
    """Variable d'environnement, sinon ligne de .env (comme docker compose --env-file)."""
    import os

    if key in os.environ:
        return os.environ[key]
    env = REPO_ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return None


def _role_conn(pg_settings: Settings, role: str, env_key: str) -> psycopg.Connection:
    password = _secret(env_key)
    if not password:
        pytest.skip(f"{env_key} absent : rôles non configurés")
    info = pg_settings.model_copy(
        update={"postgres_user": role, "postgres_password": SecretStr(password)}
    ).conninfo()
    try:
        return psycopg.connect(info, connect_timeout=2, autocommit=True)
    except psycopg.Error as exc:
        pytest.skip(f"rôle {role} injoignable (make db-roles ?) : {type(exc).__name__}")


@pytest.mark.parametrize(
    ("role", "env_key"),
    [("atlas_api", "ATLAS_API_DB_PASSWORD"), ("atlas_tiles", "ATLAS_TILES_DB_PASSWORD")],
)
def test_reader_roles_are_read_only_non_superusers(
    pg_settings: Settings, role: str, env_key: str
) -> None:
    with _role_conn(pg_settings, role, env_key) as conn:
        row = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
        assert row == (False,)
        assert conn.execute("SHOW default_transaction_read_only").fetchone() == ("on",)
        assert conn.execute("SELECT count(*) FROM gold.agg_hex").fetchone()
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM gold.agg_hex WHERE false")
        # même en levant la lecture seule (paramètre de session), aucun droit d'écriture
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM gold.agg_hex WHERE false")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE public.atlas_role_probe (x int)")


def test_tiles_role_cannot_read_sales(pg_settings: Settings) -> None:
    with _role_conn(pg_settings, "atlas_tiles", "ATLAS_TILES_DB_PASSWORD") as conn:
        for table in ("dim_commune", "dim_iris"):
            conn.execute(f"SELECT 1 FROM gold.{table} LIMIT 1")  # noqa: S608 - nom fixe
        for table in ("fact_transactions", "fact_risques_commune"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"SELECT 1 FROM gold.{table} LIMIT 1")  # noqa: S608 - nom fixe


def test_api_role_reads_whole_gold(pg_settings: Settings) -> None:
    with _role_conn(pg_settings, "atlas_api", "ATLAS_API_DB_PASSWORD") as conn:
        for table in ("fact_transactions", "fact_risques_commune", "dim_iris"):
            conn.execute(f"SELECT 1 FROM gold.{table} LIMIT 1")  # noqa: S608 - nom fixe
