"""Application entrypoint: app factory, middleware, routers and static front-end."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .api.admin.logo import router as admin_logo_router
from .api.admin.services import router as admin_services_router
from .api.admin.users import router as admin_users_router
from .api.me import router as me_router
from .api.services import router as services_router
from .auth.routes import router as auth_router
from .config import get_settings
from .database import init_db
from .seed import run_seed

STATIC_DIR = Path(__file__).parent / "static"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; base-uri 'none'; form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, secure: bool) -> None:
        super().__init__(app)
        self._secure = secure

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if self._secure:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    run_seed()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    # Order matters: add_middleware is LIFO, so the last one added is outermost.
    # Starlette (1.x): http-only is enforced internally & not configurable; the
    # other cookie flags map to session_cookie / same_site / https_only.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.cookie_name,
        max_age=settings.cookie_max_age,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.add_middleware(SecurityHeadersMiddleware, secure=settings.cookie_secure)

    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(services_router)
    app.include_router(admin_users_router)
    app.include_router(admin_services_router)
    app.include_router(admin_logo_router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/brand", tags=["meta"])
    def brand() -> dict[str, str]:
        # Public: the front-end shows the (self-hosted) app name on the
        # login screen before any authentication.
        return {"name": settings.app_name}

    @app.get("/manifest.json", include_in_schema=False)
    def web_manifest() -> Response:
        # Served dynamically so DASH_APP_NAME shows up on the install prompt
        # and the "Add to home screen" label.
        return JSONResponse(
            {
                "name": settings.app_name,
                "short_name": settings.app_name[:16],
                "description": "Self-hosted health dashboard for your services.",
                "id": "/",
                "start_url": "/",
                "scope": "/",
                "display": "standalone",
                "background_color": "#0f1218",
                "theme_color": "#0f1218",
                "icons": [
                    {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                    {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
                ],
            }
        )

    app.frontend("/", directory=str(STATIC_DIR))
    return app


app = create_app()
