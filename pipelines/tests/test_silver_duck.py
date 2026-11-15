"""Silver DuckDB : BAN, DPE, Géorisques sur des Parquet minuscules."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.silver import ban, dpe, georisques, run_duck


def _write(path: Path, cols: dict[str, list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), path)


def _rows(path: Path) -> list[dict[str, object]]:
    return pq.read_table(path).to_pylist()


@pytest.fixture
def one(cfg: PipelineConfig) -> PipelineConfig:
    return PipelineConfig(data_dir=cfg.data_dir, departements=("33",), dvf_periodes=("2024",))


def test_ban_dedup_types_and_explodes(one: PipelineConfig) -> None:
    _write(
        one.bronze("ban") / "dep=33.parquet",
        {
            "id": ["a", "a", "b", None],
            "code_insee": ["33063", "33063", "33001", "33001"],
            "nom_commune": ["Bordeaux"] * 2 + ["Abzac"] * 2,
            "code_postal": ["33000"] * 4,
            "numero": ["1", "1", "2", "3"],
            "rep": [None] * 4,
            "nom_voie": ["rue"] * 4,
            "lon": ["-0.57", "-0.57", "x", "0"],
            "lat": ["44.8", "44.8", "45", "0"],
            "cad_parcelles": ["P1|P2", None, None, "P9"],
        },
    )
    assert ban.run(one) == {"33": 2}
    rows = {r["id"]: r for r in _rows(one.silver("ban") / "dep=33.parquet")}
    assert rows["a"]["parcelles"] == ["P1", "P2"]  # la ligne avec parcelles gagne
    assert rows["a"]["lon"] == pytest.approx(-0.57)
    assert rows["b"]["parcelles"] == [] and rows["b"]["lon"] is None


def test_dpe_keeps_valid_history(one: PipelineConfig) -> None:
    _write(
        one.bronze("dpe") / "dep=33.parquet",
        {
            "numero_dpe": ["1", "2", "3", "4", "5", "6"],
            "identifiant_ban": ["a", "a", "a", "b", "c", None],
            "code_insee_ban": ["33063"] * 6,
            "etiquette_dpe": ["D", "c", "B", "H", "E", "A"],
            "etiquette_ges": ["A", "Z", "B", "A", "E", "A"],
            "date_etablissement_dpe": [
                "2022-01-01", "2024-05-01", "2021-06-30", "2024-01-01", "2023-01-01", "2023-01-01"
            ],
            "surface_habitable_logement": ["50.5"] * 6,
            "type_batiment": ["Appartement"] * 6,
            "periode_construction": ["1978-1982"] * 6,
            "_geopoint": ["44.8,-0.57"] * 6,
        },
    )
    counts = dpe.run(one)
    assert counts == {"33_bronze": 6, "33": 3}
    rows = _rows(one.silver("dpe") / "dep=33.parquet")
    # historique complet : les DPE 1 et 2 de l'adresse « a » sont gardés tous les deux
    # (le gold choisit celui connu à la date de chaque vente) ; 3 rejeté (avant juillet
    # 2021), 4 rejeté (étiquette H), 6 rejeté (sans adresse BAN) ; GES « Z » → NULL
    assert [(r["numero_dpe"], r["identifiant_ban"]) for r in rows] == [
        ("1", "a"), ("2", "a"), ("5", "c")
    ]
    by_num = {r["numero_dpe"]: r for r in rows}
    assert (by_num["2"]["etiquette_dpe"], by_num["2"]["etiquette_ges"]) == ("C", None)
    assert by_num["1"]["etiquette_ges"] == "A"
    assert (by_num["2"]["lon"], by_num["2"]["lat"]) == (-0.57, 44.8)
    assert by_num["2"]["type_batiment"] == "appartement"
    assert "n_dpe_adresse" not in rows[0]  # calculé au gold, à la date de chaque vente


def _payloads(path: Path, endpoint: str, items: list[tuple[str, dict[str, object] | None]]) -> None:
    _write(
        path,
        {
            "endpoint": [endpoint] * len(items),
            "code_insee": [c for c, _ in items],
            "payload": [None if p is None else json.dumps(p) for _, p in items],
        },
    )


def test_georisques_flattens_and_tracks_coverage(one: PipelineConfig) -> None:
    b = one.bronze("georisques")
    cat = {"code_national_catnat": "X1", "libelle_risque_jo": "Inondations",
           "date_debut_evt": "08/02/2026", "date_fin_evt": "09/02/2026",
           "date_publication_arrete": "23/02/2026"}
    _payloads(b / "catnat.parquet", "catnat", [("33063", cat), ("33063", cat), ("33001", None)])
    _payloads(b / "tri.parquet", "tri", [("33063", {"code_national_tri": "T", "libelle_tri": "B"})])
    _payloads(b / "pprn.parquet", "pprn", [
        ("33063", {"idGaspar": "P1", "modeleProcedure": "PPRN-I", "libPpr": "PPR"}),
        ("33009", {"idGaspar": "P2", "modeleProcedure": "PPRN-IF", "libPpr": "Feu"}),
    ])
    _write(b / "rga.parquet", {
        "code_iris": ["330630101", "330010000"], "lon": [-0.5, -0.2], "lat": [44.8, 44.9],
        "payload": ['{"codeExposition":"2","exposition":"Exposition moyenne"}', None],
    })
    counts = run_duck.RUNNERS["georisques"](one)
    assert counts == {"catnat": 1, "tri": 1, "pprn": 2, "couverture": 5, "rga": 2}
    s = one.silver("georisques")
    c = _rows(s / "catnat.parquet")[0]
    assert str(c["date_debut_evt"]) == "2026-02-08"
    flood = {r["id_gaspar"]: r["risque_inondation"] for r in _rows(s / "pprn.parquet")}
    assert flood == {"P1": True, "P2": False}
    cov = {
        (r["endpoint"], r["code_insee"]): r["n_enregistrements"]
        for r in _rows(s / "couverture.parquet")
    }
    assert cov[("catnat", "33001")] == 0 and cov[("catnat", "33063")] == 2
    r = {x["code_iris"]: x for x in _rows(s / "rga.parquet")}
    assert r["330630101"]["code_exposition"] == 2 and r["330010000"]["exposition"] is None


def test_silver_missing_inputs_are_explicit(one: PipelineConfig) -> None:
    with pytest.raises(FileNotFoundError, match="BAN"):
        ban.run(one)
    with pytest.raises(FileNotFoundError, match="Géorisques"):
        georisques.run(one)


def test_run_duck_cli(one: PipelineConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_DATA_DIR", str(one.data_dir))
    monkeypatch.setenv("ATLAS_DEPARTEMENTS", "33")
    _write(one.bronze("ban") / "dep=33.parquet", {
        "id": ["a"], "code_insee": ["33063"], "nom_commune": ["B"], "code_postal": ["1"],
        "numero": ["1"], "rep": [None], "nom_voie": ["r"], "lon": ["0"], "lat": ["0"],
        "cad_parcelles": ["P"],
    })
    assert run_duck.main(["ban"]) == {"ban": {"33": 1}}
