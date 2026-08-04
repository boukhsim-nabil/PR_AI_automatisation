from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Conversation,
    ConversationNote,
    ConversationParticipant,
    ConversationParticipantType,
    ConversationStatus,
    ConversationTag,
    ConversationTagLink,
    Membership,
    Message,
    MessageContentType,
    MessageDirection,
    MessageSenderType,
    MessageStatus,
)
from app.schemas.inbox import (
    InboundMessageCommand,
    MessageDraftCreate,
    MessageDraftUpdate,
    ParticipantCreate,
    SystemEventCommand,
)


class InboxDomainError(ValueError):
    """Base error for deterministic Inbox business-rule violations."""

    code = "inbox_rule_violation"


class ConversationReadOnlyError(InboxDomainError):
    code = "conversation_read_only"


class InvalidMessageTransitionError(InboxDomainError):
    code = "invalid_message_transition"


class InvalidParticipantError(InboxDomainError):
    code = "invalid_participant"


class DuplicateConversationTagError(InboxDomainError):
    code = "duplicate_conversation_tag"


_UNSET = object()


class ConversationService:
    @staticmethod
    def ensure_writable(conversation: Conversation) -> None:
        if conversation.status == ConversationStatus.ARCHIVED or conversation.archived_at:
            raise ConversationReadOnlyError("Archived conversations are read-only")
        if conversation.status == ConversationStatus.CLOSED:
            raise ConversationReadOnlyError(
                "Closed conversations require an explicit reopen before modification"
            )

    @classmethod
    def update(
        cls,
        conversation: Conversation,
        *,
        subject: str | None | object = _UNSET,
        priority: str | object = _UNSET,
        human_takeover: bool | object = _UNSET,
    ) -> Conversation:
        cls.ensure_writable(conversation)
        if subject is not _UNSET:
            if subject is not None and not isinstance(subject, str):
                raise TypeError("subject must be a string or None")
            conversation.subject = subject
        if priority is not _UNSET:
            if not isinstance(priority, str):
                raise TypeError("priority must be a string")
            conversation.priority = str(priority)
        if human_takeover is not _UNSET:
            if not isinstance(human_takeover, bool):
                raise TypeError("human_takeover must be a boolean")
            conversation.human_takeover = human_takeover
            if conversation.human_takeover:
                conversation.ai_enabled = False
        return conversation

    @classmethod
    def set_unread_count(cls, conversation: Conversation, value: int) -> None:
        cls.ensure_writable(conversation)
        if value < 0:
            raise InboxDomainError("unread_count cannot be negative")
        conversation.unread_count = value

    @classmethod
    def mark_read(cls, conversation: Conversation) -> None:
        cls.set_unread_count(conversation, 0)

    @staticmethod
    def reopen(
        conversation: Conversation,
        target_status: ConversationStatus = ConversationStatus.OPEN,
    ) -> None:
        if conversation.status == ConversationStatus.ARCHIVED or conversation.archived_at:
            raise ConversationReadOnlyError("Archived conversations cannot be reopened implicitly")
        if target_status in {ConversationStatus.CLOSED, ConversationStatus.ARCHIVED}:
            raise InboxDomainError("Reopen target must be a writable conversation status")
        conversation.status = target_status
        conversation.closed_at = None
        conversation.resolved_at = None

    @classmethod
    def assign(
        cls,
        db: Session,
        conversation: Conversation,
        membership_id: UUID | None,
    ) -> None:
        cls.ensure_writable(conversation)
        if membership_id is None:
            conversation.assigned_membership_id = None
            return
        membership = db.scalar(
            select(Membership.id).where(
                Membership.id == membership_id,
                Membership.company_id == conversation.company_id,
                Membership.status == "active",
            )
        )
        if membership is None:
            raise InboxDomainError(
                "Assigned membership must be active and belong to the conversation tenant"
            )
        conversation.assigned_membership_id = membership_id


