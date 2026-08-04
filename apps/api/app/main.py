from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers


def _cors_origin(settings: Settings | None) -> str:
    """Use the validated setting when supplied, with its documented default in tests."""
    if settings is not None:
        return settings.web_origin
    return str(Settings.model_fields["web_origin"].default)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="AI Admission Interview Coach API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_cors_origin(settings)],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied_request_id = request.headers.get("X-Request-ID")
        try:
            request_id = str(UUID(supplied_request_id)) if supplied_request_id else str(uuid4())
        except ValueError:
            request_id = str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    install_exception_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    return app


try:
    # The production ASGI application uses validated settings.  Keeping the
    # factory usable without server-only settings lets health/unit-test apps be
    # constructed independently of database credentials.
    app = create_app(get_settings())
except ValidationError:
    app = create_app()
