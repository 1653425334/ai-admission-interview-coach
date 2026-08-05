from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.applications import router as applications_router
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application using a complete, validated server configuration."""
    settings = settings if settings is not None else get_settings()
    app = FastAPI(title="AI Admission Interview Coach API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
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
    app.include_router(applications_router, prefix="/api/v1")
    return app


app = create_app()
