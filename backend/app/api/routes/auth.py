from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentAuth
from app.core.security import create_access_token, verify_password
from app.db.models import Membership, User
from app.db.session import get_db
from app.schemas.auth import AuthContextResponse, LoginRequest, TokenResponse


router = APIRouter(prefix="/auth", tags=["authentication"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DatabaseSession) -> TokenResponse:
    statement = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.email == str(payload.email).lower(),
            User.status == "active",
            Membership.company_id == payload.company_id,
            Membership.status == "active",
        )
    )
    result = db.execute(statement).one_or_none()
    user = result[0] if result else None
    membership = result[1] if result else None

    password_is_valid = verify_password(
        payload.password.get_secret_value(),
        user.password_hash if user else None,
    )
    if user is None or membership is None or not password_is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or inactive membership",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = create_access_token(
        user_id=user.id,
        company_id=membership.company_id,
        membership_id=membership.id,
        role_id=membership.role_id,
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        company_id=membership.company_id,
    )


@router.get("/context", response_model=AuthContextResponse)
def current_auth_context(auth: CurrentAuth) -> AuthContextResponse:
    return AuthContextResponse(
        user_id=auth.user_id,
        company_id=auth.company_id,
        membership_id=auth.membership_id,
        role_id=auth.role_id,
    )
