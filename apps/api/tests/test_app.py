import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from atlas_api.config import Settings
from atlas_api.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(atlas_departements="33,13", api_cors_origins="http://a")))


def test_health_returns_envelope(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"] == {"status": "ok", "departements": ["33", "13"]}


def test_every_response_is_noindex(client: TestClient) -> None:
    assert client.get("/health").headers["x-robots-tag"] == "noindex, nofollow"


def test_robots_disallows_all(client: TestClient) -> None:
    res = client.get("/robots.txt")
    assert res.headers["content-type"].startswith("text/plain")
    assert "Disallow: /" in res.text


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/nope").status_code == 404


def test_cors_only_allows_configured_origin(client: TestClient) -> None:
    allowed = client.get("/health", headers={"Origin": "http://a"})
    denied = client.get("/health", headers={"Origin": "http://evil"})
    assert allowed.headers.get("access-control-allow-origin") == "http://a"
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.parametrize("bad", ["", "  ,", "9999", "AB"])
def test_invalid_departements_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(atlas_departements=bad)


def test_corsica_codes_accepted() -> None:
    assert Settings(atlas_departements="2A, 2B").departements == ("2A", "2B")
