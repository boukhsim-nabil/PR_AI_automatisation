from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentPlatformAuth
from app.core.rate_limit import platform_login_limiter
from app.core.security import (
    create_platform_access_token,
    hash_password,
    verify_password,
)
from app.core.sessions import token_hash
from app.db.models import (
    Company,
    CompanyInvitation,
    PlatformRole,
    PlatformSession,
    PlatformUserRole,
    User,
)
from app.db.session import get_db
from app.db.tenant import set_current_invitation_token_hash
from app.schemas.platform import (
    AcceptInvitation,
    AdminSummary,
    CompanyCreate,
    CompanyPage,
    CompanyProvisioned,
    CompanyRead,
    CompanyUpdate,
    InvitationRead,
    InvitationValidation,
    InviteOwner,
    PlatformLogin,
    PlatformToken,
    SuspendCompany,
    UsageSummary,
)
from app.services.platform import (
    create_owner_invitation,
    normalize_email,
    platform_audit,
    slugify,
)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]


def _correlation_id(request: Request) -> UUID:
    try:
        return UUID(str(request.state.correlation_id))
    except (AttributeError, ValueError):
        return UUID(int=0)


def _invitation_read(item: CompanyInvitation) -> InvitationRead:
    return InvitationRead(
        id=item.id,
        company_id=item.company_id,
        email=item.email_normalized,
        status=item.status,
        expires_at=item.expires_at,
        accepted_at=item.accepted_at,
        revoked_at=item.revoked_at,
        created_at=item.created_at,
    )


def _company_read(db: Session, company: Company) -> CompanyRead:
    owner_email = db.scalar(
        select(CompanyInvitation.email_normalized)
        .where(CompanyInvitation.company_id == company.id)
        .order_by(CompanyInvitation.created_at.desc())
        .limit(1)
    )
    return CompanyRead(
        id=company.id,
        name=company.name,
        legal_name=company.legal_name,
        slug=company.slug,
        sector=company.sector,
        country=company.country,
        timezone=company.timezone,
        language=company.language,
        currency=company.currency,
        status=company.status,
        onboarding_status=company.onboarding_status,
        plan_code=company.plan_code,
        trial_ends_at=company.trial_ends_at,
        owner_email=owner_email,
        created_at=company.created_at,
        suspended_at=company.suspended_at,
        suspension_reason=company.suspension_reason,
    )


def require_platform_admin(
    context: CurrentPlatformAuth,
    db: DatabaseSession,
) -> tuple[User, PlatformSession]:
    session = db.scalar(
        select(PlatformSession).where(
            PlatformSession.id == context.session_id,
            PlatformSession.user_id == context.user_id,
            PlatformSession.revoked_at.is_(None),
            PlatformSession.expires_at > datetime.now(UTC),
        )
    )
    role_exists = db.scalar(
        select(PlatformUserRole.user_id)
        .join(PlatformRole, PlatformRole.id == PlatformUserRole.platform_role_id)
        .where(
            PlatformUserRole.user_id == context.user_id,
            PlatformRole.code == "platform_super_admin",
        )
    )
    user = db.get(User, context.user_id)
    if session is None or role_exists is None or user is None or user.status != "active":
        raise HTTPException(status_code=403, detail="Platform super administrator required")
    return user, session


PlatformAdmin = Annotated[tuple[User, PlatformSession], Depends(require_platform_admin)]