class MessageService:
    ALLOWED_TRANSITIONS = {
        MessageStatus.DRAFT: frozenset({MessageStatus.QUEUED, MessageStatus.FAILED}),
        MessageStatus.QUEUED: frozenset({MessageStatus.SENT, MessageStatus.FAILED}),
        MessageStatus.SENT: frozenset({MessageStatus.DELIVERED}),
        MessageStatus.DELIVERED: frozenset({MessageStatus.READ}),
        MessageStatus.READ: frozenset(),
        MessageStatus.RECEIVED: frozenset(),
        MessageStatus.FAILED: frozenset(),
    }

    @staticmethod
    def _now(value: datetime | None = None) -> datetime:
        return value or datetime.now(UTC)

    @staticmethod
    def _validate_reply(
        db: Session,
        conversation: Conversation,
        reply_to_message_id: UUID | None,
    ) -> None:
        if reply_to_message_id is None:
            return
        reply = db.scalar(
            select(Message.id).where(
                Message.id == reply_to_message_id,
                Message.company_id == conversation.company_id,
                Message.conversation_id == conversation.id,
            )
        )
        if reply is None:
            raise InboxDomainError("reply_to_message must belong to the same conversation")

    @classmethod
    def _record_message_on_conversation(
        cls,
        conversation: Conversation,
        *,
        occurred_at: datetime,
        inbound: bool,
    ) -> None:
        ConversationService.ensure_writable(conversation)
        if inbound and conversation.status == ConversationStatus.RESOLVED:
            ConversationService.reopen(conversation)
        if conversation.first_message_at is None:
            conversation.first_message_at = occurred_at
        conversation.last_message_at = occurred_at
        if inbound:
            ConversationService.set_unread_count(conversation, conversation.unread_count + 1)

    @classmethod
    def create_draft(
        cls,
        db: Session,
        conversation: Conversation,
        command: MessageDraftCreate,
        *,
        sender_membership_id: UUID,
        now: datetime | None = None,
    ) -> Message:
        if command.conversation_id != conversation.id:
            raise InboxDomainError("Draft command does not target the loaded conversation")
        if command.content_type is MessageContentType.SYSTEM_EVENT:
            raise InboxDomainError("system_event requires the authorized internal service")
        if command.direction is MessageDirection.INBOUND:
            raise InboxDomainError("Inbound messages must use the reception command")
        cls._validate_reply(db, conversation, command.reply_to_message_id)
        occurred_at = cls._now(now)
        cls._record_message_on_conversation(conversation, occurred_at=occurred_at, inbound=False)
        message = Message(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            direction=command.direction,
            sender_type=MessageSenderType.USER,
            sender_membership_id=sender_membership_id,
            content_type=command.content_type,
            subject=command.subject,
            body_text=command.body_text,
            body_html=command.body_html,
            reply_to_message_id=command.reply_to_message_id,
            status=MessageStatus.DRAFT,
            created_at=occurred_at,
        )
        db.add(message)
        return message

    @staticmethod
    def update_draft(message: Message, command: MessageDraftUpdate) -> None:
        if message.status != MessageStatus.DRAFT:
            raise InboxDomainError("Only draft messages can be modified")
        for field in command.model_fields_set:
            setattr(message, field, getattr(command, field))

    @classmethod
    def transition(
        cls,
        message: Message,
        target_status: MessageStatus,
        *,
        now: datetime | None = None,
    ) -> None:
        current = MessageStatus(message.status)
        if target_status not in cls.ALLOWED_TRANSITIONS[current]:
            raise InvalidMessageTransitionError(
                f"Message transition {current.value} -> {target_status.value} is not allowed"
            )
        if message.direction == MessageDirection.INTERNAL and target_status in {
            MessageStatus.QUEUED,
            MessageStatus.SENT,
            MessageStatus.DELIVERED,
            MessageStatus.READ,
        }:
            raise InvalidMessageTransitionError(
                "Internal messages cannot enter the customer delivery lifecycle"
            )
        timestamp = cls._now(now)
        message.status = target_status
        message.updated_at = timestamp
        if target_status is MessageStatus.SENT:
            message.sent_at = timestamp

    @classmethod
    def receive(
        cls,
        db: Session,
        conversation: Conversation,
        command: InboundMessageCommand,
        *,
        now: datetime | None = None,
    ) -> Message:
        cls._validate_reply(db, conversation, command.reply_to_message_id)
        occurred_at = cls._now(command.received_at or now)
        cls._record_message_on_conversation(conversation, occurred_at=occurred_at, inbound=True)
        message = Message(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND,
            sender_type=command.sender_type,
            sender_contact_id=command.sender_contact_id,
            sender_identifier=command.sender_identifier,
            content_type=command.content_type,
            subject=command.subject,
            body_text=command.body_text,
            body_html=command.body_html,
            external_message_id=command.external_message_id,
            reply_to_message_id=command.reply_to_message_id,
            status=MessageStatus.RECEIVED,
            received_at=occurred_at,
            created_at=occurred_at,
        )
        db.add(message)
        return message

    @classmethod
    def create_system_event(
        cls,
        db: Session,
        conversation: Conversation,
        command: SystemEventCommand,
        *,
        now: datetime | None = None,
    ) -> Message:
        occurred_at = cls._now(now)
        cls._record_message_on_conversation(conversation, occurred_at=occurred_at, inbound=False)
        message = Message(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            direction=MessageDirection.INTERNAL,
            sender_type=MessageSenderType.SYSTEM,
            content_type=MessageContentType.SYSTEM_EVENT,
            subject=command.subject,
            body_text=command.body_text,
            status=MessageStatus.RECEIVED,
            created_at=occurred_at,
        )
        db.add(message)
        return message


