from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.middleware.tenant_security import AuthContext


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