@router.post("/platform-auth/login", response_model=PlatformToken)
def platform_login(
    payload: PlatformLogin, request: Request, db: DatabaseSession
) -> PlatformToken | JSONResponse:
    email = normalize_email(str(payload.email))
    client_ip = request.client.host if request.client else "unknown"
    limiter_key = f"{client_ip}|{email}"
    retry_after = platform_login_limiter.retry_after(limiter_key)
    if retry_after is not None:
        platform_audit(
            db,
            correlation_id=_correlation_id(request),
            action="platform.auth.login",
            result="denied",
            metadata={"reason": "rate_limited"},
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many authentication attempts"},
            headers={"Retry-After": str(retry_after)},
        )
    user = db.scalar(select(User).where(User.email == email))
    authorized = None
    if user is not None:
        authorized = db.scalar(
            select(PlatformUserRole.user_id)
            .join(PlatformRole, PlatformRole.id == PlatformUserRole.platform_role_id)
            .where(
                PlatformUserRole.user_id == user.id,
                PlatformRole.code == "platform_super_admin",
            )
        )
    if (
        user is None
        or authorized is None
        or user.status != "active"
        or not verify_password(payload.password.get_secret_value(), user.password_hash)
    ):
        platform_login_limiter.record_failure(limiter_key)
        platform_audit(
            db,
            correlation_id=_correlation_id(request),
            action="platform.auth.login",
            result="failure",
            metadata={"reason": "invalid_credentials"},
        )
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid platform credentials"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    platform_login_limiter.reset(limiter_key)
    session = PlatformSession(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        user_agent=request.headers.get("user-agent", "")[:500] or None,
        ip_address=request.client.host[:45] if request.client else None,
        mfa_verified=False,
    )
    db.add(session)
    db.flush()
    token, expires_in = create_platform_access_token(
        user_id=user.id, session_id=session.id, platform_role="platform_super_admin"
    )
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.auth.login",
        result="success",
        actor_user_id=user.id,
        resource_type="platform_session",
        resource_id=str(session.id),
        metadata={"mfa_enabled": user.mfa_enabled},
    )
    return PlatformToken(access_token=token, expires_in=expires_in)


@router.get("/platform-auth/me")
def platform_me(admin: PlatformAdmin) -> dict[str, object]:
    user, session = admin
    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "platform_role": "platform_super_admin",
        "session_id": session.id,
        "mfa_enabled": user.mfa_enabled,
    }


@router.post("/platform-auth/logout", status_code=204)
def platform_logout(admin: PlatformAdmin) -> Response:
    _, session = admin
    session.revoked_at = datetime.now(UTC)
    return Response(status_code=204)


@router.get("/platform/summary", response_model=AdminSummary)
def platform_summary(_admin: PlatformAdmin, db: DatabaseSession) -> AdminSummary:
    now = datetime.now(UTC)
    soon = now + timedelta(days=7)
    return AdminSummary(
        total_companies=db.scalar(select(func.count()).select_from(Company)) or 0,
        active_companies=db.scalar(
            select(func.count()).select_from(Company).where(Company.status == "active")
        )
        or 0,
        onboarding_companies=db.scalar(
            select(func.count()).select_from(Company).where(Company.status == "onboarding")
        )
        or 0,
        suspended_companies=db.scalar(
            select(func.count()).select_from(Company).where(Company.status == "suspended")
        )
        or 0,
        pending_owner_invitations=db.scalar(
            select(func.count())
            .select_from(CompanyInvitation)
            .where(CompanyInvitation.status == "pending")
        )
        or 0,
        trials_expiring_soon=db.scalar(
            select(func.count())
            .select_from(Company)
            .where(Company.trial_ends_at.between(now, soon))
        )
        or 0,
    )


