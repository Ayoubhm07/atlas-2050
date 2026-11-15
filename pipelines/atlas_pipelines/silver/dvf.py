"""DVF bronze → silver : une ligne par vente d'un logement unique, prix/m² fiable.

Rappel de structure DVF : une mutation occupe plusieurs lignes (une par local × nature
de culture), et `valeur_fonciere` est le prix TOTAL répété sur chaque ligne. On ne
peut donc calculer un prix/m² que pour les mutations qui ne portent qu'un logement.
Règles : docs/data-contract.md §1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

LOGEMENTS = ("Maison", "Appartement")
LOCAL_PRO = "Local industriel. commercial ou assimilé"
PRIX_MIN = 1_000.0
SURFACE_MIN = 9
IQR_K = 3.0
MIN_GROUPE = 10


@dataclass(frozen=True)
class QualityReport:
    steps: tuple[tuple[str, int], ...] = field(default_factory=tuple)

    def add(self, name: str, rows: int) -> QualityReport:
        return QualityReport(self.steps + ((name, rows),))

    def to_markdown(self) -> str:
        def fmt(n: int) -> str:
            return f"{n:,}".replace(",", " ")

        lines = ["| Étape | Lignes | Rejetées |", "|---|---:|---:|"]
        prev: int | None = None
        for name, rows in self.steps:
            lost = "" if prev is None else fmt(prev - rows)
            lines.append(f"| {name} | {fmt(rows)} | {lost} |")
            prev = rows
        return "\n".join(lines)


def ventes_un_logement(bronze: DataFrame) -> DataFrame:
    """Ventes ne portant qu'un logement et aucun local professionnel → une ligne par vente."""
    ventes = bronze.where(F.col("nature_mutation") == "Vente")
    local_key = F.concat_ws(
        "|",
        F.coalesce("type_local", F.lit("∅")),
        F.coalesce("surface_reelle_bati", F.lit("∅")),
        F.coalesce("lot1_numero", F.lit("∅")),
    )
    logement_key = F.when(
        F.col("type_local").isin(*LOGEMENTS), F.concat_ws("|", "id_parcelle", local_key)
    )
    par_mutation = ventes.groupBy("id_mutation").agg(
        F.countDistinct(logement_key).alias("n_logements"),
        F.max(F.when(F.col("type_local") == LOCAL_PRO, 1).otherwise(0)).alias("a_local_pro"),
        F.countDistinct(
            F.when(F.col("type_local") == "Dépendance", F.concat_ws("|", "id_parcelle", local_key))
        ).alias("n_dependances"),
    )
    gardees = par_mutation.where((F.col("n_logements") == 1) & (F.col("a_local_pro") == 0))
    return (
        _logement_unique(ventes)
        .join(gardees.select("id_mutation", "n_dependances"), "id_mutation")
        .join(_terrain_par_mutation(ventes, local_key), "id_mutation", "left")
    )


def _terrain_par_mutation(ventes: DataFrame, local_key: Column) -> DataFrame:
    """Surface de terrain sans double comptage.

    geo-DVF répète chaque nature de culture pour chaque local de la parcelle (produit
    cartésien) : on somme les cultures d'UN groupe de local, on prend le max entre
    groupes d'une même parcelle, puis on somme les parcelles de la vente.
    """
    par_groupe = (
        ventes.where(F.col("code_nature_culture").isNotNull())
        .groupBy("id_mutation", "id_parcelle", local_key.alias("_local"))
        .agg(F.sum(F.col("surface_terrain").cast("double")).alias("t"))
    )
    par_parcelle = par_groupe.groupBy("id_mutation", "id_parcelle").agg(F.max("t").alias("t"))
    return par_parcelle.groupBy("id_mutation").agg(F.sum("t").alias("terrain_brut"))


def _logement_unique(ventes: DataFrame) -> DataFrame:
    """Une ligne logement par vente, choisie de façon déterministe (min lexicographique)."""
    cols = [c for c in ventes.columns if c != "id_mutation"]
    return (
        ventes.where(F.col("type_local").isin(*LOGEMENTS))
        .groupBy("id_mutation")
        .agg(F.min(F.struct(*cols)).alias("_r"))
        .select("id_mutation", "_r.*")
    )


