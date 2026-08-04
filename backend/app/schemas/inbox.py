from __future__ import annotations

from datetime import datetime
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
    external_conversation_id: Identifier | None = None
    subject: ShortText | None = None
    priority: ConversationPriority = ConversationPriority.NORMAL
    assigned_membership_id: UUID | None = None
    human_takeover: bool = False


class ConversationUpdate(NonEmptyUpdate):
    subject: ShortText | None = None
    priority: ConversationPriority | None = None
    assigned_membership_id: UUID | None = None
    human_takeover: bool | None = None


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


class ConversationRead(ConversationListItem):
    external_conversation_id: str | None
    ai_enabled: bool
    first_message_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    archived_at: datetime | None


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
