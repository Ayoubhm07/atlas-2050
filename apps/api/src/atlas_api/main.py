"""Point d'entrée FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from atlas_api import __doc__ as api_doc
from atlas_api.config import Settings, get_settings
from atlas_api.envelope import Envelope, fail, ok

logger = logging.getLogger("atlas_api")


class NoIndexMiddleware:
    """Interdit l'indexation par les moteurs (conditions d'usage DVF, ADR 0005)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-robots-tag", b"noindex, nofollow"))
            await send(message)

        await self.app(scope, receive, send_with_header)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    app = FastAPI(title="ATLAS 2050 API", description=api_doc, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.add_middleware(NoIndexMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=fail("Paramètres invalides").model_dump())

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Erreur non gérée sur %s", request.url.path)
        return JSONResponse(status_code=500, content=fail("Erreur interne").model_dump())

    @app.get("/health", response_model=Envelope[dict[str, object]])
    def health() -> Envelope[dict[str, object]]:
        return ok({"status": "ok", "departements": list(cfg.departements)})

    @app.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
    def robots() -> str:
        return "User-agent: *\nDisallow: /\n"

    return app


app = create_app()
