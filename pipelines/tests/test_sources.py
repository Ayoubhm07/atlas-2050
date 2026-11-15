from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path

import duckdb
import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.sources import ban, dpe, drias, dvf, georisques, insee
from atlas_pipelines.sources.csv_to_parquet import csv_to_parquet


def _rows(path: Path) -> list[dict[str, object]]:
    return pq.read_table(path).to_pylist()


def test_csv_to_parquet_keeps_leading_zeros(tmp_path: Path) -> None:
    src = tmp_path / "a.csv.gz"
    src.write_bytes(gzip.compress(b"code;v\n01;1\n33;2\n"))
    n = csv_to_parquet(src, tmp_path / "a.parquet", sep=";", where="code = '01'")
    assert n == 1
    assert _rows(tmp_path / "a.parquet") == [{"code": "01", "v": "1"}]
    with pytest.raises(ValueError):
        csv_to_parquet(src, tmp_path / "b.parquet", sep="'")


def test_csv_to_parquet_handles_rare_quoted_field_after_sample(tmp_path: Path) -> None:
    """Régression : champ entre guillemets avec virgule, loin après l'échantillon de détection."""
    body = "a,b,c\n" + "x,1,y\n" * 30_000 + 'x,"Pierraille, pierrier",y\n'
    src = tmp_path / "q.csv.gz"
    src.write_bytes(gzip.compress(body.encode()))
    assert csv_to_parquet(src, tmp_path / "q.parquet") == 30_001
    assert _rows(tmp_path / "q.parquet")[-1] == {"a": "x", "b": "Pierraille, pierrier", "c": "y"}


DVF_CSV = b"id_mutation,code_departement,valeur_fonciere\n1,33,100\n2,13,200\n3,75,300\n"


