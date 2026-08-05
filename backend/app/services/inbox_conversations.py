from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import (
    Conversation,
    ConversationPriority,
    ConversationStatus,
)
from app.schemas.inbox import SystemEventCommand
from app.services.inbox import (
    ConversationReadOnlyError,
    ConversationService,
    InboxDomainError,
    MessageService,
)


class InvalidConversationTransitionError(InboxDomainError):
    code = "invalid_conversation_transition"


class ConversationManagementService:
    ALLOWED_TRANSITIONS = {
        ConversationStatus.OPEN: frozenset(
            {
                ConversationStatus.PENDING,
                ConversationStatus.WAITING_CUSTOMER,
                ConversationStatus.WAITING_INTERNAL,
                ConversationStatus.RESOLVED,
            }
        ),
        ConversationStatus.PENDING: frozenset(
            {ConversationStatus.OPEN, ConversationStatus.RESOLVED}
        ),
        ConversationStatus.WAITING_CUSTOMER: frozenset({ConversationStatus.OPEN}),
        ConversationStatus.WAITING_INTERNAL: frozenset({ConversationStatus.OPEN}),
        ConversationStatus.RESOLVED: frozenset(
            {ConversationStatus.OPEN, ConversationStatus.CLOSED}
        ),
        ConversationStatus.CLOSED: frozenset(),
        ConversationStatus.ARCHIVED: frozenset(),
    }

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def add_system_event(
        db: Session,
        conversation: Conversation,
        *,
        subject: str,
        body: str,
    ) -> None:
        MessageService.create_system_event(
            db,
            conversation,
            SystemEventCommand(subject=subject, body_text=body),
        )

    @classmethod
    def change_status(
        cls,
        db: Session,
        conversation: Conversation,
        target: ConversationStatus,
    ) -> bool:
        ConversationService.ensure_writable(conversation)
        current = ConversationStatus(conversation.status)
        if target == current:
            return False
        if (
            target in {ConversationStatus.CLOSED, ConversationStatus.ARCHIVED}
            and target not in cls.ALLOWED_TRANSITIONS[current]
        ):
            raise InvalidConversationTransitionError(
                f"Conversation transition {current.value} -> {target.value} is not allowed"
            )
        if target not in cls.ALLOWED_TRANSITIONS[current]:
            raise InvalidConversationTransitionError(
                f"Conversation transition {current.value} -> {target.value} is not allowed"
            )

        # This event must be persisted before a transition to CLOSED because the
        # database lifecycle trigger intentionally rejects new child rows afterwards.
        cls.add_system_event(
            db,
            conversation,
            subject="Conversation status changed",
            body=f"Status changed from {current.value} to {target.value}.",
        )
        db.flush()
        now = cls._now()
        conversation.status = target
        if target is ConversationStatus.RESOLVED:
            conversation.resolved_at = now
            conversation.closed_at = None
        elif target is ConversationStatus.CLOSED:
            conversation.closed_at = now
        else:
            conversation.resolved_at = None
            conversation.closed_at = None
        return True

    @classmethod
    def reopen(cls, db: Session, conversation: Conversation) -> bool:
        if conversation.status == ConversationStatus.ARCHIVED or conversation.archived_at:
            raise ConversationReadOnlyError("Archived conversations cannot be reopened")
        if conversation.status != ConversationStatus.CLOSED:
            return False
        previous = ConversationStatus(conversation.status)
        ConversationService.reopen(conversation)
        db.flush()
        cls.add_system_event(
            db,
            conversation,
            subject="Conversation reopened",
            body=f"Status changed from {previous.value} to open.",
        )
        return True

    @classmethod
    def archive(cls, db: Session, conversation: Conversation) -> bool:
        if conversation.status == ConversationStatus.ARCHIVED or conversation.archived_at:
            return False
        ConversationService.ensure_writable(conversation)
        cls.add_system_event(
            db,
            conversation,
            subject="Conversation archived",
            body="Conversation archived.",
        )
        db.flush()
        conversation.status = ConversationStatus.ARCHIVED
        conversation.archived_at = cls._now()
        return True

    @classmethod
    def change_priority(
        cls,
        db: Session,
        conversation: Conversation,
        priority: ConversationPriority,
    ) -> bool:
        ConversationService.ensure_writable(conversation)
        previous = ConversationPriority(conversation.priority)
        if previous is priority:
            return False
        ConversationService.update(conversation, priority=priority.value)
        cls.add_system_event(
            db,
            conversation,
            subject="Conversation priority changed",
            body=f"Priority changed from {previous.value} to {priority.value}.",
        )
        return True

    @classmethod
    def set_takeover(
        cls,
        db: Session,
        conversation: Conversation,
        enabled: bool,
    ) -> bool:
        ConversationService.ensure_writable(conversation)
        if conversation.human_takeover is enabled:
            return False
        ConversationService.update(conversation, human_takeover=enabled)
        cls.add_system_event(
            db,
            conversation,
            subject="Human takeover changed",
            body="Human takeover enabled." if enabled else "Human takeover released.",
        )
        return True

    @classmethod
    def mark_unread(cls, conversation: Conversation) -> bool:
        ConversationService.ensure_writable(conversation)
        if conversation.unread_count >= 1:
            return False
        ConversationService.set_unread_count(conversation, 1)
        return True
