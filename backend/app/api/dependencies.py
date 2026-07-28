from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.middleware.tenant_security import AuthContext, PlatformAuthContext


def get_auth_context(request: Request) -> AuthContext:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication context missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_context


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


def get_platform_auth_context(request: Request) -> PlatformAuthContext:
    context = getattr(request.state, "platform_auth_context", None)
    if context is None:
        raise HTTPException(status_code=403, detail="Platform super administrator required")
    return context


CurrentPlatformAuth = Annotated[PlatformAuthContext, Depends(get_platform_auth_context)]