def test_dvf_resolves_national_files_and_filters(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    url = "https://static.data.gouv.fr/resources/x/20261020/full-2024.csv.gz"

    def handler(req: httpx.Request) -> httpx.Response:
        if "api/1/datasets" in str(req.url):
            return httpx.Response(
                200, json={"resources": [{"url": url}, {"url": "https://x/doc.pdf"}]}
            )
        return httpx.Response(200, content=gzip.compress(DVF_CSV))

    with mock_client(handler) as client:
        assert dvf.ingest(cfg, client) == {"2024": 2}
    deps = {r["code_departement"] for r in _rows(cfg.bronze("dvf") / "periode=2024.parquet")}
    assert deps == {"33", "13"}


def test_dvf_missing_period_is_explicit(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    with mock_client(lambda _r: httpx.Response(200, json={"resources": []})) as client:
        with pytest.raises(LookupError, match="2024"):
            dvf.resolve_urls(client, ("2024",))


def test_ban_uses_semicolon(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    body = gzip.compress(b"id;code_insee;cad_parcelles\na;33001;p1|p2\n")
    with mock_client(lambda _r: httpx.Response(200, content=body)) as client:
        assert ban.ingest(cfg, client) == {"33": 1, "13": 1}
    assert _rows(cfg.bronze("ban") / "dep=33.parquet")[0]["cad_parcelles"] == "p1|p2"


def test_dpe_follows_cursor_and_refuses_foreign_host(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    pages = {
        None: {
            "results": [{"numero_dpe": "A", "surface_habitable_logement": 50.5}],
            "next": "https://data.ademe.fr/next?after=1",
        },
        "1": {"results": [{"numero_dpe": "B"}], "next": None},
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[req.url.params.get("after")])

    with mock_client(handler) as client:
        assert dpe.ingest(cfg, client) == {"33": 2, "13": 2}
    rows = _rows(cfg.bronze("dpe") / "dep=33.parquet")
    assert [r["numero_dpe"] for r in rows] == ["A", "B"]
    assert rows[0]["surface_habitable_logement"] == "50.5"

    evil = {"results": [{"numero_dpe": "A"}], "next": "https://evil.example/x"}
    with mock_client(lambda _r: httpx.Response(200, json=evil)) as client:
        with pytest.raises(ValueError, match="refusé"):
            list(dpe.iter_pages(client, "33", dpe.RateLimiter(10)))


def _write_ban(cfg: PipelineConfig, codes: list[str]) -> None:
    cfg.bronze("ban").mkdir(parents=True)
    pq.write_table(pa.table({"code_insee": codes}), cfg.bronze("ban") / "dep=33.parquet")


def test_georisques_paginates_by_page_and_marks_empty(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    _write_ban(cfg, ["33063", "33001", "33063"])

    def handler(req: httpx.Request) -> httpx.Response:
        code = req.url.params["code_insee"]
        page = int(req.url.params["page"])
        if code == "33001":
            return httpx.Response(200, json={"data": [], "total_pages": 0})
        return httpx.Response(
            200,
            json={"data": [{"p": page}], "total_pages": 2, "next": "http://internal/host"},
        )

    with mock_client(handler) as client:
        counts = georisques.ingest(cfg, client)
    assert counts == {"catnat": 3, "tri": 3, "azi": 3}
    rows = _rows(cfg.bronze("georisques") / "catnat.parquet")
    assert [(r["code_insee"], r["payload"]) for r in rows] == [
        ("33001", None),
        ("33063", '{"p": 1}'),
        ("33063", '{"p": 2}'),
    ]


def test_georisques_guards(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    with mock_client(lambda _r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError):
            georisques.fetch_all(client, "../admin", "33063", georisques.RateLimiter(10))
    _write_ban(cfg, [])
    with mock_client(lambda _r: httpx.Response(200, json={})) as client:
        with pytest.raises(RuntimeError, match="BAN"):
            georisques.ingest(cfg, client)


def _zip(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path.read_bytes()


def test_insee_extracts_data_csv_and_filters(
    cfg: PipelineConfig, mock_client, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    body = _zip(
        tmp_path / "z.zip",
        {
            "../../evil/BASE_TD.csv": b"IRIS;DISP_MED21\n330630101;25000\n750010101;30000\n",
            "meta_BASE_TD.csv": b"x\n",
        },
    )
    with mock_client(lambda _r: httpx.Response(200, content=body)) as client:
        assert insee.ingest(cfg, client) == {"filosofi_iris_2021": 1}
    assert (cfg.raw("insee") / "BASE_TD.csv").exists()
    assert not (cfg.data_dir.parent / "evil").exists()


def test_insee_rejects_ambiguous_archive(tmp_path: Path) -> None:
    _zip(tmp_path / "z.zip", {"a.csv": b"x", "b.csv": b"y"})
    with pytest.raises(ValueError, match="unique"):
        insee._extract_csv(tmp_path / "z.zip", tmp_path)


def _drias_depot(cfg: PipelineConfig, entries: list[dict[str, str]]) -> None:
    raw = cfg.raw("drias")
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")


def test_drias_explains_missing_depot(cfg: PipelineConfig) -> None:
    with pytest.raises(drias.DriasDepotError, match="drias-climat.fr"):
        drias.ingest(cfg)


def _entry(scenario: str, horizon: str = "2050", **kw: str) -> dict[str, str]:
    base = {
        "file": "a",
        "indicateur": "tx35",
        "scenario": scenario,
        "horizon": horizon,
        "sha256": "",
        "telecharge_le": "2026-11-15",
    }
    return {**base, **kw}


def test_drias_validates_and_converts(cfg: PipelineConfig) -> None:
    raw = cfg.raw("drias")
    raw.mkdir(parents=True)
    entries = []
    for sc in ("rcp45", "rcp85"):
        for hz in ("2030", "2050"):
            data = f"point;tx35\n1;{hz}\n".encode()
            (raw / f"tx35_{sc}_{hz}.csv").write_bytes(data)
            entries.append(
                _entry(sc, hz, file=f"tx35_{sc}_{hz}.csv", sha256=hashlib.sha256(data).hexdigest())
            )
    _drias_depot(cfg, entries)
    counts = drias.ingest(cfg)
    assert sorted(counts) == [
        f"tx35_{s}_{h}.parquet" for s in ("rcp45", "rcp85") for h in ("2030", "2050")
    ]

    entries[0]["sha256"] = "0" * 64
    _drias_depot(cfg, entries)
    with pytest.raises(drias.DriasDepotError, match="Checksum"):
        drias.ingest(cfg)


@pytest.mark.parametrize(
    ("entries", "msg"),
    [
        ([], "vide"),
        ([_entry("rcp26")], "inconnus"),
        ([_entry("rcp45")], "manquants"),
        ([_entry("rcp45", "2100"), _entry("rcp85")], "Horizons"),
        ([_entry("rcp45", indicateur="../../x"), _entry("rcp85")], "indicateur"),
        ([_entry("rcp45"), _entry("rcp45", file="b"), _entry("rcp85")], "double"),
        ([_entry("rcp45"), _entry("rcp85")], "absent"),
    ],
)
def test_drias_manifest_errors(
    cfg: PipelineConfig, entries: list[dict[str, str]], msg: str
) -> None:
    _drias_depot(cfg, entries)
    with pytest.raises(drias.DriasDepotError, match=msg):
        drias.ingest(cfg)


def test_communes_from_ban_is_distinct(cfg: PipelineConfig) -> None:
    _write_ban(cfg, ["33063", None, "33063", "33001"])  # type: ignore[list-item]
    assert georisques.communes_from_ban(cfg) == ["33001", "33063"]
    assert duckdb is not None


def test_dvf_duplicate_period_is_ambiguous(mock_client) -> None:  # type: ignore[no-untyped-def]
    res = {
        "resources": [
            {"url": "https://s/a/full-2024.csv.gz"},
            {"url": "https://s/b/full-2024.csv.gz"},
        ]
    }
    with mock_client(lambda _r: httpx.Response(200, json=res)) as client:
        with pytest.raises(LookupError, match="ambigu"):
            dvf.resolve_urls(client, ("2024",))


def test_dpe_refuses_http_downgrade(mock_client) -> None:  # type: ignore[no-untyped-def]
    page = {"results": [{"numero_dpe": "A"}], "next": "http://data.ademe.fr/next"}
    with mock_client(lambda _r: httpx.Response(200, json=page)) as client:
        with pytest.raises(ValueError, match="refusé"):
            list(dpe.iter_pages(client, "33", dpe.RateLimiter(10)))


def test_dpe_stops_looping_cursor_and_leaves_no_partial_file(
    cfg: PipelineConfig,
    mock_client,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setattr(dpe, "MAX_PAGES", 3)
    page = {"results": [{"numero_dpe": "A"}], "next": "https://data.ademe.fr/next?after=1"}
    with mock_client(lambda _r: httpx.Response(200, json=page)) as client:
        with pytest.raises(RuntimeError, match="boucle"):
            dpe.ingest(cfg, client)
    assert list(cfg.bronze("dpe").iterdir()) == []
