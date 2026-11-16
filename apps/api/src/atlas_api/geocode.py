"""Géocodage d'adresse par la BAN (api-adresse.data.gouv.fr).

- échéance globale (≤ 3 s, toutes tentatives comprises) : chaque tentative a pour délai
  le temps restant, aucune nouvelle tentative une fois l'échéance passée ;
- nouvelles tentatives sur erreur réseau ou 5xx seulement ; un 429 (quota BAN dépassé)
  échoue tout de suite : insister aggraverait le dépassement ;
- petit cache LRU en mémoire des points trouvés (adresse normalisée → point), jamais
  écrit sur disque ni journalisé ; il évite de rappeler la BAN pour une même adresse ;
- réponse validée (schéma Pydantic, coordonnées finies, score minimal) ;
- l'adresse n'est JAMAIS journalisée ni renvoyée : seuls le point et le score sortent.
"""

import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("atlas_api.geocode")
# httpx journalise chaque URL en INFO, chaîne de requête comprise (donc l'adresse) :
# ses journaux et ceux de httpcore sont limités aux avertissements.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
USER_AGENT = "atlas-2050-api/0.1"
_RETRYABLE = frozenset({500, 502, 503, 504})
MAX_DEADLINE_S = 3.0
CACHE_SIZE = 256


class GeocodingError(RuntimeError):
    """Service BAN injoignable ou réponse invalide (503 côté API)."""


class AddressNotFoundError(LookupError):
    """Aucune adresse assez sûre (404 côté API)."""


@dataclass(frozen=True)
class GeocodedPoint:
    lon: float
    lat: float
    score: float
    citycode: str


class Geocoder(Protocol):
    def geocode(self, address: str) -> GeocodedPoint: ...


class _Geometry(BaseModel):
    type: str
    coordinates: tuple[float, float]


class _Properties(BaseModel):
    score: float
    citycode: str


class _Feature(BaseModel):
    geometry: _Geometry
    properties: _Properties


class _Collection(BaseModel):
    features: list[_Feature]


class BanGeocoder:
    def __init__(
        self,
        url: str,
        timeout: float,
        retries: int,
        min_score: float,
        transport: httpx.BaseTransport | None = None,
        deadline_s: float = MAX_DEADLINE_S,
        cache_size: int = CACHE_SIZE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < deadline_s <= MAX_DEADLINE_S or cache_size < 0:
            raise ValueError(f"deadline_s dans ]0, {MAX_DEADLINE_S}], cache_size ≥ 0")
        self.url = url
        self.retries = retries
        self.min_score = min_score
        self.timeout = timeout
        self.deadline_s = deadline_s
        self.clock = clock
        self.cache_size = cache_size
        self._cache: OrderedDict[str, GeocodedPoint] = OrderedDict()
        self._lock = threading.Lock()
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": USER_AGENT},
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, address: str) -> httpx.Response:
        params = {"q": address, "limit": "1", "type": "housenumber"}
        deadline = self.clock() + self.deadline_s
        last: str = ""
        for attempt in range(self.retries + 1):
            remaining = deadline - self.clock()
            if remaining <= 0:
                last = last or "échéance"
                break
            try:
                res = self.client.get(
                    self.url, params=params, timeout=min(self.timeout, remaining)
                )
            except httpx.TransportError as exc:
                last = type(exc).__name__
            else:
                if res.status_code == 429:
                    raise GeocodingError("BAN : quota dépassé (HTTP 429)")
                if res.status_code not in _RETRYABLE:
                    return res
                last = f"HTTP {res.status_code}"
            logger.warning("BAN : tentative %d en échec (%s)", attempt + 1, last)
        raise GeocodingError(f"BAN indisponible ({last})")

    @staticmethod
    def cache_key(address: str) -> str:
        return " ".join(address.casefold().split())

    def _cached(self, key: str) -> GeocodedPoint | None:
        with self._lock:
            point = self._cache.get(key)
            if point is not None:
                self._cache.move_to_end(key)
            return point

    def _remember(self, key: str, point: GeocodedPoint) -> None:
        if self.cache_size == 0:
            return
        with self._lock:
            self._cache[key] = point
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def geocode(self, address: str) -> GeocodedPoint:
        key = self.cache_key(address)
        cached = self._cached(key)
        if cached is not None:
            return cached
        point = self._lookup(address)
        self._remember(key, point)
        return point

    def _lookup(self, address: str) -> GeocodedPoint:
        res = self._get(address)
        if res.status_code == 400:
            raise AddressNotFoundError("Adresse non reconnue")
        if res.status_code != 200:
            raise GeocodingError(f"BAN : HTTP {res.status_code}")
        try:
            data = _Collection.model_validate_json(res.content)
        except ValidationError as exc:
            raise GeocodingError("BAN : réponse invalide") from exc
        if not data.features:
            raise AddressNotFoundError("Adresse introuvable")
        feat = data.features[0]
        lon, lat = feat.geometry.coordinates
        if feat.geometry.type != "Point" or not (math.isfinite(lon) and math.isfinite(lat)):
            raise GeocodingError("BAN : géométrie invalide")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise GeocodingError("BAN : coordonnées hors bornes")
        if feat.properties.score < self.min_score:
            raise AddressNotFoundError("Adresse trop incertaine")
        return GeocodedPoint(lon, lat, round(feat.properties.score, 2), feat.properties.citycode)
