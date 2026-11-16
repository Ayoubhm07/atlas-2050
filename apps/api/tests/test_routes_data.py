import pytest
from fastapi.testclient import TestClient

from atlas_api.db import HexFilter, escape_like
from atlas_api.routes import normalise_query
from tests.conftest import FakeRepository

BBOX = "-0.75,44.75,-0.45,44.95"


# --- /communes ------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["ÉTAU", "étau", "Etau", "  etau "])
def test_search_normalises_case_and_accents(
    client: TestClient, repo: FakeRepository, raw: str
) -> None:
    res = client.get("/communes", params={"q": raw})
    assert res.status_code == 200
    body = res.json()
    assert [c["nom_commune"] for c in body["data"]] == ["Étauliers"]
    assert body["meta"]["total"] == 1
    assert repo.calls[-1] == ("search", "etau")


def test_normalise_query() -> None:
    assert normalise_query("  Saint-Émilion  ") == "saint-emilion"
    assert normalise_query("LÈGE   Cap") == "lege cap"


def test_like_wildcards_are_escaped() -> None:
    assert escape_like("a%b_c\\") == "a\\%b\\_c\\\\"


@pytest.mark.parametrize("q", ["", "a", "x" * 65])
def test_search_rejects_bad_length(client: TestClient, q: str) -> None:
    res = client.get("/communes", params={"q": q})
    assert res.status_code == 422
    assert res.json()["success"] is False


def test_search_rejects_only_accents(client: TestClient) -> None:
    res = client.get("/communes", params={"q": " ́ "})
    assert res.status_code == 400


def test_search_has_etag_and_304(client: TestClient) -> None:
    first = client.get("/communes", params={"q": "bord"})
    etag = first.headers["etag"]
    assert etag.startswith('W/"')
    assert first.headers["cache-control"] == "public, max-age=3600"
    again = client.get("/communes", params={"q": "bord"}, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    other = client.get("/communes", params={"q": "bord"}, headers={"If-None-Match": 'W/"x"'})
    assert other.status_code == 200


# --- /hex ---------------------------------------------------------------------------


def test_hex_returns_cells_with_filters(client: TestClient, repo: FakeRepository) -> None:
    res = client.get("/hex", params={"bbox": BBOX, "res": 9, "type": "Maison", "dpe": "G",
                                     "annee": "2024"})
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 3
    assert body["meta"]["limit"] == 3
    assert "etag" in res.headers
    f = repo.calls[-1][1]
    assert isinstance(f, HexFilter)
    assert (f.res, f.type_local, f.dpe, f.annee) == (9, "Maison", "G", "2024")
    assert f.bbox == (-0.75, 44.75, -0.45, 44.95)
    assert f.limit == 4  # plafond + 1 pour détecter le dépassement


def test_hex_defaults_to_all_modalities(client: TestClient, repo: FakeRepository) -> None:
    assert client.get("/hex", params={"bbox": BBOX, "res": 7}).status_code == 200
    f = repo.calls[-1][1]
    assert isinstance(f, HexFilter)
    assert (f.type_local, f.dpe, f.annee) == ("tous", "tous", "tous")


def test_hex_refuses_more_rows_than_cap(client: TestClient, repo: FakeRepository) -> None:
    repo.hexes = repo.hexes + repo.hexes  # 6 lignes > plafond 3
    res = client.get("/hex", params={"bbox": BBOX, "res": 9})
    assert res.status_code == 400
    assert "réduire l'emprise" in res.json()["error"]


@pytest.mark.parametrize(
    "bbox",
    [
        "1,2,3",
        "a,b,c,d",
        "nan,44,1,45",
        "-0.4,44.75,-0.75,44.95",  # xmin > xmax
        "-0.75,44.95,-0.45,44.75",  # ymin > ymax
        "-0.75,44.75,-0.75,44.95",  # largeur nulle
        "-200,44,-0.4,45",
        "-1.5,44,0.5,45",  # 2 degrés² > 0,25 en r9
        "inf,44,1,45",
    ],
)
def test_hex_rejects_bad_bbox(client: TestClient, bbox: str) -> None:
    res = client.get("/hex", params={"bbox": bbox, "res": 9})
    assert res.status_code == 400
    assert res.json()["success"] is False


def test_hex_r7_allows_larger_area(client: TestClient) -> None:
    assert client.get("/hex", params={"bbox": "-1.5,44,0.5,45", "res": 7}).status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {"res": 8},
        {"res": 9, "type": "Château"},
        {"res": 9, "dpe": "H"},
        {"res": 9, "annee": "2024 OR 1=1"},
    ],
)
def test_hex_rejects_bad_filters(client: TestClient, params: dict[str, object]) -> None:
    assert client.get("/hex", params={"bbox": BBOX, **params}).status_code == 422


# --- /communes/{code}/stats et /risques --------------------------------------------


def test_commune_stats(client: TestClient) -> None:
    res = client.get("/communes/33063/stats")
    assert res.status_code == 200
    g = res.json()["data"]["groupes"][0]
    assert g["n_ventes"] >= 5
    assert g["prix_m2_q1"] is None  # moins de 11 ventes
    assert g["surface_mediane"] % 5 == 0 and "surface_moyenne" not in g
    assert "etag" in res.headers


def test_commune_risks(client: TestClient) -> None:
    res = client.get("/communes/33063/risques")
    assert res.status_code == 200
    assert res.json()["data"]["rga_iris"] == {"faible": 10}


@pytest.mark.parametrize("path", ["/communes/99999/stats", "/communes/99999/risques"])
def test_unknown_commune_is_404(client: TestClient, path: str) -> None:
    res = client.get(path)
    assert res.status_code == 404
    assert res.json()["success"] is False


@pytest.mark.parametrize("code", ["3306", "330633", "abcde", "33%27"])
def test_bad_commune_code_is_422(client: TestClient, code: str) -> None:
    assert client.get(f"/communes/{code}/stats").status_code == 422


def test_corsica_code_accepted(client: TestClient) -> None:
    assert client.get("/communes/2A004/risques").status_code == 404  # format valide
