from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import (
    Conversation,
    Message,
    MessageContentType,
    MessageSenderType,
    MessageStatus,
)
from app.schemas.inbox import (
    InboundMessageCommand,
    MessageDraftCreate,
    MessageDraftPatch,
    MessageDraftRequest,
    MessageDraftUpdate,
    SimulatedInboundRequest,
    SystemEventCommand,
)
from app.services.inbox import ConversationService, InboxDomainError, MessageService


class SystemEventType(StrEnum):
    STATUS_CHANGE = "status_change"
    ASSIGNMENT = "assignment"
    TAKEOVER = "takeover"
    RELEASE = "release"
    CONVERSATION_REOPENED = "conversation_reopened"
    MESSAGE_SENT = "message_sent"
    MESSAGE_FAILED = "message_failed"


class MessageApiService:
    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def ensure_visible(message: Message) -> None:
        if message.discarded_at is not None:
            raise InboxDomainError("Message not found")

    @classmethod
    def ensure_draft(cls, message: Message) -> None:
        cls.ensure_visible(message)
        if message.status != MessageStatus.DRAFT:
            raise InboxDomainError("Only an active draft can be changed")

    @staticmethod
    def validate_content(message: Message) -> None:
        if message.content_type not in {MessageContentType.TEXT, MessageContentType.HTML}:
            raise InboxDomainError("Only text and html messages are supported")
        if message.body_text is None and message.body_html is None:
            raise InboxDomainError("A message requires body_text or body_html")

    @classmethod
    def create_draft(
        cls,
        db: Session,
        conversation: Conversation,
        payload: MessageDraftRequest,
        *,
        sender_membership_id: UUID,
    ) -> Message:
        command = MessageDraftCreate(
            conversation_id=conversation.id,
            content_type=payload.content_type,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
            reply_to_message_id=payload.reply_to_message_id,
        )
        return MessageService.create_draft(
            db,
            conversation,
            command,
            sender_membership_id=sender_membership_id,
        )

    @classmethod
    def update_draft(cls, message: Message, payload: MessageDraftPatch) -> None:
        cls.ensure_draft(message)
        command = MessageDraftUpdate(**payload.model_dump(exclude_unset=True))
        MessageService.update_draft(message, command)
        cls.validate_content(message)

    @classmethod
    def discard_draft(cls, message: Message) -> None:
        cls.ensure_draft(message)
        now = cls._now()
        message.discarded_at = now
        message.updated_at = now

    @classmethod
    def queue(cls, conversation: Conversation, message: Message) -> None:
        ConversationService.ensure_writable(conversation)
        cls.ensure_draft(message)
        cls.validate_content(message)
        MessageService.transition(message, MessageStatus.QUEUED)

    @classmethod
    def send(
        cls,
        db: Session,
        conversation: Conversation,
        message: Message,
    ) -> Message:
        ConversationService.ensure_writable(conversation)
        cls.ensure_visible(message)
        MessageService.transition(message, MessageStatus.SENT)
        conversation.last_message_at = message.sent_at
        db.flush()
        return cls.create_system_event(
            db,
            conversation,
            SystemEventType.MESSAGE_SENT,
            subject="Message sent",
            body="A simulated outbound message was sent.",
        )

    @staticmethod
    def create_system_event(
        db: Session,
        conversation: Conversation,
        event_type: SystemEventType,
        *,
        subject: str,
        body: str,
    ) -> Message:
        event = MessageService.create_system_event(
            db,
            conversation,
            SystemEventCommand(subject=subject, body_text=body),
        )
        event.message_metadata = {"event_type": event_type.value}
        return event

    @staticmethod
    def receive(
        db: Session,
        conversation: Conversation,
        payload: SimulatedInboundRequest,
        *,
        sender_contact_id: UUID | None,
        sender_identifier: str | None,
    ) -> Message:
        command = InboundMessageCommand(
            sender_type=(
                MessageSenderType.CONTACT
                if sender_contact_id is not None
                else MessageSenderType.EXTERNAL
            ),
            sender_contact_id=sender_contact_id,
            sender_identifier=sender_identifier,
            content_type=payload.content_type,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
            external_message_id=payload.external_message_id,
            reply_to_message_id=payload.reply_to_message_id,
        )
        return MessageService.receive(db, conversation, command)
