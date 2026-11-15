"""Promotion du gold : data/gold_build → data/gold, tout ou rien, après dbt build."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas_pipelines.load import promote as pr

TABLES = ("dim_a", "fact_b")


def _build(build: Path, tables: tuple[str, ...] = TABLES, value: int = 1) -> None:
    build.mkdir(parents=True, exist_ok=True)
    for t in tables:
        pq.write_table(pa.table({"x": [value]}), build / f"{t}.parquet")


def _old_gold(gold: Path) -> None:
    gold.mkdir(parents=True)
    pq.write_table(pa.table({"x": [0]}), gold / "dim_a.parquet")
    (gold / "obsolete.txt").write_text("ancien")


def _value(path: Path) -> int:
    return int(pq.read_table(path)["x"][0].as_py())


def test_promote_replaces_gold_with_exactly_the_build(tmp_path: Path) -> None:
    build, gold = tmp_path / "gold_build", tmp_path / "gold"
    _build(build, value=7)
    (build / "atlas.duckdb").write_bytes(b"db")  # artefact dbt : jamais promu
    _old_gold(gold)
    out = pr.promote(build, gold, TABLES)
    assert out == [gold / "dim_a.parquet", gold / "fact_b.parquet"]
    assert sorted(p.name for p in gold.iterdir()) == ["dim_a.parquet", "fact_b.parquet"]
    assert _value(gold / "dim_a.parquet") == 7
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gold", "gold_build"]  # rien qui traîne


def test_promote_works_without_previous_gold(tmp_path: Path) -> None:
    build, gold = tmp_path / "gold_build", tmp_path / "gold"
    _build(build)
    pr.promote(build, gold, TABLES)
    assert (gold / "fact_b.parquet").exists()


@pytest.mark.parametrize("defaut", ["absent", "vide", "corrompu"])
def test_promote_refuses_incomplete_build_and_keeps_gold(tmp_path: Path, defaut: str) -> None:
    build, gold = tmp_path / "gold_build", tmp_path / "gold"
    _build(build, tables=("dim_a",))
    bad = build / "fact_b.parquet"
    if defaut == "vide":
        bad.write_bytes(b"")
    elif defaut == "corrompu":
        bad.write_bytes(b"pas du parquet")
    _old_gold(gold)
    with pytest.raises((FileNotFoundError, ValueError)):
        pr.promote(build, gold, TABLES)
    assert _value(gold / "dim_a.parquet") == 0 and (gold / "obsolete.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gold", "gold_build"]


def test_promote_rolls_back_when_swap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build, gold = tmp_path / "gold_build", tmp_path / "gold"
    _build(build, value=7)
    _old_gold(gold)
    real_rename = Path.rename

    def flaky(self: Path, target: Path) -> Path:
        if self.name == ".gold.new":  # la bascule nouveau → gold échoue
            raise OSError("disque plein")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    with pytest.raises(OSError, match="disque plein"):
        pr.promote(build, gold, TABLES)
    monkeypatch.undo()
    assert _value(gold / "dim_a.parquet") == 0 and (gold / "obsolete.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gold", "gold_build"]


def test_promote_rejects_empty_table_list(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Aucune table"):
        pr.promote(tmp_path / "b", tmp_path / "g", ())


def test_main_reads_data_dir_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _build(tmp_path / "gold_build", tables=pr.GOLD_TABLES)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_DEPARTEMENTS", "33")
    pr.main()
    assert (tmp_path / "gold" / "agg_hex.parquet").exists()
    assert "agg_hex.parquet" in capsys.readouterr().out
