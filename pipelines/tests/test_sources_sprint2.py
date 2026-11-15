"""Sources du sprint 2 : contours IRIS (7z + GPKG), PPRN et RGA Géorisques. Sans réseau."""

from __future__ import annotations

from pathlib import Path

import httpx
import py7zr
import pyarrow.parquet as pq
import pytest

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.sources import iris, ppr, rga
from atlas_pipelines.spatial import connect_spatial, sql_path

SQUARE = "POLYGON((-0.6 44.8, -0.5 44.8, -0.5 44.9, -0.6 44.9, -0.6 44.8))"
FAR = "POLYGON((5.3 43.2, 5.4 43.2, 5.4 43.3, 5.3 43.3, 5.3 43.2))"


def make_gpkg(path: Path, geom_name: str = "geometrie") -> Path:
    """GeoPackage minuscule au schéma IGN : deux IRIS (Gironde, Bouches-du-Rhône)."""
    with connect_spatial() as con:
        con.execute(
            f"""COPY (
                SELECT * FROM (VALUES
                  ('330630101', '33063', 'Bordeaux', 'Iris A', 'H', ST_GeomFromText('{SQUARE}')),
                  ('130550101', '13055', 'Marseille', 'Iris B', 'H', ST_GeomFromText('{FAR}'))
                ) t(code_iris, code_insee, nom_commune, nom_iris, type_iris, geometrie)
            ) TO {sql_path(path)} (FORMAT gdal, DRIVER 'GPKG', SRS 'EPSG:4326',
                LAYER_CREATION_OPTIONS 'GEOMETRY_NAME={geom_name}')"""
        )
    return path


def make_7z(archive: Path, files: dict[str, bytes]) -> Path:
    with py7zr.SevenZipFile(archive, "w") as z:
        for name, data in files.items():
            z.writestr(data, name)
    return archive


def test_iris_ingest_extracts_filters_and_writes_wkb(
    cfg: PipelineConfig, mock_client, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    gpkg = make_gpkg(tmp_path / "src.gpkg").read_bytes()
    body = make_7z(
        tmp_path / "a.7z",
        {"A/B/LISTE.csv": b"x", "A/" + "x" * 200 + "/iris.gpkg": gpkg},
    ).read_bytes()
    one_dep = PipelineConfig(data_dir=cfg.data_dir, departements=("33",), dvf_periodes=("2024",))
    with mock_client(lambda _r: httpx.Response(200, content=body)) as client:
        assert iris.ingest(one_dep, client) == {"contours_iris": 1}
    rows = pq.read_table(one_dep.bronze("iris") / "contours_iris.parquet").to_pylist()
    assert rows[0]["code_iris"] == "330630101"
    assert isinstance(rows[0]["geom_wkb"], bytes)
    assert (one_dep.raw("iris") / "iris.gpkg").exists()
    assert not (one_dep.raw("iris") / "A").exists()  # chemins de l'archive jamais utilisés


def test_iris_rejects_ambiguous_archive_and_bad_schema(tmp_path: Path) -> None:
    archive = make_7z(tmp_path / "b.7z", {"a.gpkg": b"1", "b.gpkg": b"2"})
    with pytest.raises(ValueError, match="unique"):
        iris.extract_gpkg(archive, tmp_path / "out.gpkg")
    empty = make_7z(tmp_path / "c.7z", {"a.gpkg": b""})
    with pytest.raises(ValueError, match="vide"):
        iris.extract_gpkg(empty, tmp_path / "out.gpkg")
    bad = make_gpkg(tmp_path / "bad.gpkg", geom_name="geom")
    with pytest.raises(ValueError, match="geometrie"):
        iris.gpkg_to_parquet(bad, tmp_path / "x.parquet", ("33",))


def test_iris_size_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(iris, "MAX_GPKG_BYTES", 3)
    archive = make_7z(tmp_path / "d.7z", {"a.gpkg": b"12345"})
    with pytest.raises(ValueError, match="refusée"):
        iris.extract_gpkg(archive, tmp_path / "out.gpkg")
    assert not (tmp_path / ".out.gpkg.part").exists()


def _ban(cfg: PipelineConfig, codes: list[str]) -> None:
    import pyarrow as pa

    cfg.bronze("ban").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"code_insee": codes}), cfg.bronze("ban") / "dep=33.parquet")


