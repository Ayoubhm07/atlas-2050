"""Routes de données : communes, carte H3, estimation."""

import math
import unicodedata
from typing import Annotated, Any

import h3
from fastapi import APIRouter, Body, Path, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from atlas_api.db import HexFilter
from atlas_api.envelope import Envelope, Meta, ok
from atlas_api.estimator import H3_RES, NEIGHBOUR_K, NEIGHBOUR_PRIOR
from atlas_api.geocode import AddressNotFoundError, GeocodingError
from atlas_api.http_cache import NO_STORE, json_response
from atlas_api.schemas import (
    CODE_INSEE,
    CommuneHit,
    CommuneRisques,
    CommuneStats,
    EstimatePointQuery,
    EstimateQuery,
    Estimation,
    HexCell,
    HexQuery,
    Localisation,
)
from atlas_api.state import ApiError, AppState

router = APIRouter()
SOURCES_DVF = ("DVF géolocalisées (Etalab)",)
CodeInsee = Annotated[str, Path(pattern=CODE_INSEE, description="Code INSEE (5 caractères)")]
ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": Envelope[None], "description": "Paramètres refusés"},
    404: {"model": Envelope[None], "description": "Ressource introuvable"},
    422: {"model": Envelope[None], "description": "Paramètres invalides"},
    429: {"model": Envelope[None], "description": "Trop de requêtes"},
    503: {"model": Envelope[None], "description": "Base, modèle ou géocodage indisponible"},
}


def state(request: Request) -> AppState:
    st: AppState = request.app.state.atlas
    return st


