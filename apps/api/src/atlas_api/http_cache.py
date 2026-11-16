"""Réponses JSON avec ETag (empreinte du corps) et Cache-Control.

Les agrégats ne changent qu'au rechargement du gold : un client qui renvoie
`If-None-Match` reçoit 304 sans corps. L'estimation, elle, n'est jamais mise en cache
partagé (`no-store`) : sa requête peut contenir une adresse.
"""

import hashlib
import json

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

NO_STORE = "no-store"


def _etag(body: bytes) -> str:
    return 'W/"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    tags = {t.strip() for t in header.split(",")}
    return "*" in tags or etag in tags or etag.removeprefix("W/") in tags


def json_response(request: Request, payload: BaseModel, max_age: int) -> Response:
    body = json.dumps(
        jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    etag = _etag(body)
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}", "Vary": "Origin"}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
