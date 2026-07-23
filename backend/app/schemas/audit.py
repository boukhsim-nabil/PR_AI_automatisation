from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditLogItem(BaseModel):
    id: UUID
    company_id: UUID
    actor_user_id: UUID | None
    actor_membership_id: UUID | None
    action: str
    resource_type: str | None
    resource_id: str | None
    result: str
    ip_address: str | None
    user_agent: str | None
    correlation_id: UUID
    metadata: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogItem]
    total: int
    limit: int
    offset: int
