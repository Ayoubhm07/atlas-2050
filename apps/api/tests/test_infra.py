"""Géocodeur BAN, limiteur de débit, requêtes SQL nommées."""

import json
import logging
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import queries
from atlas_api.config import Settings
from atlas_api.geocode import AddressNotFoundError, BanGeocoder, GeocodingError
from atlas_api.ratelimit import TokenBucketLimiter, client_key
from tests.conftest import REPO_ROOT, FakeGeocoder, FakeRepository, make_client

ADDRESS = "8 boulevard du Port 80000 Amiens"


def _feature(score: float = 0.9, coords: object = (2.29, 49.89)) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": {"score": score, "citycode": "80021", "label": ADDRESS},
            }
        ],
    }


def _geocoder(responses: list[httpx.Response | Exception], retries: int = 2) -> BanGeocoder:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = responses[min(len(seen) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    geo = BanGeocoder("https://ban.test/search/", 1.0, retries, 0.5, httpx.MockTransport(handler))
    geo.seen = seen  # type: ignore[attr-defined]
    return geo


# --- BAN ------------------------------------------------------------------------------


def test_ban_success_returns_point_only() -> None:
    geo = _geocoder([httpx.Response(200, json=_feature())])
    point = geo.geocode(ADDRESS)
    assert (point.lon, point.lat, point.score, point.citycode) == (2.29, 49.89, 0.9, "80021")
    req = geo.seen[0]  # type: ignore[attr-defined]
    assert req.url.params["limit"] == "1"
    assert req.headers["user-agent"].startswith("atlas-2050-api")
    geo.close()


def test_ban_retries_then_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    geo = _geocoder([httpx.ConnectTimeout("t"), httpx.Response(503),
                     httpx.Response(200, json=_feature())])
    with caplog.at_level(logging.DEBUG):
        assert geo.geocode(ADDRESS).citycode == "80021"
    assert len(geo.seen) == 3  # type: ignore[attr-defined]
    assert all("Amiens" not in r.getMessage() and "boulevard" not in r.getMessage()
               for r in caplog.records)


def test_ban_gives_up_after_retries() -> None:
    geo = _geocoder([httpx.Response(502)], retries=1)
    with pytest.raises(GeocodingError):
        geo.geocode(ADDRESS)
    assert len(geo.seen) == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, json=_feature(score=0.2)), AddressNotFoundError),
        (httpx.Response(200, json={"features": []}), AddressNotFoundError),
        (httpx.Response(400, json={"message": "q"}), AddressNotFoundError),
        (httpx.Response(200, content=b"<html>"), GeocodingError),
        (httpx.Response(200, json={"features": [{"geometry": {}}]}), GeocodingError),
        (httpx.Response(200, json=_feature(coords=(200.0, 49.0))), GeocodingError),
        (httpx.Response(403), GeocodingError),
    ],
)
def test_ban_validates_response(response: httpx.Response, error: type[Exception]) -> None:
    with pytest.raises(error):
        _geocoder([response]).geocode(ADDRESS)


def test_ban_rejects_non_point_geometry() -> None:
    body = _feature()
    body["features"][0]["geometry"]["type"] = "LineString"  # type: ignore[index]
    with pytest.raises(GeocodingError):
        _geocoder([httpx.Response(200, content=json.dumps(body).encode())]).geocode(ADDRESS)


# --- limiteur ---------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_ban_does_not_retry_on_429() -> None:
    geo = _geocoder([httpx.Response(429), httpx.Response(200, json=_feature())], retries=3)
    with pytest.raises(GeocodingError, match="429"):
        geo.geocode(ADDRESS)
    assert len(geo.seen) == 1  # type: ignore[attr-defined]


def test_ban_overall_deadline_caps_attempts_and_timeouts() -> None:
    clock = Clock()
    timeouts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        clock.now += 2.0  # chaque tentative « dure » 2 s
        return httpx.Response(503)

    geo = BanGeocoder("https://ban.test/search/", 2.5, 5, 0.5, httpx.MockTransport(handler),
                      deadline_s=3.0, clock=clock)
    with pytest.raises(GeocodingError):
        geo.geocode(ADDRESS)
    assert timeouts == [2.5, 1.0]  # 2e tentative bornée au temps restant, pas de 3e
    assert clock.now == 4.0


