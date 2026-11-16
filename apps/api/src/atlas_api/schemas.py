"""Modèles Pydantic v2 des entrées et sorties de l'API."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TypeLocal = Literal["Maison", "Appartement"]
TypeFiltre = Literal["Maison", "Appartement", "tous"]
Dpe = Literal["A", "B", "C", "D", "E", "F", "G"]
DpeFiltre = Literal["A", "B", "C", "D", "E", "F", "G", "tous"]
CODE_INSEE = r"^(\d{5}|2[AB]\d{3})$"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- communes -----------------------------------------------------------------------


class CommuneHit(Frozen):
    code_insee: str
    nom_commune: str
    code_departement: str
    lon: float
    lat: float


class StatsGroupe(Frozen):
    """Groupe (type, année) d'au moins 5 ventes ; quartiles à partir de 11 (ADR 0005)."""

    type_local: str
    annee: int
    n_ventes: int = Field(ge=5)
    prix_m2_q1: float | None = Field(description="null sous 11 ventes")
    prix_m2_median: float
    prix_m2_q3: float | None = Field(description="null sous 11 ventes")
    surface_mediane: float = Field(description="Surface habitable médiane, arrondie à 5 m²")


class CommuneStats(Frozen):
    code_insee: str
    groupes: tuple[StatsGroupe, ...]


class CommuneRisques(Frozen):
    code_insee: str
    nom_commune: str
    n_catnat: int | None
    n_catnat_10ans: int | None
    date_reference: dt.date | None
    in_tri: bool | None
    ppri: bool | None
    n_ppr: int | None
    azi: str | None
    rga_iris: dict[str, int] = Field(
        default_factory=dict, description="Nombre d'IRIS de la commune par exposition RGA"
    )


# --- carte H3 -----------------------------------------------------------------------


class HexCell(Frozen):
    h3: str
    n_ventes: int = Field(ge=5)
    prix_m2_median: int


class HexQuery(Frozen):
    bbox: str = Field(
        description="Emprise « xmin,ymin,xmax,ymax » en degrés WGS 84 (EPSG:4326)",
        max_length=120,
        examples=["-0.75,44.75,-0.45,44.95"],
    )
    res: int = Field(description="Résolution H3 : 7 (≈ 5 km²) ou 9 (≈ 0,1 km²)", ge=7, le=9)
    type: TypeFiltre = "tous"
    dpe: DpeFiltre = "tous"
    annee: str = Field(default="tous", pattern=r"^(tous|20\d\d)$")

    @field_validator("res")
    @classmethod
    def _res(cls, value: int) -> int:
        if value not in (7, 9):
            raise ValueError("res vaut 7 ou 9")
        return value


# --- estimation ---------------------------------------------------------------------


class BienFictif(Frozen):
    """Caractéristiques du bien FICTIF décrit par l'utilisateur."""

    type_local: TypeLocal
    surface: float = Field(ge=9, le=1000, description="Surface habitable, m²")
    pieces: int = Field(ge=1, le=30)
    surface_terrain: float | None = Field(default=None, ge=0, le=10_000)
    dependances: int = Field(default=0, ge=0, le=10)
    dpe: Dpe | None = None


class EstimatePointQuery(BienFictif):
    """GET /estimate : coordonnées seulement. Une adresse n'entre jamais dans une URL
    (journaux de proxy, historique du navigateur) : elle passe par POST /estimate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    def to_query(self) -> "EstimateQuery":
        return EstimateQuery(**self.model_dump())


class EstimateQuery(BienFictif):
    """POST /estimate (corps JSON) : position (coordonnées OU adresse) + bien."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(
        default=None,
        min_length=5,
        max_length=200,
        description="Adresse géocodée par la BAN ; jamais journalisée ni renvoyée",
    )

    @model_validator(mode="after")
    def _one_location(self) -> "EstimateQuery":
        has_point = self.lat is not None and self.lon is not None
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat et lon vont ensemble")
        if has_point == (self.address is not None):
            raise ValueError("Fournir soit lat+lon, soit address")
        return self


class Fourchette(Frozen):
    p10: float
    p50: float
    p90: float


class Localisation(Frozen):
    code_insee: str
    nom_commune: str
    code_iris: str
    source: Literal["coordonnees", "adresse_ban"]
    score_geocodage: float | None = None


class RisquesActuels(Frozen):
    termes: tuple[str, ...] = Field(description="Risques déjà présents, déjà dans le prix")
    n_catnat_10ans: int | None
    in_tri: bool | None
    ppri: bool | None
    azi: str | None
    rga_exposition: str | None


class Sensibilite(Frozen):
    statut: str
    risques: tuple[str, ...]
    avec_voisinage: Fourchette
    sans_voisinage: Fourchette


class Scenario(Frozen):
    id: str
    libelle: str
    statut: Literal["calcule", "non_applicable", "indisponible (DRIAS)", "effet_non_estime"]
    message: str | None = None
    prix_m2: Fourchette | None = None
    valeur: Fourchette | None = None
    location_interdite_depuis: int | None = None
    composantes: tuple[str, ...] = ()
    non_inclus: tuple[str, ...] = ()
    sensibilite: Sensibilite | None = None


class Facteur(Frozen):
    variable: str
    libelle: str
    contribution_pct: float = Field(description="Effet multiplicatif sur le prix, en %")
    valeur: float | None = Field(
        default=None, description="Valeur d'entrée (null pour les variables de voisinage)"
    )


class Explication(Frozen):
    """Bouclage du waterfall SHAP (TreeSHAP natif, log-prix additif).

    prix_m2_modele = base_prix_m2 × Π(1 + contribution_pct/100 des facteurs) ×
    (1 + autres_pct/100), aux arrondis près. Prédiction ponctuelle du modèle, distincte
    de la médiane P50 de la fourchette (tirée avec les résidus).
    """

    base_prix_m2: float = Field(
        description="Prix/m² de référence du modèle (valeur attendue, tous biens), arrondi 10 €"
    )
    autres_pct: float = Field(
        description="Effet multiplicatif cumulé des variables hors des facteurs listés, en %"
    )
    prix_m2_modele: float = Field(
        description="Prédiction ponctuelle du modèle (€/m², arrondie 10 €), avant incertitude"
    )


class Estimation(Frozen):
    localisation: Localisation
    date_valeur: dt.date
    type_local: TypeLocal
    surface: float
    prix_m2: Fourchette
    valeur: Fourchette
    risques_actuels: RisquesActuels
    horizon: int
    scenarios: tuple[Scenario, ...]
    facteurs: tuple[Facteur, ...]
    explication: Explication
    avertissements: tuple[str, ...]


# --- santé --------------------------------------------------------------------------


class Health(Frozen):
    status: Literal["ok", "degrade"]
    database: Literal["ok", "indisponible"]
    model: Literal["ok", "indisponible"]
    departements: tuple[str, ...]
