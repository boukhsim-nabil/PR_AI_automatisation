from fastapi import APIRouter

from app.api.routes import audit, auth, crm, platform

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(audit.router)
api_router.include_router(crm.router)
api_router.include_router(platform.router)
