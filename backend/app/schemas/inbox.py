from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

from app.db.models import (
    AttachmentScanStatus,
    ConversationChannel,
    ConversationParticipantType,
    ConversationPriority,
    ConversationStatus,
    MessageContentType,
    MessageDirection,
    MessageSenderType,
    MessageStatus,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
BodyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=40)]


class StrictInboxSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InboxReadSchema(StrictInboxSchema):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class NonEmptyUpdate(StrictInboxSchema):
    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class ConversationCreate(StrictInboxSchema):
    contact_id: UUID | None = None
    lead_id: UUID | None = None
    channel: ConversationChannel = ConversationChannel.INTERNAL
    subject: ShortText | None = None
    priority: ConversationPriority = ConversationPriority.NORMAL
    assigned_membership_id: UUID | None = None


class ConversationUpdate(NonEmptyUpdate):
    subject: ShortText | None = None


class ConversationAssign(StrictInboxSchema):
    assigned_membership_id: UUID | None


class ConversationStatusChange(StrictInboxSchema):
    status: ConversationStatus


class ConversationPriorityChange(StrictInboxSchema):
    priority: ConversationPriority


class ConversationSortField(StrEnum):
    LAST_MESSAGE_AT = "last_message_at"
    CREATED_AT = "created_at"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class ConversationFilters(StrictInboxSchema):
    search: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    channel: ConversationChannel | None = None
    status: ConversationStatus | None = None
    priority: ConversationPriority | None = None
    assigned_membership_id: UUID | None = None
    contact_id: UUID | None = None
    lead_id: UUID | None = None
    human_takeover: bool | None = None
    unread_only: bool = False
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort_by: ConversationSortField = ConversationSortField.LAST_MESSAGE_AT
    sort_direction: SortDirection = SortDirection.DESC
    cursor: Annotated[str, StringConstraints(min_length=1, max_length=1000)] | None = None
    page_size: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must be before created_to")
        return self


class ContactSummary(InboxReadSchema):
    id: UUID
    first_name: str | None
    last_name: str
    email: EmailStr | None
    phone: str | None
    organization_name: str | None


class LeadSummary(InboxReadSchema):
    id: UUID
    title: str
    status: str
    priority: str


class AssignedMemberSummary(InboxReadSchema):
    membership_id: UUID
    display_name: str | None
    email: EmailStr


class ConversationListItem(InboxReadSchema):
    id: UUID
    contact_id: UUID | None
    lead_id: UUID | None
    channel: ConversationChannel
    subject: str | None
    status: ConversationStatus
    priority: ConversationPriority
    assigned_membership_id: UUID | None
    human_takeover: bool
    unread_count: int = Field(ge=0)
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    assigned_member: AssignedMemberSummary | None = None
    contact: ContactSummary | None = None
    lead: LeadSummary | None = None


class ConversationRead(ConversationListItem):
    external_conversation_id: str | None
    ai_enabled: bool
    first_message_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    archived_at: datetime | None


class ParticipantSummary(InboxReadSchema):
    id: UUID
    participant_type: ConversationParticipantType
    display_name: str | None
    email: EmailStr | None
    phone: str | None


class MessageSummary(InboxReadSchema):
    id: UUID
    direction: MessageDirection
    sender_type: MessageSenderType
    content_type: MessageContentType
    body_preview: str | None
    status: MessageStatus
    created_at: datetime


class ConversationDetail(ConversationRead):
    participants: list[ParticipantSummary]
    tags: list[TagRead]
    message_count: int = Field(ge=0)
    last_message: MessageSummary | None
    applicable_permissions: list[str]


class ConversationPage(StrictInboxSchema):
    items: list[ConversationListItem]
    next_cursor: str | None
    has_more: bool
    page_size: int = Field(ge=1, le=100)


