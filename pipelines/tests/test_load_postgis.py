"""Chargeur PostGIS : SQL généré et flux de copie, avec un curseur factice (sans base)."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas_pipelines.load import postgis as lp


class FakeCopy:
    def __init__(self, sink: list[tuple[Any, ...]]) -> None:
        self.sink = sink

    def __enter__(self) -> FakeCopy:
        return self

    def __exit__(
        self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    def write_row(self, row: tuple[Any, ...]) -> None:
        self.sink.append(row)


class FakeCursor:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.rows: list[tuple[Any, ...]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.sql.append(query)

    def copy(self, statement: str) -> FakeCopy:
        self.sql.append(statement)
        return FakeCopy(self.rows)


def test_pg_types_and_identifiers() -> None:
    # texte libre : collation par défaut de la base (lower('Étauliers') doit marcher)
    assert lp.pg_type(pa.string()) == "text"
    assert lp.pg_type(pa.string(), code=True) == 'text COLLATE "C"'
    assert lp.pg_type(pa.large_string(), code=True) == 'text COLLATE "C"'
    assert lp.pg_type(pa.int32(), code=True) == "integer"  # code=True n'agit que sur le texte
    assert lp.pg_type(pa.int32()) == "integer"
    assert lp.pg_type(pa.float64()) == "double precision"
    assert lp.pg_type(pa.date32()) == "date"
    assert lp.pg_type(pa.binary()) == "bytea"
    with pytest.raises(TypeError):
        lp.pg_type(pa.list_(pa.string()))
    for bad in ("x; DROP TABLE y", "Nom", "a-b"):
        with pytest.raises(ValueError):
            lp.ident(bad)


def test_collation_c_only_on_code_columns() -> None:
    names = ("code_insee", "id_mutation", "h3", "h3_r9", "dpe_numero",
             "nom_commune", "nom_recherche", "type_local", "dpe_etiquette")
    schema = pa.schema([(n, pa.string()) for n in names])
    sql = lp.create_sql(lp.TableSpec("t", "code_insee", "none"), schema)
    for code in names[:5]:
        assert f'"{code}" text COLLATE "C"' in sql
    for libre in names[5:]:
        assert f'"{libre}" text,' in sql or f'"{libre}" text)' in sql


def test_stage_table_polygons(tmp_path: Path) -> None:
    path = tmp_path / "dim_iris.parquet"
    pq.write_table(
        pa.table({"code_iris": ["1", "2"], "geom_wkb": [b"\x01", b"\x02"]}), path
    )
    cur = FakeCursor()
    spec = lp.TableSpec("dim_iris", "code_iris", "wkb", ("code_insee",))
    assert lp.stage_table(cur, spec, path) == 2
    assert cur.rows == [("1", b"\x01"), ("2", b"\x02")]
    sql = "\n".join(cur.sql)
    assert 'CREATE TABLE gold."dim_iris__new"' in sql
    assert "ST_GeomFromWKB(geom_wkb, 4326)" in sql and "DROP COLUMN geom_wkb" in sql
    assert "USING gist (geom)" in sql and '"ix_dim_iris_code_insee__new"' in sql


def test_finish_and_swap_points_and_plain() -> None:
    pts = lp.TableSpec("fact_transactions", "id_mutation", "point", ("h3_r9",))
    assert any("ST_MakePoint(lon, lat)" in s for s in lp.finish_sql(pts))
    swap = lp.swap_sql(pts)
    assert swap[0] == 'DROP TABLE IF EXISTS gold."fact_transactions"'
    assert any('"ix_fact_transactions_geom__new" RENAME' in s for s in swap)
    plain = lp.TableSpec("fact_risques_commune", "code_insee", "none")
    assert not any("geom" in s for s in lp.finish_sql(plain) + lp.swap_sql(plain))
    agg = lp.TableSpec("agg_hex", "id_agg", "point", (), ("resolution", "annee"))
    assert any('("resolution", "annee")' in s for s in lp.finish_sql(agg))
    assert any('"ix_agg_hex_filtre__new" RENAME' in s for s in lp.swap_sql(agg))
    commune = lp.TableSpec("dim_commune", "code_insee", "wkb")
    assert any('("nom_recherche" text_pattern_ops)' in s for s in lp.finish_sql(commune))
    assert any("ix_dim_commune_nom__new" in s for s in lp.swap_sql(commune))


def test_conninfo_and_missing_gold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="POSTGRES_USER"):
        lp.conninfo_from_env()
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "d")
    info = lp.conninfo_from_env()
    assert "dbname=d" in info and "user=u" in info
    with pytest.raises(FileNotFoundError, match="dbt build"):
        lp.load(tmp_path, info)


class FakeConn:
    def __init__(self, cur: FakeCursor) -> None:
        self.cur = cur
        self.commits = 0
        self.autocommit = False

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> FakeConn:
        return self

    def execute(self, query: str, params: Any = None) -> None:
        self.cur.execute(query, params)

    def copy(self, statement: str) -> FakeCopy:
        return self.cur.copy(statement)

    def commit(self) -> None:
        self.commits += 1


def test_swap_regrants_least_privilege_readers() -> None:
    fact = lp.swap_sql(lp.TableSpec("fact_transactions", "id_mutation", "point"))
    grants = [s for s in fact if "GRANT" in s]
    assert len(grants) == 1 and '"atlas_api"' in grants[0]  # jamais atlas_tiles sur les ventes
    assert 'GRANT SELECT ON gold."fact_transactions"' in grants[0]
    for name in ("agg_hex", "dim_commune", "dim_iris"):
        grants = [s for s in lp.swap_sql(lp.TableSpec(name, "k", "none")) if "GRANT" in s]
        granted = {r for r in ("atlas_api", "atlas_tiles") if any(f'"{r}"' in g for g in grants)}
        assert granted == {"atlas_api", "atlas_tiles"}
        assert all("SELECT 1 FROM pg_roles" in g for g in grants)


def test_load_stages_all_then_swaps_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg

    specs = (
        lp.TableSpec("t_a", "k", "none"),
        lp.TableSpec("t_b", "k", "point"),
    )
    pq.write_table(pa.table({"k": ["1"]}), tmp_path / "t_a.parquet")
    pq.write_table(pa.table({"k": ["1"], "lon": [0.0], "lat": [0.0]}), tmp_path / "t_b.parquet")
    conn = FakeConn(FakeCursor())
    monkeypatch.setattr(psycopg, "connect", lambda _info: conn)
    assert lp.load(tmp_path, "x", specs) == {"t_a": 1, "t_b": 1}
    sql = conn.cur.sql
    first_drop = next(i for i, s in enumerate(sql) if s == 'DROP TABLE IF EXISTS gold."t_a"')
    last_copy = max(i for i, s in enumerate(sql) if s.startswith("COPY"))
    assert first_drop > last_copy  # bascule seulement après toutes les préparations
    assert conn.commits == 3 and sql[-1] == 'ANALYZE gold."t_b"'
