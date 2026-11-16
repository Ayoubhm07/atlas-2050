"""Latence p50 / p95 de chaque route, en processus, sur le PostGIS et le modèle réels.

    cd apps/api && .venv/Scripts/python.exe scripts/measure_latency.py [n]

TestClient (pas de réseau) : mesure l'application + PostGIS + modèle, pas le transport.
3 appels à blanc puis n appels mesurés par route (cache PostgreSQL chaud, sans ETag).
"""

import statistics
import sys
import time

from fastapi.testclient import TestClient

from atlas_api.config import Settings
from atlas_api.main import create_app

ROUTES: dict[str, tuple[str, dict[str, object]]] = {
    "GET /health": ("/health", {}),
    "GET /communes?q=bord": ("/communes", {"q": "bord"}),
    "GET /hex r9 Bordeaux": ("/hex", {"bbox": "-0.75,44.75,-0.45,44.95", "res": 9}),
    "GET /hex r7 Gironde": ("/hex", {"bbox": "-1.3,44.2,0.3,45.6", "res": 7}),
    "GET /communes/33063/stats": ("/communes/33063/stats", {}),
    "GET /communes/33063/risques": ("/communes/33063/risques", {}),
    "GET /estimate (lat/lon, maison G)": (
        "/estimate",
        {"lat": 44.8378, "lon": -0.5792, "type_local": "Maison", "surface": 96,
         "pieces": 4, "surface_terrain": 760, "dpe": "G"},
    ),
}


def pct(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def main(n: int) -> None:
    cfg = Settings(api_rate_limit="1000000/minute")
    with TestClient(create_app(cfg)) as client:
        print("| Route | n | p50 (ms) | p95 (ms) |\n|---|---|---|---|")
        for label, (path, params) in ROUTES.items():
            for _ in range(3):
                client.get(path, params=params)
            times = []
            for _ in range(n):
                t0 = time.perf_counter()
                res = client.get(path, params=params)
                times.append((time.perf_counter() - t0) * 1000)
                if res.status_code != 200:
                    raise SystemExit(f"{label} : HTTP {res.status_code} {res.text[:200]}")
            print(f"| {label} | {n} | {pct(times, 50):.1f} | {pct(times, 95):.1f} |")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 50)
