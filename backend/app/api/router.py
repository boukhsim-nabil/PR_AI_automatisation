from fastapi import APIRouter

from app.api.routes import (
    audit,
    auth,
    crm,
    inbox,
    inbox_collaboration,
    inbox_messages,
    platform,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(audit.router)
api_router.include_router(crm.router)
api_router.include_router(inbox.router)
api_router.include_router(inbox_messages.router)
api_router.include_router(inbox_collaboration.router)
api_router.include_router(platform.router)
