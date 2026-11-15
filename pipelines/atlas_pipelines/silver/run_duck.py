"""Silver DuckDB (BAN, DPE, Géorisques) : python -m atlas_pipelines.silver.run_duck ban dpe ...

DVF reste en PySpark (run_dvf) ; ces trois sources tiennent en mémoire et DuckDB les
traite en secondes sans JVM.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable

from atlas_pipelines.config import PipelineConfig
from atlas_pipelines.silver import ban, dpe, georisques

RUNNERS: dict[str, Callable[[PipelineConfig], dict[str, int]]] = {
    "ban": ban.run,
    "dpe": dpe.run,
    "georisques": georisques.run,
}


def main(argv: list[str] | None = None) -> dict[str, dict[str, int]]:
    parser = argparse.ArgumentParser(description="Silver DuckDB ATLAS 2050")
    parser.add_argument("sources", nargs="+", choices=tuple(RUNNERS))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = PipelineConfig.from_env()
    results = {name: RUNNERS[name](cfg) for name in dict.fromkeys(args.sources)}
    print(json.dumps(results, indent=2))  # noqa: T201 - sortie CLI
    return results


if __name__ == "__main__":
    main()
