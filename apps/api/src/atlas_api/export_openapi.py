"""Exporte le schéma OpenAPI vers docs/api/openapi.json (sans base ni modèle).

    python -m atlas_api.export_openapi [chemin]
"""

import json
import sys
from pathlib import Path

from atlas_api.config import Settings

DEFAULT = Path(__file__).resolve().parents[4] / "docs" / "api" / "openapi.json"


def render() -> str:
    from atlas_api.main import create_app

    app = create_app(Settings(), load_model=False)
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0]) if args else DEFAULT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
