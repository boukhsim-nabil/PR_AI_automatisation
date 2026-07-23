from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AuthSession, Membership, RefreshToken, User

AUTH_COOKIE_PATH = "/v1/auth"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token(company_id: UUID) -> str:
    return f"{company_id}.{secrets.token_urlsafe(48)}"


def refresh_company_id(token: str) -> UUID:
    company, separator, secret = token.partition(".")
    if not separator or len(secret) < 32:
        raise ValueError("Malformed refresh token")
    return UUID(company)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(
    db: Session,
    *,
    user: User,
    membership: Membership,
    request: Request,
) -> tuple[AuthSession, str, str]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    refresh_token = generate_refresh_token(membership.company_id)
    csrf_token = generate_csrf_token()
    auth_session = AuthSession(
        user_id=user.id,
        membership_id=membership.id,
        company_id=membership.company_id,
        expires_at=expires_at,
        csrf_token_hash=token_hash(csrf_token),
        user_agent=request.headers.get("user-agent", "")[:500] or None,
        ip_address=request.client.host[:45] if request.client else None,
    )
    db.add(auth_session)
    db.flush()
    db.add(
        RefreshToken(
            session_id=auth_session.id,
            token_hash=token_hash(refresh_token),
            expires_at=expires_at,
        )
    )
    db.flush()
    return auth_session, refresh_token, csrf_token


def set_session_cookies(
    response: Response,
    *,
    refresh_token: str,
    csrf_token: str,
    max_age: int,
) -> None:
    secure = settings.environment.lower() in {"production", "staging"}
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=AUTH_COOKIE_PATH,
        max_age=max_age,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        path=AUTH_COOKIE_PATH,
        max_age=max_age,
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.refresh_cookie_name, path=AUTH_COOKIE_PATH)
    response.delete_cookie(settings.csrf_cookie_name, path=AUTH_COOKIE_PATH)


def require_csrf(request: Request, auth_session: AuthSession) -> None:
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("x-csrf-token", "")
    valid = (
        bool(cookie_token)
        and hmac.compare_digest(cookie_token, header_token)
        and hmac.compare_digest(token_hash(header_token), auth_session.csrf_token_hash)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


def revoke_session_family(db: Session, auth_session: AuthSession) -> None:
    now = datetime.now(UTC)
    auth_session.revoked_at = auth_session.revoked_at or now
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.session_id == auth_session.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
