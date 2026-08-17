from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.applications import router as applications_router
from app.api.routes.documents import router as documents_router
from app.api.routes.analyses import router as analyses_router
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.request_limits import DocumentUploadRequestLimitMiddleware, RequestIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application using a complete, validated server configuration."""
    settings = settings if settings is not None else get_settings()
    app = FastAPI(title="AI Admission Interview Coach API")
    app.add_middleware(DocumentUploadRequestLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    install_exception_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(applications_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(analyses_router, prefix="/api/v1")
    return app


app = create_app()
