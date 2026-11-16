"""Point d'entrée FastAPI.

Lancer avec `uvicorn atlas_api.main:app --no-access-log` : le journal d'accès d'uvicorn
écrit l'URL complète, donc l'adresse de /estimate ; `AccessLogMiddleware` le remplace
par méthode, chemin SANS chaîne de requête, statut et durée.
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from atlas_api import __doc__ as api_doc
from atlas_api.config import Settings, get_settings
from atlas_api.db import DatabaseUnavailableError, GoldRepository, PgRepository, open_pool
from atlas_api.envelope import Envelope, fail, ok
from atlas_api.estimator import Estimator, ModelUnavailableError, load_bundle
from atlas_api.geocode import BanGeocoder, Geocoder
from atlas_api.ratelimit import RateLimitMiddleware, TokenBucketLimiter
from atlas_api.routes import router
from atlas_api.schemas import Health
from atlas_api.state import ApiError, AppState

logger = logging.getLogger("atlas_api")
access_logger = logging.getLogger("atlas_api.access")
ESTIMATE_COST = 5.0  # une estimation consomme 5 jetons (modèle + 20 000 tirages × scénarios)
QUIET_PATHS = frozenset({"/estimate"})  # une exception pourrait citer l'adresse saisie
_INTERNAL_ERROR = json.dumps(fail("Erreur interne").model_dump()).encode()


class QuietErrorsMiddleware:
    """Enveloppe la plus externe : sur QUIET_PATHS, aucune pile ni message d'exception.

    Starlette (ServerErrorMiddleware) envoie la réponse 500 PUIS relance l'exception, et
    uvicorn journalise alors la pile complète (« Exception in ASGI application »), message
    compris. Ici l'exception est absorbée après coup : seul son type est journalisé.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in QUIET_PATHS:
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking)
        except Exception as exc:  # noqa: BLE001 - absorbée volontairement, type journalisé
            logger.error("Exception absorbée sur %s : %s", scope.get("path"), type(exc).__name__)
            if not started:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(_INTERNAL_ERROR)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": _INTERNAL_ERROR})


class AtlasApi(FastAPI):
    """FastAPI dont la pile de middlewares est enveloppée par QuietErrorsMiddleware."""

    def build_middleware_stack(self) -> ASGIApp:
        return QuietErrorsMiddleware(super().build_middleware_stack())


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


class AccessLogMiddleware:
    """Journal d'accès sans chaîne de requête (une adresse n'est jamais écrite)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            access_logger.info(
                "%s %s %d %.1fms",
                scope.get("method"),
                scope.get("path"),
                status,
                (time.perf_counter() - start) * 1000,
            )


def _load_estimator(cfg: Settings) -> Estimator | None:
    try:
        return Estimator(load_bundle(cfg.atlas_ml_dir))
    except ModelUnavailableError as exc:
        logger.error("%s : /estimate répondra 503", exc)
        return None


def create_app(
    settings: Settings | None = None,
    repository: GoldRepository | None = None,
    estimator: Estimator | None = None,
    geocoder: Geocoder | None = None,
    load_model: bool = True,
) -> FastAPI:
    """Fabrique ; les dépendances non fournies sont créées au démarrage (lifespan)."""
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        repo = repository
        if repo is None:
            pool = open_pool(
                cfg.conninfo(), cfg.api_db_pool_min, cfg.api_db_pool_max, cfg.api_db_timeout_s
            )
            repo = PgRepository(pool)
        est = estimator if estimator is not None or not load_model else _load_estimator(cfg)
        geo = geocoder or BanGeocoder(
            cfg.api_ban_url,
            cfg.api_ban_timeout_s,
            cfg.api_ban_retries,
            cfg.api_ban_min_score,
            deadline_s=cfg.api_ban_deadline_s,
            cache_size=cfg.api_ban_cache_size,
        )
        app.state.atlas = AppState(cfg, repo, est, geo)
        try:
            yield
        finally:
            if isinstance(geo, BanGeocoder) and geocoder is None:
                geo.close()
            if pool is not None:
                pool.close()

    app = AtlasApi(
        title="ATLAS 2050 API",
        description=(api_doc or "")
        + "\n\nToutes les réponses suivent l'enveloppe {success, data, error, meta}. "
        "Aucune vente isolée ni adresse n'est renvoyée (ADR 0005). Tuiles vectorielles : "
        "Martin (docs/api/README.md).",
        version="0.4.0",
        lifespan=lifespan,
    )
    capacity, period = cfg.rate_limit
    app.add_middleware(
        RateLimitMiddleware,
        limiter=TokenBucketLimiter(capacity, period),
        costs={"/estimate": ESTIMATE_COST},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_methods=["GET", "POST"],  # POST : /estimate par adresse (corps JSON)
        allow_headers=["If-None-Match", "Content-Type"],
        expose_headers=["ETag", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(NoIndexMiddleware)
    app.add_middleware(AccessLogMiddleware)
    _install_handlers(app)
    app.include_router(router)

    @app.get(
        "/health",
        response_model=Envelope[Health],
        summary="État de l'API, de la base et du modèle",
        responses={503: {"model": Envelope[Health], "description": "Base indisponible"}},
    )
    def health(request: Request) -> JSONResponse:
        st: AppState = request.app.state.atlas
        db_ok = st.repository.ping()
        body = Health(
            status="ok" if db_ok and st.estimator is not None else "degrade",
            database="ok" if db_ok else "indisponible",
            model="ok" if st.estimator is not None else "indisponible",
            departements=cfg.departements,
        )
        return JSONResponse(
            status_code=200 if db_ok else 503,
            content=ok(body).model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
    def robots() -> str:
        return "User-agent: *\nDisallow: /\n"

    return app


def _install_handlers(app: FastAPI) -> None:
    def _fail(status: int, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content=fail(message).model_dump())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # champ + message Pydantic, jamais la valeur saisie (une adresse)
        details = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', ())[1:]) or 'requête'} : {e.get('msg')}"
            for e in exc.errors()
        )
        return _fail(422, f"Paramètres invalides ({details})")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _fail(exc.status, exc.message)

    @app.exception_handler(DatabaseUnavailableError)
    async def _db_error(_: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        return _fail(503, "Base de données indisponible")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {404: "Ressource introuvable", 405: "Méthode non autorisée"}
        return _fail(exc.status_code, messages.get(exc.status_code, "Requête refusée"))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # pile d'appel journalisée sauf sur /estimate (un message pourrait citer l'adresse)
        logger.error(
            "Erreur non gérée sur %s : %s",
            request.url.path,
            type(exc).__name__,
            exc_info=None if request.url.path == "/estimate" else exc,
        )
        return _fail(500, "Erreur interne")


def _make_default_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return create_app()


app = _make_default_app()
