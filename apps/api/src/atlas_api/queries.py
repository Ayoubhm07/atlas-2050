"""Chargement des requêtes nommées de `sql/api_queries.sql` (source unique du SQL)."""

import re
from functools import lru_cache
from importlib.resources import files

_NAME = re.compile(r"^-- name: (\w+)\s*$", flags=re.M)
_POSITIONAL = re.compile(r"\$(\d+)")


def parse(text: str) -> dict[str, str]:
    """Blocs `-- name: x` → texte SQL (sans le point-virgule final)."""
    blocks = _NAME.split(text)
    return {
        name: body.strip().rstrip(";").strip()
        for name, body in zip(blocks[1::2], blocks[2::2], strict=True)
    }


def to_psycopg(query: str) -> str:
    """$1, $2... (style PostgreSQL) → %(p1)s ; les % littéraux sont doublés."""
    return _POSITIONAL.sub(r"%(p\1)s", query.replace("%", "%%"))


def bind(*values: object) -> dict[str, object]:
    """Valeurs positionnelles → paramètres nommés p1, p2... (jamais de concaténation)."""
    return {f"p{i}": v for i, v in enumerate(values, start=1)}


def raw_text() -> str:
    return files("atlas_api").joinpath("sql/api_queries.sql").read_text(encoding="utf-8")


@lru_cache
def get(name: str) -> str:
    """Requête prête pour psycopg ; KeyError si le nom est inconnu."""
    return to_psycopg(parse(raw_text())[name])
