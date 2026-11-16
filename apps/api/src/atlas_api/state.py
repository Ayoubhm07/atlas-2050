"""Ressources partagées de l'application (dépôt, modèle, géocodeur) et erreurs métier."""

import datetime as dt
import threading
from dataclasses import dataclass, field

from atlas_api.config import Settings
from atlas_api.db import GoldRepository
from atlas_api.estimator import Estimator
from atlas_api.geocode import Geocoder


class ApiError(Exception):
    """Erreur destinée au client : statut HTTP et message sûr (aucun détail interne)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class AppState:
    settings: Settings
    repository: GoldRepository
    estimator: Estimator | None
    geocoder: Geocoder
    _valuation: dt.date | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def valuation_date(self) -> dt.date:
        """Lendemain de la dernière vente du gold, lu une fois puis gardé en mémoire."""
        with self._lock:
            if self._valuation is None:
                self._valuation = self.repository.valuation_date()
            if self._valuation is None:
                raise ApiError(503, "Aucune vente dans le gold : estimation impossible")
            return self._valuation
