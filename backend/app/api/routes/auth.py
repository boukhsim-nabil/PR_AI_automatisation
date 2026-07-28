from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.authorization import ActiveMembership
from app.api.dependencies import CurrentAuth
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.core.sessions import (
    clear_session_cookies,
    create_session,
    generate_csrf_token,
    generate_refresh_token,
    refresh_company_id,
    require_csrf,
    revoke_session_family,
    set_session_cookies,
    token_hash,
)
from app.db.models import AuthSession, Company, Membership, RefreshToken, User
from app.db.session import get_db
from app.db.tenant import set_current_company
from app.schemas.auth import (
    AuthContextResponse,
    CurrentCompanyInfo,
    CurrentMembershipInfo,
    CurrentRoleInfo,
    CurrentUserInfo,
    CurrentUserResponse,
    LoginRequest,
    TokenResponse,
)
from app.services.audit import AuditEvent, AuditService

router = APIRouter(prefix="/auth", tags=["authentication"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> TokenResponse:
    # The login endpoint is public, but its membership lookup must still be
    # constrained to the tenant explicitly requested by the caller.
    set_current_company(db, payload.company_id)
    statement = (
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .join(Company, Company.id == Membership.company_id)
        .where(
            User.email == str(payload.email).lower(),
            User.status == "active",
            Membership.company_id == payload.company_id,
            Membership.status == "active",
            Company.status.in_(("active", "onboarding")),
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
        AuditService.record(
            request.scope,
            AuditEvent(
                company_id=payload.company_id,
                action="auth.login",
                result="failure",
                metadata={"reason": "invalid_credentials_or_inactive_membership"},
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or inactive membership",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_session, refresh_token, csrf_token = create_session(
        db, user=user, membership=membership, request=request
    )
    access_token, expires_in = create_access_token(
        user_id=user.id,
        company_id=membership.company_id,
        membership_id=membership.id,
        role_id=membership.role_id,
        session_id=auth_session.id,
    )
    set_session_cookies(
        response,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
    )
    AuditService.record(
        request.scope,
        AuditEvent(
            company_id=membership.company_id,
            actor_user_id=user.id,
            actor_membership_id=membership.id,
            action="auth.login",
            result="success",
            resource_type="auth_session",
            resource_id=str(auth_session.id),
        ),
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
        session_id=auth.session_id,
    )


def _refresh_record(request: Request, db: Session) -> tuple[str, RefreshToken, AuthSession]:
    raw_token = request.cookies.get(settings.refresh_cookie_name, "")
    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh token required")
    try:
        company_id = refresh_company_id(raw_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    set_current_company(db, company_id)
    record = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash(raw_token))
        .with_for_update()
    )
    auth_session = db.get(AuthSession, record.session_id) if record else None
    if record is None or auth_session is None or auth_session.company_id != company_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return raw_token, record, auth_session


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> TokenResponse | JSONResponse:
    _raw_token, record, auth_session = _refresh_record(request, db)
    now = datetime.now(UTC)

    if record.used_at is not None or record.revoked_at is not None:
        revoke_session_family(db, auth_session)
        AuditService.record(
            request.scope,
            AuditEvent(
                company_id=auth_session.company_id,
                actor_user_id=auth_session.user_id,
                actor_membership_id=auth_session.membership_id,
                action="auth.refresh",
                result="denied",
                resource_type="auth_session",
                resource_id=str(auth_session.id),
                metadata={"reason": "token_reuse"},
            ),
        )
        rejected = JSONResponse(status_code=401, content={"detail": "Refresh token reuse detected"})
        clear_session_cookies(rejected)
        return rejected

    require_csrf(request, auth_session)
    if (
        auth_session.revoked_at is not None
        or _utc(record.expires_at) <= now
        or _utc(auth_session.expires_at) <= now
    ):
        revoke_session_family(db, auth_session)
        AuditService.record(
            request.scope,
            AuditEvent(
                company_id=auth_session.company_id,
                actor_user_id=auth_session.user_id,
                actor_membership_id=auth_session.membership_id,
                action="auth.refresh",
                result="denied",
                resource_type="auth_session",
                resource_id=str(auth_session.id),
                metadata={"reason": "expired_or_revoked"},
            ),
        )
        rejected = JSONResponse(
            status_code=401, content={"detail": "Refresh session expired or revoked"}
        )
        clear_session_cookies(rejected)
        return rejected

    membership = db.scalar(
        select(Membership).where(
            Membership.id == auth_session.membership_id,
            Membership.user_id == auth_session.user_id,
            Membership.company_id == auth_session.company_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        revoke_session_family(db, auth_session)
        AuditService.record(
            request.scope,
            AuditEvent(
                company_id=auth_session.company_id,
                actor_user_id=auth_session.user_id,
                actor_membership_id=auth_session.membership_id,
                action="auth.refresh",
                result="denied",
                resource_type="auth_session",
                resource_id=str(auth_session.id),
                metadata={"reason": "inactive_membership"},
            ),
        )
        rejected = JSONResponse(status_code=401, content={"detail": "Inactive membership"})
        clear_session_cookies(rejected)
        return rejected

    record.used_at = now
    record.revoked_at = now
    new_refresh_token = generate_refresh_token(auth_session.company_id)
    new_csrf_token = generate_csrf_token()
    replacement = RefreshToken(
        session_id=auth_session.id,
        token_hash=token_hash(new_refresh_token),
        expires_at=auth_session.expires_at,
    )
    db.add(replacement)
    db.flush()
    record.replaced_by_id = replacement.id
    auth_session.csrf_token_hash = token_hash(new_csrf_token)
    db.flush()

    access_token, expires_in = create_access_token(
        user_id=auth_session.user_id,
        company_id=auth_session.company_id,
        membership_id=auth_session.membership_id,
        role_id=membership.role_id,
        session_id=auth_session.id,
    )
    set_session_cookies(
        response,
        refresh_token=new_refresh_token,
        csrf_token=new_csrf_token,
        max_age=max(0, int((_utc(auth_session.expires_at) - now).total_seconds())),
    )
    AuditService.record(
        request.scope,
        AuditEvent(
            company_id=auth_session.company_id,
            actor_user_id=auth_session.user_id,
            actor_membership_id=auth_session.membership_id,
            action="auth.refresh",
            result="success",
            resource_type="auth_session",
            resource_id=str(auth_session.id),
        ),
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        company_id=auth_session.company_id,
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DatabaseSession) -> Response:
    try:
        _raw_token, _record, auth_session = _refresh_record(request, db)
        require_csrf(request, auth_session)
        revoke_session_family(db, auth_session)
        AuditService.record(
            request.scope,
            AuditEvent(
                company_id=auth_session.company_id,
                actor_user_id=auth_session.user_id,
                actor_membership_id=auth_session.membership_id,
                action="auth.logout",
                result="success",
                resource_type="auth_session",
                resource_id=str(auth_session.id),
            ),
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
    clear_session_cookies(response)
    response.status_code = 204
    return response


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, response: Response, db: DatabaseSession) -> Response:
    _raw_token, _record, current_session = _refresh_record(request, db)
    require_csrf(request, current_session)
    sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == current_session.user_id,
            AuthSession.company_id == current_session.company_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    for auth_session in sessions:
        revoke_session_family(db, auth_session)
    AuditService.record(
        request.scope,
        AuditEvent(
            company_id=current_session.company_id,
            actor_user_id=current_session.user_id,
            actor_membership_id=current_session.membership_id,
            action="auth.logout_all",
            result="success",
            resource_type="auth_session",
            resource_id=str(current_session.id),
            metadata={"revoked_sessions": len(sessions)},
        ),
    )
    clear_session_cookies(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=CurrentUserResponse)
def current_user(access: ActiveMembership) -> CurrentUserResponse:
    role = access.role
    return CurrentUserResponse(
        user=CurrentUserInfo(
            id=access.user.id,
            email=access.user.email,
            display_name=access.user.display_name,
        ),
        company=CurrentCompanyInfo(
            id=access.company.id,
            name=access.company.name,
        ),
        membership=CurrentMembershipInfo(
            id=access.membership.id,
            status=access.membership.status,
        ),
        role=(
            CurrentRoleInfo(id=role.id, code=role.code, name=role.name)
            if role is not None
            else None
        ),
        permissions=sorted(access.permissions),
    )