class ParticipantService:
    @staticmethod
    def create(
        db: Session,
        conversation: Conversation,
        command: ParticipantCreate,
    ) -> ConversationParticipant:
        ConversationService.ensure_writable(conversation)
        participant = ConversationParticipant(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            participant_type=command.participant_type,
            contact_id=command.contact_id,
            membership_id=command.membership_id,
            external_identifier=command.external_identifier,
            display_name=command.display_name,
            email=str(command.email) if command.email else None,
            phone=command.phone,
        )
        db.add(participant)
        return participant

    @staticmethod
    def create_technical(
        db: Session,
        conversation: Conversation,
        *,
        participant_type: ConversationParticipantType,
        external_identifier: str,
        display_name: str | None = None,
    ) -> ConversationParticipant:
        ConversationService.ensure_writable(conversation)
        if participant_type not in {
            ConversationParticipantType.SYSTEM,
            ConversationParticipantType.AI_AGENT,
        }:
            raise InvalidParticipantError("Technical participant type must be system or ai_agent")
        if not external_identifier.strip():
            raise InvalidParticipantError("Technical participant requires an identifier")
        participant = ConversationParticipant(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            participant_type=participant_type,
            external_identifier=external_identifier.strip(),
            display_name=display_name,
        )
        db.add(participant)
        return participant


class NoteService:
    @staticmethod
    def create(
        db: Session,
        conversation: Conversation,
        *,
        author_membership_id: UUID,
        body: str,
    ) -> ConversationNote:
        ConversationService.ensure_writable(conversation)
        if not body.strip():
            raise InboxDomainError("Internal note body cannot be empty")
        note = ConversationNote(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            author_membership_id=author_membership_id,
            body=body.strip(),
        )
        db.add(note)
        return note


class TagService:
    @staticmethod
    def link(
        db: Session,
        conversation: Conversation,
        tag: ConversationTag,
        *,
        created_by_membership_id: UUID,
    ) -> ConversationTagLink:
        ConversationService.ensure_writable(conversation)
        if tag.company_id != conversation.company_id:
            raise InboxDomainError("Tag must belong to the conversation tenant")
        existing = db.scalar(
            select(ConversationTagLink.conversation_id).where(
                ConversationTagLink.company_id == conversation.company_id,
                ConversationTagLink.conversation_id == conversation.id,
                ConversationTagLink.tag_id == tag.id,
            )
        )
        if existing is not None:
            raise DuplicateConversationTagError("Tag is already linked to the conversation")
        link = ConversationTagLink(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            tag_id=tag.id,
            created_by_membership_id=created_by_membership_id,
        )
        db.add(link)
        return link
