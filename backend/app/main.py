import os

from fastapi import FastAPI

import app.db.session as db_session_module
from app.api.router import api_router
from app.core.config import settings
from app.core.e2e import identify_e2e_database
from app.middleware.correlation import CorrelationAuditMiddleware
from app.middleware.tenant_security import TenantSecurityMiddleware


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.add_middleware(TenantSecurityMiddleware)
    application.add_middleware(CorrelationAuditMiddleware)
    application.state.audit_session_factory = db_session_module.SessionLocal
    application.include_router(api_router, prefix="/v1")

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        payload = {"status": "ok"}
        environment = settings.environment.strip().lower()
        if environment in {"test", "e2e"}:
            payload["environment"] = environment
            database_marker = identify_e2e_database(os.getenv("DATABASE_URL", ""))
            if database_marker is not None:
                payload["database_marker"] = database_marker
        return payload

    return application


app = create_app()