def test_ppr_paginates_by_number_and_marks_empty(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    _ban(cfg, ["33063", "33001"])
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        code, page = req.url.params["codeInsee"], int(req.url.params["page"])
        if code == "33001":
            return httpx.Response(200, json={"content": [], "totalPages": 0})
        item = {"idGaspar": f"P{page}", "modeleProcedure": "PPRN-I"}
        return httpx.Response(
            200, json={"content": [item], "totalPages": 2, "next": "http://interne/x"}
        )

    with mock_client(handler) as client:
        assert ppr.ingest(cfg, client) == {"pprn": 3}
    rows = pq.read_table(cfg.bronze("georisques") / "pprn.parquet").to_pylist()
    assert [(r["code_insee"], r["payload"] is None) for r in rows] == [
        ("33001", True),
        ("33063", False),
        ("33063", False),
    ]
    assert not any("interne" in u for u in seen)


def test_ppr_guards(cfg: PipelineConfig, mock_client) -> None:  # type: ignore[no-untyped-def]
    endless = {"content": [{"idGaspar": "x"}], "totalPages": 999}
    with mock_client(lambda _r: httpx.Response(200, json=endless)) as client:
        with pytest.raises(RuntimeError, match="pages"):
            ppr.fetch_pprn(client, "33063", ppr.RateLimiter(100))
    _ban(cfg, [])
    with mock_client(lambda _r: httpx.Response(200, json={})) as client:
        with pytest.raises(RuntimeError, match="BAN"):
            ppr.ingest(cfg, client)


def _iris_bronze(cfg: PipelineConfig, tmp_path: Path) -> None:
    gpkg = make_gpkg(tmp_path / "i.gpkg")
    iris.gpkg_to_parquet(gpkg, cfg.bronze("iris") / "contours_iris.parquet", ("33", "13"))


def test_rga_queries_point_inside_each_iris(
    cfg: PipelineConfig, mock_client, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    _iris_bronze(cfg, tmp_path)
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        lon, lat = (float(x) for x in req.url.params["latlon"].split(","))
        calls.append(req.url.params["latlon"])
        if lon > 0:  # Marseille : corps vide, comme l'API hors zone cartographiée
            return httpx.Response(200, content=b"")
        assert -0.6 < lon < -0.5 and 44.8 < lat < 44.9  # point DANS le polygone
        return httpx.Response(200, json={"codeExposition": "2", "exposition": "Exposition moyenne"})

    with mock_client(handler) as client:
        assert rga.ingest(cfg, client) == {"rga": 2, "rga_avec_donnee": 1}
    table = pq.read_table(cfg.bronze("georisques") / "rga.parquet")
    rows = {r["code_iris"]: r for r in table.to_pylist()}
    assert rows["130550101"]["payload"] is None
    assert "Exposition moyenne" in rows["330630101"]["payload"]
    assert len(calls) == 2


def test_rga_requires_iris_and_rejects_non_object(
    cfg: PipelineConfig, mock_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FileNotFoundError, match="IRIS"):
        rga.iris_points(cfg)
    monkeypatch.setattr(rga.fetch_rga.retry, "sleep", lambda _s: None)  # type: ignore[attr-defined]
    with mock_client(lambda _r: httpx.Response(200, json=[1, 2])) as client:
        with pytest.raises(ValueError, match="inattendue"):
            rga.fetch_rga(client, -0.5, 44.8, rga.RateLimiter(100))


def test_iris_gpkg_to_parquet_rejects_empty_departements(tmp_path: Path) -> None:
    gpkg = make_gpkg(tmp_path / "src.gpkg")
    with pytest.raises(ValueError, match="département"):
        iris.gpkg_to_parquet(gpkg, tmp_path / "x.parquet", ())
    assert not (tmp_path / "x.parquet").exists()


def test_iris_gpkg_to_parquet_removes_part_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpkg = make_gpkg(tmp_path / "src.gpkg")
    dest = tmp_path / "out" / "contours_iris.parquet"

    def boom(self: Path, target: Path) -> Path:
        raise OSError("bascule impossible")

    monkeypatch.setattr(Path, "replace", boom)  # échec APRÈS l'écriture du .part
    with pytest.raises(OSError, match="bascule"):
        iris.gpkg_to_parquet(gpkg, dest, ("33",))
    monkeypatch.undo()
    assert list(dest.parent.iterdir()) == []
