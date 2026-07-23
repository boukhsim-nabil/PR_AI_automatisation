from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
OptionalName = Name | None
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=40)]
Language = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$", max_length=10),
]
Currency = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")
]


class ContactStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class LeadStatus(StrEnum):
    NEW = "new"
    TO_QUALIFY = "to_qualify"
    QUALIFIED = "qualified"
    APPOINTMENT_SCHEDULED = "appointment_scheduled"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"
    ARCHIVED = "archived"


class LeadPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LeadUrgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LeadSource(StrEnum):
    MANUAL = "manual"
    FORM = "form"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    REFERRAL = "referral"
    API = "api"


class UserActivityType(StrEnum):
    NOTE = "note"
    CALL = "call"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    MEETING = "meeting"
    TASK = "task"


class ActivityType(StrEnum):
    NOTE = "note"
    CALL = "call"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    MEETING = "meeting"
    TASK = "task"
    STATUS_CHANGE = "status_change"
    ASSIGNMENT = "assignment"
    SYSTEM = "system"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class LeadSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    SCORE = "score"
    NEXT_ACTION_AT = "next_action_at"


class ContactSortField(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    LAST_NAME = "last_name"


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NonEmptyUpdate(StrictSchema):
    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class ContactCreate(StrictSchema):
    first_name: OptionalName = None
    last_name: Name
    email: EmailStr | None = None
    phone: Phone | None = None
    job_title: ShortText | None = None
    organization_name: ShortText | None = None
    language: Language = "fr"
    status: ContactStatus = ContactStatus.ACTIVE
    consent_email: bool = False
    consent_whatsapp: bool = False


class ContactUpdate(NonEmptyUpdate):
    first_name: OptionalName = None
    last_name: Name | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    job_title: ShortText | None = None
    organization_name: ShortText | None = None
    language: Language | None = None
    status: ContactStatus | None = None
    consent_email: bool | None = None
    consent_whatsapp: bool | None = None


class ContactListItem(StrictSchema):
    id: UUID
    first_name: str | None
    last_name: str
    email: EmailStr | None
    phone: str | None
    job_title: str | None
    organization_name: str | None
    status: ContactStatus
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContactRead(ContactListItem):
    language: str
    consent_email: bool
    consent_whatsapp: bool


class ContactFilters(StrictSchema):
    search: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    status: ContactStatus | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort_by: ContactSortField = ContactSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=25, ge=1, le=100)


class ContactPage(StrictSchema):
    items: list[ContactListItem]
    total: int
    page: int
    page_size: int
    pages: int


class LeadCreateFields(StrictSchema):
    title: ShortText
    need_description: LongText | None = None
    estimated_budget: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: Currency = "MAD"
    urgency: LeadUrgency = LeadUrgency.MEDIUM
    source: LeadSource = LeadSource.MANUAL
    score: int = Field(default=0, strict=True, ge=0, le=100)
    priority: LeadPriority = LeadPriority.MEDIUM
    next_action: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    next_action_at: datetime | None = None


class LeadCreate(LeadCreateFields):
    contact_id: UUID


class LeadWithContactCreate(StrictSchema):
    contact: ContactCreate
    lead: LeadCreateFields


class LeadUpdate(NonEmptyUpdate):
    title: ShortText | None = None
    need_description: LongText | None = None
    estimated_budget: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: Currency | None = None
    urgency: LeadUrgency | None = None
    source: LeadSource | None = None
    score: int | None = Field(default=None, strict=True, ge=0, le=100)
    priority: LeadPriority | None = None
    next_action: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    next_action_at: datetime | None = None


class LeadAssign(StrictSchema):
    assigned_membership_id: UUID | None


class LeadStatusChange(StrictSchema):
    status: LeadStatus
    lost_reason: Annotated[str, StringConstraints(min_length=1, max_length=1000)] | None = None

    @model_validator(mode="after")
    def lost_requires_reason(self) -> Self:
        if self.status is LeadStatus.LOST and not self.lost_reason:
            raise ValueError("lost_reason is required when status is lost")
        if self.status is not LeadStatus.LOST and self.lost_reason is not None:
            raise ValueError("lost_reason is only accepted when status is lost")
        return self


class LeadListItem(StrictSchema):
    id: UUID
    contact_id: UUID
    title: str
    contact_first_name: str | None
    contact_last_name: str
    contact_email: EmailStr | None
    organization_name: str | None
    score: int
    priority: LeadPriority
    status: LeadStatus
    source: LeadSource
    assigned_membership_id: UUID | None
    next_action: str | None
    next_action_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadRead(LeadListItem):
    contact: ContactRead
    need_description: str | None
    estimated_budget: Decimal | None
    currency: str
    urgency: LeadUrgency
    lost_reason: str | None
    archived_at: datetime | None


class LeadWithContactRead(StrictSchema):
    contact: ContactRead
    lead: LeadRead


class LeadFilters(StrictSchema):
    search: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    status: LeadStatus | None = None
    priority: LeadPriority | None = None
    source: LeadSource | None = None
    assigned_membership_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort_by: LeadSortField = LeadSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=25, ge=1, le=100)


class LeadPage(StrictSchema):
    items: list[LeadListItem]
    total: int
    page: int
    page_size: int
    pages: int


class ActivityCreate(StrictSchema):
    activity_type: UserActivityType
    subject: ShortText
    description: LongText | None = None
    occurred_at: datetime | None = None


class ActivityRead(StrictSchema):
    id: UUID
    contact_id: UUID | None
    lead_id: UUID | None
    actor_membership_id: UUID | None
    activity_type: ActivityType
    subject: str
    description: str | None
    metadata: dict[str, object]
    occurred_at: datetime
    created_at: datetime


class ActivityPage(StrictSchema):
    items: list[ActivityRead]
    total: int
    page: int
    page_size: int
    pages: int


class TaskCreate(StrictSchema):
    lead_id: UUID | None = None
    contact_id: UUID | None = None
    title: ShortText
    description: LongText | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_membership_id: UUID | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def resource_required(self) -> Self:
        if self.lead_id is None and self.contact_id is None:
            raise ValueError("lead_id or contact_id is required")
        return self


class TaskUpdate(NonEmptyUpdate):
    title: ShortText | None = None
    description: LongText | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    assigned_membership_id: UUID | None = None
    due_at: datetime | None = None


class TaskRead(StrictSchema):
    id: UUID
    lead_id: UUID | None
    contact_id: UUID | None
    title: str
    description: str | None
    priority: TaskPriority
    status: TaskStatus
    assigned_membership_id: UUID | None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskFilters(StrictSchema):
    lead_id: UUID | None = None
    contact_id: UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assigned_membership_id: UUID | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=25, ge=1, le=100)


class TaskPage(StrictSchema):
    items: list[TaskRead]
    total: int
    page: int
    page_size: int
    pages: int


class AssigneeRead(StrictSchema):
    membership_id: UUID
    display_name: str | None
    status: str
    role: str | None


class CrmSummary(StrictSchema):
    total_leads: int
    new_leads: int
    qualified_leads: int
    won_leads: int
    overdue_tasks: int