def typer(df: DataFrame) -> DataFrame:
    return df.select(
        "id_mutation",
        F.to_date("date_mutation").alias("date_mutation"),
        F.year(F.to_date("date_mutation")).alias("annee"),
        "code_departement",
        "code_commune",
        "id_parcelle",
        "type_local",
        F.col("surface_reelle_bati").cast("int").alias("surface_bati"),
        F.col("nombre_pieces_principales").cast("int").alias("pieces"),
        # pour un appartement, le terrain est la parcelle de la copropriété : non pertinent
        F.when(F.col("type_local") == "Maison", F.coalesce(F.col("terrain_brut"), F.lit(0.0)))
        .otherwise(F.lit(None).cast("double"))
        .alias("surface_terrain"),
        F.col("n_dependances").cast("int").alias("n_dependances"),
        F.col("valeur_fonciere").cast("double").alias("valeur_fonciere"),
        F.col("longitude").cast("double").alias("lon"),
        F.col("latitude").cast("double").alias("lat"),
    )


def valeurs_valides(df: DataFrame) -> DataFrame:
    return df.where(
        (F.col("valeur_fonciere") >= PRIX_MIN)
        & (F.col("surface_bati") >= SURFACE_MIN)
        & F.col("date_mutation").isNotNull()
    ).withColumn("prix_m2", F.col("valeur_fonciere") / F.col("surface_bati"))


def avec_coordonnees(df: DataFrame) -> DataFrame:
    return df.where(F.col("lon").isNotNull() & F.col("lat").isNotNull())


def sans_aberrants(df: DataFrame) -> DataFrame:
    """Bornes IQR sur log(prix/m²) par commune et type ; département et type si < 10 ventes.

    Le prix/m² est asymétrique à droite : un IQR linéaire donne une borne basse négative
    et laisse passer les ventes symboliques (ex. 8 €/m²). En log, les bornes sont
    multiplicatives et symétriques.
    """
    logged = df.withColumn("_lp", F.log("prix_m2"))

    def bornes(keys: list[str], prefix: str) -> DataFrame:
        return (
            logged.groupBy(*keys)
            .agg(
                F.percentile_approx("_lp", [0.25, 0.75], 1000).alias("q"),
                F.count("*").alias(f"{prefix}_n"),
            )
            .select(
                *keys,
                f"{prefix}_n",
                (F.col("q")[0] - IQR_K * (F.col("q")[1] - F.col("q")[0])).alias(f"{prefix}_lo"),
                (F.col("q")[1] + IQR_K * (F.col("q")[1] - F.col("q")[0])).alias(f"{prefix}_hi"),
            )
        )

    commune = bornes(["code_commune", "type_local"], "c")
    dep = bornes(["code_departement", "type_local"], "d")
    joined = logged.join(commune, ["code_commune", "type_local"]).join(
        dep, ["code_departement", "type_local"]
    )
    use_c = F.col("c_n") >= MIN_GROUPE
    lo = F.when(use_c, F.col("c_lo")).otherwise(F.col("d_lo"))
    hi = F.when(use_c, F.col("c_hi")).otherwise(F.col("d_hi"))
    kept = joined.where((F.col("_lp") >= lo) & (F.col("_lp") <= hi))
    return kept.select(*df.columns)


def nettoyer(bronze: DataFrame) -> tuple[DataFrame, QualityReport]:
    report = QualityReport().add("Bronze (toutes lignes)", bronze.count())
    df = ventes_un_logement(bronze).cache()
    # ici l'écart avec l'étape précédente mêle lignes regroupées (1 vente = n lignes) et rejets
    report = report.add("Ventes d'un logement unique (lignes regroupées en 1/vente)", df.count())
    df = valeurs_valides(typer(df))
    report = report.add(f"Prix ≥ {PRIX_MIN:.0f} €, surface ≥ {SURFACE_MIN} m²", df.count())
    df = avec_coordonnees(df)
    report = report.add("Avec coordonnées", df.count())
    df = sans_aberrants(df)
    report = report.add(f"Sans prix/m² aberrant (IQR × {IQR_K:g} sur log)", df.count())
    return df, report