def normalise_query(text: str) -> str:
    """Minuscules, sans accents (comme dim_commune.nom_recherche), espaces réduits."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(plain.lower().split())


@router.get(
    "/communes",
    response_model=Envelope[list[CommuneHit]],
    responses=ERRORS,
    summary="Recherche de commune par préfixe",
    description="Préfixe du nom, insensible à la casse et aux accents ; 10 résultats au plus, "
    "les communes les plus peuplées en adresses d'abord.",
)
def search_communes(
    request: Request,
    q: Annotated[str, Query(min_length=2, max_length=64, description="Début du nom")],
) -> Response:
    st = state(request)
    prefix = normalise_query(q)
    if len(prefix) < 2:
        raise ApiError(400, "Saisir au moins 2 caractères")
    hits = st.repository.search_communes(prefix)
    return json_response(
        request, ok(hits, Meta(total=len(hits), limit=10)), st.settings.api_cache_max_age_s
    )


def parse_bbox(raw: str, res: int, max_r7: float, max_r9: float) -> tuple[float, ...]:
    parts = raw.split(",")
    if len(parts) != 4:
        raise ApiError(400, "bbox attendu : xmin,ymin,xmax,ymax")
    try:
        xmin, ymin, xmax, ymax = (float(p) for p in parts)
    except ValueError as exc:
        raise ApiError(400, "bbox : nombres attendus") from exc
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)):
        raise ApiError(400, "bbox : valeurs finies attendues")
    if not (-180 <= xmin < xmax <= 180 and -90 <= ymin < ymax <= 90):
        raise ApiError(400, "bbox : xmin < xmax et ymin < ymax, en degrés WGS 84")
    limit = max_r7 if res == 7 else max_r9
    if (xmax - xmin) * (ymax - ymin) > limit:
        raise ApiError(400, f"bbox trop grande pour la résolution {res} (max {limit} degrés²)")
    return xmin, ymin, xmax, ymax


@router.get(
    "/hex",
    response_model=Envelope[list[HexCell]],
    responses=ERRORS,
    summary="Agrégats de prix par hexagone H3",
    description="Lus dans gold.agg_hex (≥ 5 ventes, suppression secondaire, prix arrondis "
    "à 10 €/m², ADR 0005) ; jamais calculés à la volée. Hexagones dont le centre est dans "
    "l'emprise. Au-delà du plafond de lignes, la requête est refusée (réduire l'emprise).",
)
def hex_cells(request: Request, p: Annotated[HexQuery, Query()]) -> Response:
    st = state(request)
    cfg = st.settings
    bbox = parse_bbox(p.bbox, p.res, cfg.api_hex_max_area_r7, cfg.api_hex_max_area_r9)
    f = HexFilter(p.res, bbox, p.type, p.annee, p.dpe, cfg.api_hex_max_rows + 1)  # type: ignore[arg-type]
    cells = st.repository.hex_cells(f)
    if len(cells) > cfg.api_hex_max_rows:
        raise ApiError(400, f"Plus de {cfg.api_hex_max_rows} hexagones : réduire l'emprise")
    meta = Meta(total=len(cells), limit=cfg.api_hex_max_rows, sources=SOURCES_DVF)
    return json_response(request, ok(cells, meta), cfg.api_cache_max_age_s)


@router.get(
    "/communes/{code}/stats",
    response_model=Envelope[CommuneStats],
    responses=ERRORS,
    summary="Prix d'une commune par type de bien et année",
    description="Groupes d'au moins 5 ventes ; quartiles à partir de 11 ; prix arrondis à "
    "10 €/m² (ADR 0005).",
)
def commune_stats(request: Request, code: CodeInsee) -> Response:
    st = state(request)
    stats = st.repository.commune_stats(code)
    if stats is None:
        raise ApiError(404, "Commune inconnue ou sans groupe publiable")
    meta = Meta(sources=SOURCES_DVF)
    return json_response(request, ok(stats, meta), st.settings.api_cache_max_age_s)


@router.get(
    "/communes/{code}/risques",
    response_model=Envelope[CommuneRisques],
    responses=ERRORS,
    summary="Risques naturels actuels d'une commune",
    description="Cat-Nat, TRI, PPRI, AZI (Géorisques) et répartition RGA des IRIS.",
)
def commune_risks(request: Request, code: CodeInsee) -> Response:
    st = state(request)
    risks = st.repository.commune_risks(code)
    if risks is None:
        raise ApiError(404, "Commune inconnue")
    meta = Meta(sources=("Géorisques (GASPAR, RGA)",))
    return json_response(request, ok(risks, meta), st.settings.api_cache_max_age_s)


def _locate(st: AppState, q: EstimateQuery) -> tuple[float, float, str, float | None]:
    if q.address is None:
        assert q.lon is not None and q.lat is not None  # garanti par EstimateQuery
        return q.lon, q.lat, "coordonnees", None
    try:
        point = st.geocoder.geocode(q.address)
    except AddressNotFoundError as exc:
        raise ApiError(404, "Adresse introuvable ou trop incertaine") from exc
    except GeocodingError as exc:
        raise ApiError(503, "Géocodage indisponible : réessayer ou donner lat/lon") from exc
    return point.lon, point.lat, "adresse_ban", point.score


_ESTIMATE_DOC = (
    "Renvoie le prix/m² en fourchette P10-P50-P90, les risques actuels de la commune, les "
    "scénarios 2050 (statu quo, rénovation en D, sensibilité « nouveau risque » NON CAUSALE "
    "à deux bornes, climat : « indisponible (DRIAS) », jamais chiffré) et les principaux "
    "facteurs SHAP. Réponse non mise en cache (no-store)."
)


@router.get(
    "/estimate",
    response_model=Envelope[Estimation],
    responses=ERRORS,
    summary="Estimation d'un bien fictif par coordonnées et projection 2050",
    description="Position par lat+lon et caractéristiques en chaîne de requête. Pour une "
    "adresse, utiliser POST /estimate (une adresse n'est jamais mise dans une URL). "
    + _ESTIMATE_DOC,
)
def estimate(request: Request, q: Annotated[EstimatePointQuery, Query()]) -> Response:
    return _estimate(request, q.to_query())


@router.post(
    "/estimate",
    response_model=Envelope[Estimation],
    responses=ERRORS,
    summary="Estimation d'un bien fictif par adresse ou coordonnées et projection 2050",
    description="Corps JSON : position (lat+lon, ou adresse géocodée par la BAN, jamais "
    "journalisée ni renvoyée) et caractéristiques. " + _ESTIMATE_DOC,
)
def estimate_post(request: Request, q: Annotated[EstimateQuery, Body()]) -> Response:
    return _estimate(request, q)


def _estimate(request: Request, q: EstimateQuery) -> Response:
    st = state(request)
    if st.estimator is None:
        raise ApiError(503, "Modèle de prix indisponible")
    lon, lat, source, score = _locate(st, q)
    ctx = st.repository.point_context(lon, lat)
    if ctx is None:
        raise ApiError(404, "Point hors du périmètre couvert")
    valuation = st.valuation_date()
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(lat, lon, H3_RES), 1))
    sales = st.repository.reference_sales(
        q.type_local, cells, valuation, NEIGHBOUR_K, NEIGHBOUR_PRIOR
    )
    loc = Localisation(
        code_insee=ctx.code_insee,
        nom_commune=ctx.nom_commune,
        code_iris=ctx.code_iris,
        source=source,  # type: ignore[arg-type]
        score_geocodage=score,
    )
    try:
        result = st.estimator.estimate(q, ctx, lon, lat, valuation, sales, loc)
    except ValueError as exc:
        raise ApiError(422, "Bien hors du domaine du modèle") from exc
    meta = Meta(sources=("Modèle LightGBM ATLAS (ml/report.md)", *SOURCES_DVF))
    return JSONResponse(
        content=jsonable_encoder(ok(result, meta)), headers={"Cache-Control": NO_STORE}
    )
