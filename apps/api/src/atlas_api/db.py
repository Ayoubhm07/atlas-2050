"""Accès au gold PostGIS : protocole du dépôt et implémentation psycopg 3 (pool).

Toutes les requêtes viennent de `sql/api_queries.sql` et sont paramétrées (aucune
valeur saisie n'est concaténée au SQL). Les connexions sont en lecture seule
(`default_transaction_read_only`) avec un `statement_timeout` (config.Settings.conninfo).
"""

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from atlas_api import queries
from atlas_api.schemas import CommuneHit, CommuneRisques, CommuneStats, HexCell, StatsGroupe

logger = logging.getLogger("atlas_api.db")


class DatabaseUnavailableError(RuntimeError):
    """Base injoignable ou requête en échec (message interne, jamais renvoyé au client)."""


@dataclass(frozen=True)
class PointContext:
    """Variables lues au point : IRIS, commune, risques (aucune donnée de vente)."""

    code_iris: str
    code_insee: str
    nom_commune: str
    revenu_median: float | None
    gini: float | None
    rga_code: int | None
    rga_exposition: str | None
    n_catnat_10ans: int | None
    in_tri: bool | None
    ppri: bool | None
    azi: str | None


@dataclass(frozen=True)
class ReferenceSale:
    """Vente de référence du voisinage : usage interne au calcul, jamais renvoyée."""

    date_mutation: dt.date
    h3_r7: str
    prix_m2: float


@dataclass(frozen=True)
class HexFilter:
    res: int
    bbox: tuple[float, float, float, float]
    type_local: str
    annee: str
    dpe: str
    limit: int


class GoldRepository(Protocol):
    def ping(self) -> bool: ...
    def search_communes(self, prefix: str) -> list[CommuneHit]: ...
    def hex_cells(self, f: HexFilter) -> list[HexCell]: ...
    def commune_stats(self, code_insee: str) -> CommuneStats | None: ...
    def commune_risks(self, code_insee: str) -> CommuneRisques | None: ...
    def point_context(self, lon: float, lat: float) -> PointContext | None: ...
    def valuation_date(self) -> dt.date | None: ...
    def reference_sales(
        self, type_local: str, cells: Sequence[str], before: dt.date, k: int, n_prior: int
    ) -> list[ReferenceSale]: ...


def escape_like(text: str) -> str:
    """Neutralise les jokers LIKE (échappement par défaut : antislash)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _int(v: Any) -> int | None:
    return None if v is None else int(v)


def _float(v: Any) -> float | None:
    return None if v is None else float(v)


class PgRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def _fetch(self, name: str, *params: object) -> list[dict[str, Any]]:
        try:
            with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(queries.get(name), queries.bind(*params))
                return list(cur.fetchall())
        except Exception as exc:  # psycopg.Error, PoolTimeout...
            logger.error("Requête %s en échec : %s", name, type(exc).__name__)
            raise DatabaseUnavailableError(name) from exc

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=2.0) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("Base injoignable : %s", type(exc).__name__)
            return False

    def search_communes(self, prefix: str) -> list[CommuneHit]:
        return [CommuneHit(**r) for r in self._fetch("commune_search", escape_like(prefix))]

    def hex_cells(self, f: HexFilter) -> list[HexCell]:
        rows = self._fetch(
            "hex_aggregates", f.res, *f.bbox, f.type_local, f.annee, f.dpe, f.limit
        )
        return [HexCell(**r) for r in rows]

    def commune_stats(self, code_insee: str) -> CommuneStats | None:
        rows = self._fetch("commune_transaction_stats", code_insee)
        if not rows:
            return None
        groupes = tuple(
            StatsGroupe(
                type_local=r["type_local"],
                annee=int(r["annee"]),
                n_ventes=int(r["n_ventes"]),
                prix_m2_q1=_float(r["prix_m2_q1"]),
                prix_m2_median=float(r["prix_m2_median"]),
                prix_m2_q3=_float(r["prix_m2_q3"]),
                surface_mediane=float(r["surface_mediane"]),
            )
            for r in rows
        )
        return CommuneStats(code_insee=code_insee, groupes=groupes)

    def commune_risks(self, code_insee: str) -> CommuneRisques | None:
        rows = self._fetch("commune_risks", code_insee)
        if not rows:
            return None
        r = rows[0]
        rga = {str(k): int(v) for k, v in (r["rga_iris"] or {}).items()}
        return CommuneRisques(
            code_insee=r["code_insee"],
            nom_commune=r["nom_commune"],
            n_catnat=_int(r["n_catnat"]),
            n_catnat_10ans=_int(r["n_catnat_10ans"]),
            date_reference=r["date_reference"],
            in_tri=r["in_tri"],
            ppri=r["ppri"],
            n_ppr=_int(r["n_ppr"]),
            azi=r["azi"],
            rga_iris=rga,
        )

    def point_context(self, lon: float, lat: float) -> PointContext | None:
        rows = self._fetch("point_lookup", lon, lat)
        if not rows:
            return None
        r = rows[0]
        return PointContext(
            code_iris=r["code_iris"],
            code_insee=r["code_insee"],
            nom_commune=r["nom_commune"],
            revenu_median=_float(r["revenu_median"]),
            gini=_float(r["gini"]),
            rga_code=_int(r["rga_code_exposition"]),
            rga_exposition=r["rga_exposition"],
            n_catnat_10ans=_int(r["n_catnat_10ans"]),
            in_tri=r["in_tri"],
            ppri=r["ppri"],
            azi=r["azi"],
        )

    def valuation_date(self) -> dt.date | None:
        rows = self._fetch("valuation_date")
        last = rows[0]["derniere_vente"] if rows else None
        return None if last is None else last + dt.timedelta(days=1)

    def reference_sales(
        self, type_local: str, cells: Sequence[str], before: dt.date, k: int, n_prior: int
    ) -> list[ReferenceSale]:
        rows = self._fetch("neighbour_sales", type_local, list(cells), before, k, n_prior)
        rows.sort(key=lambda r: (r["date_mutation"], r["id_mutation"]))
        return [ReferenceSale(r["date_mutation"], r["h3_r7"], float(r["prix_m2"])) for r in rows]


def open_pool(conninfo: str, min_size: int, max_size: int, timeout: float) -> ConnectionPool:
    """Pool ouvert sans attendre la base : l'API démarre même si PostGIS est en retard."""
    pool: ConnectionPool = ConnectionPool(
        conninfo, min_size=min_size, max_size=max_size, timeout=timeout, open=False
    )
    pool.open(wait=False)
    return pool