class MessageDraftCreate(StrictInboxSchema):
    conversation_id: UUID
    direction: MessageDirection = MessageDirection.OUTBOUND
    content_type: MessageContentType = MessageContentType.TEXT
    subject: ShortText | None = None
    body_text: BodyText | None = None
    body_html: BodyText | None = None
    reply_to_message_id: UUID | None = None

    @model_validator(mode="after")
    def validate_public_draft(self) -> Self:
        if self.direction is MessageDirection.INBOUND:
            raise ValueError("Inbound messages are created by the internal reception command")
        if self.content_type is MessageContentType.SYSTEM_EVENT:
            raise ValueError("system_event requires the authorized internal service")
        if self.content_type is MessageContentType.TEXT and self.body_text is None:
            raise ValueError("body_text is required for a text draft")
        if self.content_type is MessageContentType.HTML and self.body_html is None:
            raise ValueError("body_html is required for an HTML draft")
        return self


class MessageDraftUpdate(NonEmptyUpdate):
    subject: ShortText | None = None
    body_text: BodyText | None = None
    body_html: BodyText | None = None


class MessageRead(InboxReadSchema):
    id: UUID
    conversation_id: UUID
    direction: MessageDirection
    sender_type: MessageSenderType
    sender_membership_id: UUID | None
    sender_contact_id: UUID | None
    sender_identifier: str | None
    content_type: MessageContentType
    subject: str | None
    body_text: str | None
    body_html: str | None
    reply_to_message_id: UUID | None
    status: MessageStatus
    error_code: str | None
    sent_at: datetime | None
    received_at: datetime | None
    created_at: datetime
    updated_at: datetime | None

    @computed_field
    def html_requires_sanitization(self) -> bool:
        return self.body_html is not None


class ParticipantCreate(StrictInboxSchema):
    participant_type: ConversationParticipantType
    contact_id: UUID | None = None
    membership_id: UUID | None = None
    external_identifier: Identifier | None = None
    display_name: ShortText | None = None
    email: EmailStr | None = None
    phone: Phone | None = None

    @model_validator(mode="after")
    def validate_public_identity(self) -> Self:
        if self.participant_type in {
            ConversationParticipantType.SYSTEM,
            ConversationParticipantType.AI_AGENT,
        }:
            raise ValueError("Technical participants require an authorized internal service")
        if self.participant_type is ConversationParticipantType.CONTACT and self.contact_id is None:
            raise ValueError("contact_id is required for a contact participant")
        if self.participant_type is ConversationParticipantType.USER and self.membership_id is None:
            raise ValueError("membership_id is required for a user participant")
        if self.participant_type is ConversationParticipantType.EXTERNAL and not any(
            (self.external_identifier, self.email, self.phone)
        ):
            raise ValueError("An external participant requires an identifier, email or phone")
        return self


class ParticipantRead(InboxReadSchema):
    id: UUID
    conversation_id: UUID
    participant_type: ConversationParticipantType
    contact_id: UUID | None
    membership_id: UUID | None
    external_identifier: str | None
    display_name: str | None
    email: EmailStr | None
    phone: str | None
    created_at: datetime


class NoteCreate(StrictInboxSchema):
    conversation_id: UUID
    body: BodyText


class NoteRead(InboxReadSchema):
    id: UUID
    conversation_id: UUID
    author_membership_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime | None
    archived_at: datetime | None


class TagCreate(StrictInboxSchema):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: ShortText | None = None


class TagRead(InboxReadSchema):
    id: UUID
    name: str
    description: str | None
    created_at: datetime


class AttachmentMetadataRead(InboxReadSchema):
    id: UUID
    message_id: UUID
    filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    scan_status: AttachmentScanStatus
    created_at: datetime


class ConversationReopenCommand(StrictInboxSchema):
    target_status: ConversationStatus = ConversationStatus.OPEN

    @model_validator(mode="after")
    def target_must_be_writable(self) -> Self:
        if self.target_status in {ConversationStatus.CLOSED, ConversationStatus.ARCHIVED}:
            raise ValueError("A reopened conversation must use a writable status")
        return self


class MessageTransitionCommand(StrictInboxSchema):
    target_status: MessageStatus


