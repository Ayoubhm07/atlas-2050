"""Lancer l'ingestion sans Airflow : python -m atlas_pipelines.cli dvf ban dpe ..."""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.http import make_client
from atlas_pipelines.sources import ban, dpe, drias, dvf, georisques, insee, iris, ppr, rga

ORDER = ("dvf", "ban", "dpe", "insee", "iris", "georisques", "ppr", "rga", "drias")


def _runners(cfg: PipelineConfig) -> dict[str, Callable[[], dict[str, int]]]:
    def with_client(fn: Callable[..., dict[str, int]]) -> Callable[[], dict[str, int]]:
        def run() -> dict[str, int]:
            with make_client(timeout=300) as client:
                return fn(cfg, client)

        return run

    return {
        "dvf": with_client(dvf.ingest),
        "ban": with_client(ban.ingest),
        "dpe": with_client(dpe.ingest),
        "insee": with_client(insee.ingest),
        "iris": with_client(iris.ingest),
        "georisques": with_client(georisques.ingest),
        "ppr": with_client(ppr.ingest),
        "rga": with_client(rga.ingest),
        "drias": lambda: drias.ingest(cfg),
    }


def main(argv: list[str] | None = None) -> dict[str, dict[str, int]]:
    parser = argparse.ArgumentParser(description="Ingestion Open Data ATLAS 2050")
    parser.add_argument("sources", nargs="+", choices=ORDER)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = PipelineConfig.from_env()
    runners = _runners(cfg)
    results: dict[str, dict[str, int]] = {}
    for name in sorted(set(args.sources), key=ORDER.index):
        start = time.perf_counter()
        results[name] = runners[name]()
        logging.info("%s terminé en %.0f s : %s", name, time.perf_counter() - start, results[name])
    print(json.dumps(results, indent=2))  # noqa: T201 - sortie CLI
    return results


if __name__ == "__main__":
    main()