@pytest.mark.parametrize(("deadline", "cache"), [(0.0, 1), (3.5, 1), (1.0, -1)])
def test_ban_rejects_bad_limits(deadline: float, cache: int) -> None:
    with pytest.raises(ValueError):
        BanGeocoder("https://ban.test/", 1.0, 0, 0.5, deadline_s=deadline, cache_size=cache)


def test_ban_lru_cache_reuses_points_and_evicts() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["q"])
        return httpx.Response(200, json=_feature())

    geo = BanGeocoder("https://ban.test/search/", 1.0, 0, 0.5, httpx.MockTransport(handler),
                      cache_size=2)
    geo.geocode("1 rue A 80000 Amiens")
    geo.geocode("  1 RUE a   80000 amiens ")  # même adresse normalisée : cache
    geo.geocode("2 rue B 80000 Amiens")
    geo.geocode("1 rue A 80000 Amiens")  # rafraîchit A
    geo.geocode("3 rue C 80000 Amiens")  # évince B (le moins récent)
    geo.geocode("2 rue B 80000 Amiens")
    assert calls == ["1 rue A 80000 Amiens", "2 rue B 80000 Amiens", "3 rue C 80000 Amiens",
                     "2 rue B 80000 Amiens"]


def test_ban_cache_skips_failures_and_can_be_disabled() -> None:
    geo = _geocoder([httpx.Response(200, json={"features": []}),
                     httpx.Response(200, json=_feature())])
    with pytest.raises(AddressNotFoundError):
        geo.geocode(ADDRESS)
    assert geo.geocode(ADDRESS).citycode == "80021"  # l'échec n'a pas été mis en cache
    off = BanGeocoder("https://ban.test/search/", 1.0, 0, 0.5,
                      httpx.MockTransport(lambda r: httpx.Response(200, json=_feature())),
                      cache_size=0)
    off.geocode(ADDRESS)
    assert off._cache == {}


def test_token_bucket_refills() -> None:
    clock = Clock()
    lim = TokenBucketLimiter(2, 60.0, clock=clock)
    assert lim.acquire("a") == 0 and lim.acquire("a") == 0
    wait = lim.acquire("a")
    assert wait == pytest.approx(30.0)
    assert lim.acquire("b") == 0  # seau indépendant par IP
    clock.now = 30.0
    assert lim.acquire("a") == 0


def test_token_bucket_cost_and_eviction() -> None:
    lim = TokenBucketLimiter(5, 5.0, max_keys=2, clock=Clock())
    assert lim.acquire("a", cost=5) == 0
    assert lim.acquire("a", cost=5) > 0
    lim.acquire("b")
    lim.acquire("c")  # "a" oublié (le moins récent)
    assert lim.acquire("a", cost=5) == 0


def test_token_bucket_validates() -> None:
    with pytest.raises(ValueError):
        TokenBucketLimiter(0, 1.0)


def test_client_key_never_reads_forwarded_header() -> None:
    scope = {"client": ("10.0.0.1", 1), "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")]}
    assert client_key(scope) == "10.0.0.1"
    assert client_key({"headers": []}) == "inconnu"
    assert client_key({"client": ("testclient", 1)}) == "testclient"


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("::ffff:192.0.2.7", "192.0.2.7"),
        ("192.0.2.7", "192.0.2.7"),
    ],
)
def test_client_key_groups_ipv6_by_64(host: str, key: str) -> None:
    assert client_key({"client": (host, 1)}) == key


