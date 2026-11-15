"""Suivi MLflow : serveur du compose s'il répond, sinon magasin fichier local `mlruns/`."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def resolve_tracking_uri(preferred: str | None, fallback_dir: Path, timeout: float = 2.0) -> str:
    """URI http joignable (`/health` = 200), sinon `file:` vers `fallback_dir`."""
    if preferred and preferred.startswith(("http://", "https://")):
        try:
            res = httpx.get(preferred.rstrip("/") + "/health", timeout=timeout)
            if res.status_code == 200:
                return preferred
            logger.warning("MLflow %s : HTTP %d", preferred, res.status_code)
        except httpx.HTTPError as exc:
            logger.warning("MLflow %s injoignable (%s) : magasin local", preferred, exc)
    elif preferred:
        return preferred
    fallback_dir.mkdir(parents=True, exist_ok=True)
    return fallback_dir.resolve().as_uri()


def flatten(prefix: str, value: Any) -> dict[str, float]:
    """{"a": {"b": 1}} → {"prefix.a.b": 1.0} ; ne garde que les nombres finis."""
    out: dict[str, float] = {}
    if isinstance(value, Mapping):
        for k, v in value.items():
            out.update(flatten(f"{prefix}.{k}" if prefix else str(k), v))
    elif isinstance(value, bool):
        out[prefix] = float(value)
    elif isinstance(value, int | float) and value == value and abs(value) != float("inf"):
        out[prefix] = float(value)
    return out


def sanitize(key: str) -> str:
    """Clés MLflow : alphanumériques ASCII, _ - . / et espace."""
    return "".join(c if (c.isascii() and c.isalnum()) or c in "_-./ " else "_" for c in key)
