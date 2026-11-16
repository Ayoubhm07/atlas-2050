"""Limitation de débit en mémoire : un seau à jetons par IP cliente.

Suffisant pour une instance unique (un worker). Plusieurs workers ou instances : chaque
processus a ses seaux, la limite effective est multipliée (passer à Redis ou au proxy).

La clé est `scope["client"]`, jamais un en-tête lu ici. Derrière un proxy, c'est
uvicorn qui remplace l'IP de la socket par celle de X-Forwarded-For (`--proxy-headers`),
et SEULEMENT si le pair figure dans FORWARDED_ALLOW_IPS (défaut 127.0.0.1 dans l'image) :
un client direct ne peut donc pas choisir son identité. Les adresses IPv6 sont groupées
par /64 (un abonné reçoit en général un /64 entier et en changerait à volonté).
"""

import ipaddress
import json
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from starlette.types import ASGIApp, Receive, Scope, Send

from atlas_api.envelope import fail

EXEMPT_PATHS = frozenset({"/health", "/robots.txt"})


class TokenBucketLimiter:
    """Seaux par clé, bornés en nombre (les moins récents sont oubliés). Thread-safe."""

    def __init__(
        self,
        capacity: int,
        period_s: float,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1 or period_s <= 0 or max_keys < 1:
            raise ValueError("capacity ≥ 1, period_s > 0, max_keys ≥ 1")
        self.capacity = float(capacity)
        self.rate = capacity / period_s  # jetons par seconde
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def acquire(self, key: str, cost: float = 1.0) -> float:
        """0 si la requête passe, sinon secondes à attendre avant le prochain jeton."""
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.pop(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                wait = 0.0
            else:
                self._buckets[key] = (tokens, now)
                wait = (cost - tokens) / self.rate
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
        return wait


IPV6_PREFIX = 64


def client_key(scope: Scope) -> str:
    """IPv4 telle quelle ; IPv6 ramenée à son /64 ; IPv4 mappée en IPv6 → IPv4."""
    client = scope.get("client")
    if not client:
        return "inconnu"
    host = str(client[0])
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host  # nom ou valeur de test : clé brute
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, IPV6_PREFIX), strict=False))
    return str(ip)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        limiter: TokenBucketLimiter,
        costs: dict[str, float] | None = None,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.costs = costs or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or path in EXEMPT_PATHS or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        wait = self.limiter.acquire(client_key(scope), self.costs.get(path, 1.0))
        if wait <= 0:
            await self.app(scope, receive, send)
            return
        body = json.dumps(fail("Trop de requêtes : réessayer plus tard").model_dump()).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"retry-after", str(max(1, math.ceil(wait))).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