def test_rate_limit_ignores_spoofed_forwarded_for() -> None:
    cfg = Settings(api_rate_limit="2/minute", api_cors_origins="http://a")
    with make_client(cfg, repository=FakeRepository(), geocoder=FakeGeocoder(),
                     load_model=False) as c:
        codes = [
            c.get("/communes?q=bo", headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
            for i in range(3)
        ]
    assert codes == [200, 200, 429]


def test_dockerfile_forwarded_ips_come_from_env() -> None:
    text = (REPO_ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV FORWARDED_ALLOW_IPS=127.0.0.1" in text
    cmd = text[text.index("CMD"):]
    assert "--proxy-headers" in cmd and "--forwarded-allow-ips" not in cmd
    assert "--no-access-log" in cmd


def test_rate_limit_returns_429_envelope() -> None:
    cfg = Settings(api_rate_limit="2/minute", api_cors_origins="http://a")
    with make_client(cfg, repository=FakeRepository(), geocoder=FakeGeocoder(),
                     load_model=False) as c:
        codes = [c.get("/communes?q=bo").status_code for _ in range(3)]
        res = c.get("/communes?q=bo", headers={"Origin": "http://a"})
        health = c.get("/health")
    assert codes == [200, 200, 429]
    assert res.status_code == 429
    assert res.json() == {"success": False, "data": None,
                          "error": "Trop de requêtes : réessayer plus tard",
                          "meta": {"total": None, "page": None, "limit": None, "sources": []}}
    assert int(res.headers["retry-after"]) >= 1
    assert res.headers["access-control-allow-origin"] == "http://a"
    assert health.status_code == 200  # santé exemptée


def test_estimate_costs_more_tokens(client: TestClient) -> None:
    cfg = Settings(api_rate_limit="6/minute")
    with make_client(cfg, repository=FakeRepository(), geocoder=FakeGeocoder(),
                     load_model=False) as c:
        first = c.get("/estimate", params={"lat": 44.8, "lon": -0.5, "type_local": "Maison",
                                           "surface": 90, "pieces": 4})
        second = c.get("/estimate", params={"lat": 44.8, "lon": -0.5, "type_local": "Maison",
                                            "surface": 90, "pieces": 4})
    assert first.status_code == 503  # modèle absent, mais jetons consommés
    assert second.status_code == 429


# --- SQL ---------------------------------------------------------------------------------


EXPECTED = {
    "hex_aggregates": 9,
    "commune_search": 1,
    "point_lookup": 2,
    "commune_transaction_stats": 1,
    "commune_risks": 1,
    "valuation_date": 0,
    "neighbour_sales": 5,
}


def test_all_queries_present_and_parameterised() -> None:
    parsed = queries.parse(queries.raw_text())
    assert set(parsed) == set(EXPECTED)
    for name, n in EXPECTED.items():
        sql = queries.get(name)
        used = {int(x) for x in re.findall(r"%\(p(\d+)\)s", sql)}
        assert used == set(range(1, n + 1)), name
        assert "$" not in sql


def test_to_psycopg_escapes_literal_percent() -> None:
    assert queries.to_psycopg("a LIKE $1 || '%'") == "a LIKE %(p1)s || '%%'"
    assert queries.bind("x", 2) == {"p1": "x", "p2": 2}


def test_sql_docs_in_sync() -> None:
    docs = (REPO_ROOT / "docs" / "sql" / "api_queries.sql").read_text(encoding="utf-8")
    assert docs == queries.raw_text()


def test_no_query_exposes_sale_identifiers_except_internal() -> None:
    parsed = queries.parse(queries.raw_text())
    for name, sql in parsed.items():
        if name != "neighbour_sales":  # usage interne au calcul, jamais renvoyé
            assert "id_mutation" not in sql and "id_parcelle" not in sql, name


def test_openapi_export_is_up_to_date() -> None:
    from atlas_api.export_openapi import render

    path = REPO_ROOT / "docs" / "api" / "openapi.json"
    assert path.is_file(), "lancer python -m atlas_api.export_openapi"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(render())


def test_openapi_documents_every_route(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert set(spec["paths"]) >= {"/communes", "/hex", "/communes/{code}/stats",
                                  "/communes/{code}/risques", "/estimate", "/health"}
    for path, ops in spec["paths"].items():
        assert ops["get"].get("summary"), path
