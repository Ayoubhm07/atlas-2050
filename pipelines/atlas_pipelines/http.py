"""Client HTTP commun : téléchargement en streaming, checksum, retries, limiteur de débit."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

USER_AGENT = "atlas-2050-pipeline/0.1 (projet etudiant open data)"
CHUNK = 1 << 20


def make_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


retrying = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    reraise=True,
)


class RateLimiter:
    """Garantit un intervalle minimal entre deux appels (thread-safe)."""

    def __init__(self, calls_per_second: float) -> None:
        if calls_per_second <= 0:
            raise ValueError("calls_per_second doit être > 0")
        self._interval = 1.0 / calls_per_second
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            time.sleep(delay)


@dataclass(frozen=True)
class Manifest:
    url: str
    path: str
    sha256: str
    bytes: int
    downloaded_at: str
    etag: str | None = None
    last_modified: str | None = None


def staging(dest: Path) -> Path:
    """Fichier temporaire caché (préfixe « . ») : Spark et DuckDB l'ignorent en lecture."""
    return dest.with_name(f".{dest.name}.part")


def manifest_path(dest: Path) -> Path:
    return dest.with_name(dest.name + ".manifest.json")


def read_manifest(dest: Path) -> Manifest | None:
    """Manifeste du fichier local, seulement si le fichier a encore la taille déclarée."""
    mp = manifest_path(dest)
    if not (mp.exists() and dest.exists()):
        return None
    manifest = Manifest(**json.loads(mp.read_text(encoding="utf-8")))
    if dest.stat().st_size != manifest.bytes:
        logger.warning("Taille locale incohérente, retéléchargement : %s", dest)
        return None
    return manifest


def _conditional_headers(existing: Manifest | None, url: str) -> dict[str, str]:
    if existing is None or existing.url != url:
        return {}
    headers = {}
    if existing.etag:
        headers["If-None-Match"] = existing.etag
    if existing.last_modified:
        headers["If-Modified-Since"] = existing.last_modified
    return headers


@retrying
def download(client: httpx.Client, url: str, dest: Path, *, force: bool = False) -> Manifest:
    """Télécharge `url` vers `dest` de façon atomique et idempotente.

    Si un fichier local existe pour la même URL, la requête est conditionnelle
    (ETag / Last-Modified) : réponse 304 → fichier local réutilisé. Les URL fixes de
    type `latest/` sont ainsi rafraîchies quand leur contenu change. Sans en-têtes de
    validation côté serveur, le fichier local est réutilisé (sauf `force=True`).
    """
    existing = read_manifest(dest)
    headers = {} if force else _conditional_headers(existing, url)
    if existing and existing.url == url and not force and not headers:
        logger.info("Déjà présent (serveur sans validation), réutilisé : %s", dest)
        return existing

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = staging(dest)
    digest = hashlib.sha256()
    size = 0
    with client.stream("GET", url, headers=headers) as res:
        if res.status_code == 304 and existing is not None:
            logger.info("Inchangé côté serveur (304), réutilisé : %s", dest)
            return existing
        res.raise_for_status()
        etag = res.headers.get("ETag")
        last_modified = res.headers.get("Last-Modified")
        with tmp.open("wb") as fh:
            for chunk in res.iter_bytes(CHUNK):
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Fichier vide reçu depuis {url}")
    tmp.replace(dest)
    manifest = Manifest(
        url=url,
        path=dest.name,
        sha256=digest.hexdigest(),
        bytes=size,
        downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        etag=etag,
        last_modified=last_modified,
    )
    manifest_path(dest).write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
    logger.info("Téléchargé %s (%d octets)", dest, size)
    return manifest


@retrying
def get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    limiter: RateLimiter | None = None,
) -> Any:
    if limiter:
        limiter.wait()
    res = client.get(url, params=params)
    res.raise_for_status()
    return res.json()
