from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.authorization import MembershipAuthorization, require_permission
from app.db.models import AuditLog
from app.db.session import get_db
from app.schemas.audit import AuditLogItem, AuditLogPage

router = APIRouter(prefix="/audit-logs", tags=["audit"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuditReader = Annotated[
    MembershipAuthorization,
    Depends(require_permission("audit.read")),
]


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    _access: AuditReader,
    db: DatabaseSession,
    action: str | None = Query(default=None, max_length=120),
    result: str | None = Query(default=None, max_length=32),
    resource_type: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AuditLogPage:
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if result:
        filters.append(AuditLog.result == result)
    if resource_type:
        filters.append(AuditLog.resource_type == resource_type)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    logs = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return AuditLogPage(
        items=[
            AuditLogItem(
                id=log.id,
                company_id=log.company_id,
                actor_user_id=log.actor_user_id,
                actor_membership_id=log.actor_membership_id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                result=log.result,
                ip_address=log.ip_address,
                user_agent=log.user_agent,
                correlation_id=log.correlation_id,
                metadata=log.event_metadata,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
