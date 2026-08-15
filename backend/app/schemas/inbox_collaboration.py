from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
TagDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoteCreateRequest(StrictSchema):
    body: NoteBody


class NoteUpdateRequest(StrictSchema):
    body: NoteBody


class NoteRead(StrictSchema):
    id: UUID
    conversation_id: UUID
    author_membership_id: UUID
    author_display_name: str | None
    body: str
    created_at: datetime
    updated_at: datetime | None
    archived_at: datetime | None


class TagCreateRequest(StrictSchema):
    name: TagName
    description: TagDescription | None = None


class TagUpdateRequest(StrictSchema):
    name: TagName | None = None
    description: TagDescription | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class TagRead(StrictSchema):
    id: UUID
    name: str
    normalized_name: str
    description: str | None
    created_at: datetime


class AssigneeRead(StrictSchema):
    membership_id: UUID
    display_name: str | None
    role_code: str
    status: str
    avatar_url: str | None = None


class CrmContactContext(StrictSchema):
    id: UUID
    display_name: str
    email: str | None
    phone: str | None
    organization_name: str | None
    status: str


class CrmLeadContext(StrictSchema):
    id: UUID
    title: str
    status: str
    score: int
    priority: str
    assigned_membership_id: UUID | None
    assigned_display_name: str | None
    next_action: str | None
    next_action_at: datetime | None


class CrmTaskContext(StrictSchema):
    id: UUID
    title: str
    status: str
    priority: str
    due_at: datetime | None


class CrmActivityContext(StrictSchema):
    id: UUID
    activity_type: str
    subject: str
    occurred_at: datetime


class ConversationCrmContext(StrictSchema):
    contact: CrmContactContext | None
    lead: CrmLeadContext | None
    tasks: list[CrmTaskContext]
    activities: list[CrmActivityContext]


class MessageOperationalSummary(StrictSchema):
    id: UUID
    direction: str
    content_type: str
    status: str
    body_preview: str | None
    created_at: datetime


class ConversationOperationalSummary(StrictSchema):
    conversation_id: UUID
    status: str
    priority: str
    assigned_membership_id: UUID | None
    assigned_display_name: str | None
    message_count: int = Field(ge=0)
    unread_count: int = Field(ge=0)
    last_message: MessageOperationalSummary | None
    last_inbound_message: MessageOperationalSummary | None
    last_outbound_message: MessageOperationalSummary | None
    note_count: int = Field(ge=0)
    tags: list[TagRead]
    contact: CrmContactContext | None
    lead: CrmLeadContext | None
    open_task_count: int = Field(ge=0)
    overdue_task_count: int = Field(ge=0)
    human_takeover: bool
    last_activity_at: datetime
