import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.types import Message, Receive, Scope, Send

from atlas_api.config import Settings
from atlas_api.estimator import Estimator
from atlas_api.geocode import GeocodedPoint
from atlas_api.main import QuietErrorsMiddleware, create_app
from tests.conftest import FakeGeocoder, FakeRepository, make_client


def test_health_returns_envelope(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"] == {
        "status": "ok",
        "database": "ok",
        "model": "ok",
        "departements": ["33", "13"],
    }
    assert res.headers["cache-control"] == "no-store"


def test_health_is_503_when_database_down(settings: Settings) -> None:
    app_client = make_client(settings, repository=FakeRepository(up=False), estimator=None,
                             geocoder=FakeGeocoder(), load_model=False)
    with app_client as c:
        res = c.get("/health")
    assert res.status_code == 503
    assert res.json()["data"]["database"] == "indisponible"
    assert res.json()["data"]["status"] == "degrade"


def test_health_reports_missing_model(settings: Settings) -> None:
    with make_client(settings, repository=FakeRepository(), geocoder=FakeGeocoder(),
                     load_model=False) as c:
        data = c.get("/health").json()["data"]
    assert data["model"] == "indisponible"
    assert data["status"] == "degrade"


def test_every_response_is_noindex(client: TestClient) -> None:
    assert client.get("/health").headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get("/communes?q=bo").headers["x-robots-tag"] == "noindex, nofollow"


def test_robots_disallows_all(client: TestClient) -> None:
    res = client.get("/robots.txt")
    assert res.headers["content-type"].startswith("text/plain")
    assert "Disallow: /" in res.text


def test_unknown_route_is_404_envelope(client: TestClient) -> None:
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.json() == {"success": False, "data": None, "error": "Ressource introuvable",
                          "meta": {"total": None, "page": None, "limit": None, "sources": []}}


def test_post_is_rejected(client: TestClient) -> None:
    assert client.post("/communes?q=bo").status_code == 405


def test_cors_only_allows_configured_origin(client: TestClient) -> None:
    allowed = client.get("/health", headers={"Origin": "http://a"})
    denied = client.get("/health", headers={"Origin": "http://evil"})
    assert allowed.headers.get("access-control-allow-origin") == "http://a"
    assert "access-control-allow-origin" not in denied.headers


def test_cors_preflight_refuses_put(client: TestClient) -> None:
    res = client.options(
        "/communes",
        headers={"Origin": "http://a", "Access-Control-Request-Method": "PUT"},
    )
    assert res.status_code == 400


def test_cors_preflight_allows_json_post_for_estimate(client: TestClient) -> None:
    res = client.options(
        "/estimate",
        headers={"Origin": "http://a", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://a"


def test_estimate_error_logs_no_traceback_nor_message(
    settings: Settings, estimator: Estimator, caplog: pytest.LogCaptureFixture
) -> None:
    """Starlette relance l'exception après la 500 : rien ne doit la journaliser en entier."""

    class LeakyGeocoder(FakeGeocoder):
        def geocode(self, address: str) -> GeocodedPoint:
            raise RuntimeError(f"échec pour {address}")

    app = create_app(settings, repository=FakeRepository(), estimator=estimator,
                     geocoder=LeakyGeocoder())
    with caplog.at_level(logging.DEBUG), TestClient(app) as c:  # relance activée
        res = c.post("/estimate", json={"address": "12 rue Secrète 33000 Bordeaux",
                                        "type_local": "Maison", "surface": 90, "pieces": 4})
    assert res.status_code == 500
    assert res.json()["error"] == "Erreur interne"
    assert "Secr" not in res.text
    assert caplog.records, "le type d'erreur doit rester journalisé"
    for record in caplog.records:
        assert record.exc_info is None and record.exc_text is None
        assert "Secr" not in record.getMessage()
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


def test_other_routes_keep_traceback(settings: Settings) -> None:
    class Boom(FakeRepository):
        def search_communes(self, prefix: str) -> list:  # type: ignore[type-arg]
            raise RuntimeError("panne")

    app = create_app(settings, repository=Boom(), geocoder=FakeGeocoder(), load_model=False)
    with TestClient(app) as c, pytest.raises(RuntimeError, match="panne"):
        c.get("/communes?q=bo")


def test_quiet_middleware_answers_500_if_nothing_sent() -> None:
    async def failing(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("12 rue Secrète")

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "http.request"}

    asyncio.run(
        QuietErrorsMiddleware(failing)({"type": "http", "path": "/estimate"}, receive, send)
    )
    assert sent[0]["status"] == 500
    assert b"Secr" not in sent[1]["body"]


def test_unhandled_error_does_not_leak(settings: Settings) -> None:
    class Boom(FakeRepository):
        def search_communes(self, prefix: str) -> list:  # type: ignore[type-arg]
            raise RuntimeError("secret interne /etc/passwd")

    with TestClient(
        make_client(settings, repository=Boom(), geocoder=FakeGeocoder(), load_model=False).app,
        raise_server_exceptions=False,
    ) as c:
        res = c.get("/communes?q=bo")
    assert res.status_code == 500
    assert res.json()["error"] == "Erreur interne"
    assert "secret" not in res.text


def test_access_log_has_no_query_string(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="atlas_api.access"):
        client.get("/communes?q=bordeaux-secret")
    lines = [r.getMessage() for r in caplog.records if r.name == "atlas_api.access"]
    assert lines and lines[-1].startswith("GET /communes 200")
    assert "secret" not in " ".join(lines)


@pytest.mark.parametrize("bad", ["", "  ,", "9999", "AB"])
def test_invalid_departements_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(atlas_departements=bad)


def test_corsica_codes_accepted() -> None:
    assert Settings(atlas_departements="2A, 2B").departements == ("2A", "2B")


@pytest.mark.parametrize("bad", ["60", "0/minute", "10/day", "abc"])
def test_invalid_rate_limit_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(api_rate_limit=bad)


def test_rate_limit_parsed() -> None:
    assert Settings(api_rate_limit="60/minute").rate_limit == (60, 60.0)
    assert Settings(api_rate_limit="5 / second").rate_limit == (5, 1.0)


def test_ban_url_must_be_https() -> None:
    with pytest.raises(ValidationError):
        Settings(api_ban_url="http://api-adresse.data.gouv.fr/search/")


def test_conninfo_is_read_only_with_timeout() -> None:
    secret = SecretStr("pw")
    info = Settings(postgres_password=secret, api_statement_timeout_ms=1234).conninfo()
    assert "default_transaction_read_only=on" in info
    assert "statement_timeout=1234" in info
    assert "pw" not in repr(Settings(postgres_password=secret))
