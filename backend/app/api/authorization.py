from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentAuth
from app.db.models import (
    AuthSession,
    Company,
    Membership,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.db.session import get_db
from app.services.audit import AuditEvent, AuditService

DatabaseSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class MembershipAuthorization:
    user: User
    company: Company
    membership: Membership
    role: Role | None
    permissions: frozenset[str]


def get_active_membership(
    auth: CurrentAuth,
    db: DatabaseSession,
) -> MembershipAuthorization:
    # role_id from the JWT is intentionally ignored. Authorization always uses
    # the current membership assignment stored in the database.
    if auth.session_id is not None:
        current_session = db.scalar(
            select(AuthSession).where(
                AuthSession.id == auth.session_id,
                AuthSession.user_id == auth.user_id,
                AuthSession.membership_id == auth.membership_id,
                AuthSession.company_id == auth.company_id,
                AuthSession.revoked_at.is_(None),
            )
        )
        if current_session is None or (
            current_session.expires_at.replace(tzinfo=current_session.expires_at.tzinfo or UTC)
            <= datetime.now(UTC)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Active session required",
            )

    statement = (
        select(Membership, User, Company, Role)
        .join(User, User.id == Membership.user_id)
        .join(Company, Company.id == Membership.company_id)
        .outerjoin(Role, Role.id == Membership.role_id)
        .where(
            Membership.id == auth.membership_id,
            Membership.user_id == auth.user_id,
            Membership.company_id == auth.company_id,
            Membership.status == "active",
            User.status == "active",
            Company.status == "active",
        )
    )
    row = db.execute(statement).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active membership required",
        )

    membership, user, company, role = row
    permission_codes: frozenset[str] = frozenset()
    if role is not None:
        permission_codes = frozenset(
            db.scalars(
                select(Permission.code)
                .join(
                    RolePermission,
                    RolePermission.permission_id == Permission.id,
                )
                .where(RolePermission.role_id == role.id)
            )
        )

    return MembershipAuthorization(
        user=user,
        company=company,
        membership=membership,
        role=role,
        permissions=permission_codes,
    )


ActiveMembership = Annotated[
    MembershipAuthorization,
    Depends(get_active_membership),
]


def require_permission(permission_code: str) -> Callable[..., MembershipAuthorization]:
    return require_permissions(permission_code)


def require_permissions(*permission_codes: str) -> Callable[..., MembershipAuthorization]:
    required = frozenset(permission_codes)

    def permission_dependency(
        request: Request, access: ActiveMembership
    ) -> MembershipAuthorization:
        missing = sorted(required - access.permissions)
        if missing:
            AuditService.record(
                request.scope,
                AuditEvent(
                    company_id=access.membership.company_id,
                    actor_user_id=access.user.id,
                    actor_membership_id=access.membership.id,
                    action="authorization.permission_denied",
                    result="denied",
                    resource_type="permission",
                    resource_id=",".join(missing),
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return access

    return permission_dependency