class InboundMessageCommand(StrictInboxSchema):
    sender_type: MessageSenderType
    sender_contact_id: UUID | None = None
    sender_identifier: Identifier | None = None
    content_type: MessageContentType = MessageContentType.TEXT
    subject: ShortText | None = None
    body_text: BodyText | None = None
    body_html: BodyText | None = None
    external_message_id: Identifier | None = None
    reply_to_message_id: UUID | None = None
    received_at: datetime | None = None

    @model_validator(mode="after")
    def validate_inbound_message(self) -> Self:
        if self.sender_type not in {MessageSenderType.CONTACT, MessageSenderType.EXTERNAL}:
            raise ValueError("Inbound sender_type must be contact or external")
        if self.content_type is MessageContentType.SYSTEM_EVENT:
            raise ValueError("system_event is not an inbound customer message")
        if self.sender_type is MessageSenderType.CONTACT and self.sender_contact_id is None:
            raise ValueError("sender_contact_id is required for a contact sender")
        if self.sender_type is MessageSenderType.EXTERNAL and self.sender_identifier is None:
            raise ValueError("sender_identifier is required for an external sender")
        return self


class SystemEventCommand(StrictInboxSchema):
    body_text: BodyText
    subject: ShortText | None = None


class MessageDraftRequest(StrictInboxSchema):
    content_type: MessageContentType = MessageContentType.TEXT
    subject: ShortText | None = None
    body_text: BodyText | None = None
    body_html: BodyText | None = None
    reply_to_message_id: UUID | None = None

    @model_validator(mode="after")
    def validate_mvp_content(self) -> Self:
        if self.content_type not in {MessageContentType.TEXT, MessageContentType.HTML}:
            raise ValueError("Only text and html drafts are supported")
        if self.body_text is None and self.body_html is None:
            raise ValueError("A draft requires body_text or body_html")
        return self


class MessageDraftPatch(NonEmptyUpdate):
    subject: ShortText | None = None
    body_text: BodyText | None = None
    body_html: BodyText | None = None


class SimulatedInboundRequest(StrictInboxSchema):
    conversation_id: UUID
    sender_contact_id: UUID | None = None
    sender_identifier: Identifier | None = None
    content_type: MessageContentType = MessageContentType.TEXT
    subject: ShortText | None = None
    body_text: BodyText | None = None
    body_html: BodyText | None = None
    external_message_id: Identifier | None = None
    reply_to_message_id: UUID | None = None

    @model_validator(mode="after")
    def validate_simulation(self) -> Self:
        if self.content_type not in {MessageContentType.TEXT, MessageContentType.HTML}:
            raise ValueError("Only text and html inbound simulations are supported")
        if self.body_text is None and self.body_html is None:
            raise ValueError("An inbound message requires body_text or body_html")
        return self


class MessageSenderSummary(StrictInboxSchema):
    sender_type: MessageSenderType
    membership_id: UUID | None = None
    contact_id: UUID | None = None
    display_name: str | None = None
    identifier: str | None = None


class ReplyMessageSummary(StrictInboxSchema):
    id: UUID
    direction: MessageDirection
    content_type: MessageContentType
    body_preview: str | None
    created_at: datetime


class MessageAttachmentSummary(StrictInboxSchema):
    id: UUID
    filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    scan_status: AttachmentScanStatus
    created_at: datetime


class MessageApiRead(StrictInboxSchema):
    id: UUID
    conversation_id: UUID
    direction: MessageDirection
    sender: MessageSenderSummary
    content_type: MessageContentType
    is_system_event: bool
    subject: str | None
    body_text: str | None
    body_html: str | None
    html_requires_sanitization: bool
    status: MessageStatus
    sent_at: datetime | None
    received_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    reply_to_message: ReplyMessageSummary | None
    attachments: list[MessageAttachmentSummary]


class MessagePage(StrictInboxSchema):
    items: list[MessageApiRead]
    next_cursor: str | None
    has_more: bool
    page_size: int = Field(ge=1, le=100)