@router.post("/platform/companies", response_model=CompanyProvisioned, status_code=201)
def create_company(
    payload: CompanyCreate,
    request: Request,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> CompanyProvisioned:
    user, _ = admin
    base_slug = slugify(payload.name)
    slug = base_slug
    suffix = 1
    while db.scalar(select(Company.id).where(Company.slug == slug)):
        suffix += 1
        slug = f"{base_slug[:145]}-{suffix}"
    company = Company(
        name=payload.name,
        legal_name=payload.legal_name,
        slug=slug,
        sector=payload.sector,
        country=payload.country,
        timezone=payload.timezone,
        language=payload.language,
        currency=payload.currency,
        status="pending",
        onboarding_status="owner_invited",
        plan_code=payload.plan_code,
        trial_ends_at=(
            datetime.now(UTC) + timedelta(days=payload.trial_days)
            if payload.trial_days is not None
            else None
        ),
        created_by_platform_user_id=user.id,
        settings={"automation_enabled": False},
    )
    db.add(company)
    try:
        db.flush()
        invitation = create_owner_invitation(
            db, company=company, email=str(payload.owner_email), invited_by=user.id
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Company slug or invitation conflict") from exc
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.company.created",
        result="success",
        actor_user_id=user.id,
        company_id=company.id,
        resource_type="company",
        resource_id=str(company.id),
        metadata={"plan_code": company.plan_code},
    )
    return CompanyProvisioned(
        company=_company_read(db, company), invitation=_invitation_read(invitation)
    )


@router.get("/platform/companies", response_model=CompanyPage)
def list_companies(
    _admin: PlatformAdmin,
    db: DatabaseSession,
    search: str | None = Query(default=None, max_length=100),
    company_status: str | None = Query(default=None, alias="status"),
    plan: str | None = Query(default=None, max_length=64),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    page: int = Query(default=1, ge=1, le=100),
    page_size: int = Query(default=25, ge=1, le=100),
    sort: str = Query(default="created_at_desc", pattern="^(created_at|name)_(asc|desc)$"),
) -> CompanyPage:
    clauses = []
    if search:
        pattern = f"%{search}%"
        clauses.append(
            or_(
                Company.name.ilike(pattern),
                Company.legal_name.ilike(pattern),
                Company.slug.ilike(pattern),
            )
        )
    if company_status:
        clauses.append(Company.status == company_status)
    if plan:
        clauses.append(Company.plan_code == plan)
    if country:
        clauses.append(Company.country == country.upper())
    column = Company.name if sort.startswith("name") else Company.created_at
    ordering = column.asc() if sort.endswith("_asc") else column.desc()
    total = db.scalar(select(func.count()).select_from(Company).where(*clauses)) or 0
    items = db.scalars(
        select(Company)
        .where(*clauses)
        .order_by(ordering, Company.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CompanyPage(
        items=[_company_read(db, item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


def _company_or_404(db: Session, company_id: UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("/platform/companies/{company_id}", response_model=CompanyRead)
def get_company(company_id: UUID, _admin: PlatformAdmin, db: DatabaseSession) -> CompanyRead:
    return _company_read(db, _company_or_404(db, company_id))


@router.patch("/platform/companies/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    request: Request,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> CompanyRead:
    company = _company_or_404(db, company_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(company, key, value)
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.company.updated",
        result="success",
        actor_user_id=admin[0].id,
        company_id=company.id,
        resource_type="company",
        resource_id=str(company.id),
        metadata={"fields": sorted(values)},
    )
    return _company_read(db, company)


@router.post("/platform/companies/{company_id}/invite-owner", response_model=InvitationRead)
def invite_owner(
    company_id: UUID,
    payload: InviteOwner,
    request: Request,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> InvitationRead:
    company = _company_or_404(db, company_id)
    previous = db.scalars(
        select(CompanyInvitation).where(
            CompanyInvitation.company_id == company.id,
            CompanyInvitation.status == "pending",
        )
    ).all()
    for item in previous:
        item.status = "revoked"
        item.revoked_at = datetime.now(UTC)
    db.flush()
    invitation = create_owner_invitation(
        db, company=company, email=str(payload.owner_email), invited_by=admin[0].id
    )
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.owner_invitation.sent",
        result="success",
        actor_user_id=admin[0].id,
        company_id=company.id,
        resource_type="company_invitation",
        resource_id=str(invitation.id),
    )
    return _invitation_read(invitation)


@router.get("/platform/companies/{company_id}/invitations", response_model=list[InvitationRead])
def invitations(
    company_id: UUID, _admin: PlatformAdmin, db: DatabaseSession
) -> list[InvitationRead]:
    _company_or_404(db, company_id)
    return [
        _invitation_read(item)
        for item in db.scalars(
            select(CompanyInvitation)
            .where(CompanyInvitation.company_id == company_id)
            .order_by(CompanyInvitation.created_at.desc())
        )
    ]


@router.post("/platform/invitations/{invitation_id}/revoke", response_model=InvitationRead)
def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> InvitationRead:
    item = db.get(CompanyInvitation, invitation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if item.status == "pending":
        item.status = "revoked"
        item.revoked_at = datetime.now(UTC)
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.owner_invitation.revoked",
        result="success",
        actor_user_id=admin[0].id,
        company_id=item.company_id,
        resource_type="company_invitation",
        resource_id=str(item.id),
    )
    return _invitation_read(item)


@router.post("/platform/companies/{company_id}/suspend", response_model=CompanyRead)
def suspend_company(
    company_id: UUID,
    payload: SuspendCompany,
    request: Request,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> CompanyRead:
    company = _company_or_404(db, company_id)
    company.status = "suspended"
    company.suspended_at = datetime.now(UTC)
    company.suspension_reason = payload.reason
    db.execute(
        text("SELECT platform_revoke_company_sessions(:company_id)"),
        {"company_id": str(company.id)},
    )
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.company.suspended",
        result="success",
        actor_user_id=admin[0].id,
        company_id=company.id,
        resource_type="company",
        resource_id=str(company.id),
        metadata={"reason": payload.reason},
    )
    return _company_read(db, company)


@router.post("/platform/companies/{company_id}/reactivate", response_model=CompanyRead)
def reactivate_company(
    company_id: UUID,
    request: Request,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> CompanyRead:
    company = _company_or_404(db, company_id)
    company.status = "onboarding" if company.onboarding_status != "completed" else "active"
    company.suspended_at = None
    company.suspension_reason = None
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.company.reactivated",
        result="success",
        actor_user_id=admin[0].id,
        company_id=company.id,
        resource_type="company",
        resource_id=str(company.id),
    )
    return _company_read(db, company)


@router.get("/platform/companies/{company_id}/usage-summary", response_model=UsageSummary)
def usage_summary(company_id: UUID, _admin: PlatformAdmin, db: DatabaseSession) -> UsageSummary:
    _company_or_404(db, company_id)
    return UsageSummary(
        company_id=company_id,
        contacts=0,
        leads=0,
        tasks=0,
        sessions_active=0,
    )


@router.get("/invitations/validate", response_model=InvitationValidation)
def validate_invitation(token: str, db: DatabaseSession) -> InvitationValidation:
    hashed_token = token_hash(token)
    set_current_invitation_token_hash(db, hashed_token)
    item = db.scalar(select(CompanyInvitation).where(CompanyInvitation.token_hash == hashed_token))
    now = datetime.now(UTC)
    if item is None or item.status != "pending" or item.expires_at <= now:
        if item is not None and item.status == "pending" and item.expires_at <= now:
            item.status = "expired"
        return InvitationValidation(valid=False)
    company = db.get(Company, item.company_id)
    return InvitationValidation(
        valid=True,
        invitation_id=item.id,
        company_name=company.name if company else None,
        email=item.email_normalized,
        expires_at=item.expires_at,
        existing_user=db.scalar(select(User.id).where(User.email == item.email_normalized))
        is not None,
    )


@router.post("/invitations/accept", response_model=CompanyRead)
def accept_invitation(
    payload: AcceptInvitation, request: Request, db: DatabaseSession
) -> CompanyRead:
    hashed_token = token_hash(payload.token)
    set_current_invitation_token_hash(db, hashed_token)
    item = db.scalar(
        select(CompanyInvitation)
        .where(CompanyInvitation.token_hash == hashed_token)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if item is None or item.status != "pending" or item.expires_at <= now:
        raise HTTPException(status_code=410, detail="Invitation invalid, expired or already used")
    company = _company_or_404(db, item.company_id)
    user = db.scalar(select(User).where(User.email == item.email_normalized))
    password = payload.password.get_secret_value()
    if user is None:
        if not payload.accept_terms or not payload.first_name or not payload.last_name:
            raise HTTPException(status_code=422, detail="Profile and terms acceptance required")
        user_id = db.scalar(
            text("SELECT platform_create_invited_user(:email, :password_hash, :display_name)"),
            {
                "email": item.email_normalized,
                "password_hash": hash_password(password),
                "display_name": f"{payload.first_name} {payload.last_name}",
            },
        )
        if user_id is None:
            raise HTTPException(status_code=409, detail="Unable to create invited user")
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=500, detail="Invited user unavailable")
    elif not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Existing user authentication failed")
    accepted = db.scalar(
        text("SELECT platform_accept_owner_invitation(:invitation_id, :user_id)"),
        {"invitation_id": str(item.id), "user_id": str(user.id)},
    )
    if accepted is not True:
        raise HTTPException(status_code=410, detail="Invitation can no longer be accepted")
    db.refresh(item)
    db.refresh(company)
    platform_audit(
        db,
        correlation_id=_correlation_id(request),
        action="platform.owner_invitation.accepted",
        result="success",
        actor_user_id=user.id,
        company_id=company.id,
        resource_type="company_invitation",
        resource_id=str(item.id),
    )
    db.flush()
    return _company_read(db, company)
