"""Tests du nettoyage silver DVF sur un mini-jeu construit à la main (PySpark local)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

pyspark = pytest.importorskip("pyspark")
from pyspark.sql import SparkSession  # noqa: E402

from atlas_pipelines.silver.dvf import (  # noqa: E402
    LOCAL_PRO,
    QualityReport,
    nettoyer,
)

pytestmark = pytest.mark.spark

COLS = [
    "id_mutation",
    "date_mutation",
    "nature_mutation",
    "valeur_fonciere",
    "code_commune",
    "code_departement",
    "id_parcelle",
    "lot1_numero",
    "type_local",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "code_nature_culture",
    "surface_terrain",
    "longitude",
    "latitude",
]


def row(mid: str, **kw: str | None) -> tuple[str | None, ...]:
    base: dict[str, str | None] = {
        "id_mutation": mid,
        "date_mutation": "2024-03-01",
        "nature_mutation": "Vente",
        "valeur_fonciere": "200000",
        "code_commune": "33063",
        "code_departement": "33",
        "id_parcelle": f"P{mid}",
        "lot1_numero": None,
        "type_local": "Maison",
        "surface_reelle_bati": "100",
        "nombre_pieces_principales": "4",
        "code_nature_culture": None,
        "surface_terrain": None,
        "longitude": "-0.57",
        "latitude": "44.84",
    }
    base.update(kw)
    return tuple(base[c] for c in COLS)


@pytest.fixture(scope="module")
def spark() -> Iterator[SparkSession]:
    s = (
        SparkSession.builder.master("local[1]")
        .appName("atlas-tests")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield s
    s.stop()


def test_nettoyer_applies_every_rule(spark: SparkSession) -> None:
    normales = [row(f"n{i}", valeur_fonciere=str(200_000 + i * 1000)) for i in range(12)]
    data = normales + [
        # forme réelle geo-DVF (mutation 2024-364725) : maison + dépendance × 2 cultures
        # = 4 lignes en produit cartésien → terrain = 300 + 200, pas 1000
        *[
            row(
                "t", type_local=tl, surface_reelle_bati=sb, code_nature_culture=c, surface_terrain=s
            )
            for tl, sb in (("Maison", "100"), ("Dépendance", None))
            for c, s in (("S", "300"), ("AG", "200"))
        ],
        # appartement : terrain = parcelle de la copropriété → doit valoir null
        row("appart", type_local="Appartement", code_nature_culture="S", surface_terrain="482"),
        # vente symbolique (≈ 15 €/m²) : passe le seuil de 1 000 €, retirée par l'IQR en log
        row("symbolique", valeur_fonciere="1500"),
        # deux logements dans la même vente → rejetée (prix total non attribuable)
        row("deux", id_parcelle="A"),
        row("deux", id_parcelle="B"),
        # logement + local commercial → rejetée
        row("pro"),
        row("pro", type_local=LOCAL_PRO),
        row("echange", nature_mutation="Echange"),
        row("unEuro", valeur_fonciere="1"),
        row("placard", surface_reelle_bati="5"),
        row("sansgeo", longitude=None),
        row("aberrant", valeur_fonciere="90000000"),
    ]
    schema = ", ".join(f"{c} string" for c in COLS)  # bronze = tout en texte
    df = spark.createDataFrame(data, schema)
    silver, report = nettoyer(df)
    got = {r["id_mutation"]: r for r in silver.collect()}

    assert set(got) == {f"n{i}" for i in range(12)} | {"t", "appart"}
    assert got["t"]["surface_terrain"] == 500.0
    assert got["t"]["n_dependances"] == 1
    assert got["t"]["prix_m2"] == 2000.0
    assert got["appart"]["surface_terrain"] is None
    assert got["n0"]["surface_terrain"] == 0.0
    assert got["n0"]["annee"] == 2024
    names = [name for name, _ in report.steps]
    assert names[0] == "Bronze (toutes lignes)"
    assert report.steps[0][1] == len(data)
    assert report.steps[-1][1] == 14


def test_report_markdown_keeps_label_commas() -> None:
    md = QualityReport().add("a, b", 1500).add("c", 1000).to_markdown()
    assert "| a, b | 1 500 |  |" in md
    assert "| c | 1 000 | 500 |" in md
