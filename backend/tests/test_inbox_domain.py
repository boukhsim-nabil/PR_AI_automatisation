from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import (
    Conversation,
    ConversationParticipantType,
    ConversationStatus,
    ConversationTag,
    Message,
    MessageAttachment,
    MessageContentType,
    MessageDirection,
    MessageStatus,
)
from app.schemas.inbox import (
    AttachmentMetadataRead,
    ConversationCreate,
    ConversationListItem,
    ConversationRead,
    ConversationUpdate,
    InboundMessageCommand,
    MessageDraftCreate,
    MessageDraftUpdate,
    MessageRead,
    NoteCreate,
    NoteRead,
    ParticipantCreate,
    ParticipantRead,
    SystemEventCommand,
    TagCreate,
    TagRead,
)
from app.services.inbox import (
    ConversationReadOnlyError,
    ConversationService,
    DuplicateConversationTagError,
    InboxDomainError,
    InvalidMessageTransitionError,
    MessageService,
    NoteService,
    TagService,
)

pytestmark = pytest.mark.unit


class FakeSession:
    def __init__(self, scalar_result: Any = None) -> None:
        self.scalar_result = scalar_result
        self.added: list[Any] = []

    def scalar(self, _statement: Any) -> Any:
        return self.scalar_result

    def add(self, value: Any) -> None:
        self.added.append(value)


def _session(*, scalar_result: Any = None) -> Session:
    return cast(Session, FakeSession(scalar_result))


def _conversation(
    *,
    status: ConversationStatus = ConversationStatus.OPEN,
    unread_count: int = 0,
) -> Conversation:
    return Conversation(
        id=uuid4(),
        company_id=uuid4(),
        channel="internal",
        status=status,
        priority="normal",
        unread_count=unread_count,
        human_takeover=False,
        ai_enabled=True,
    )


def _outbound_draft(*, direction: MessageDirection = MessageDirection.OUTBOUND) -> Message:
    return Message(
        id=uuid4(),
        company_id=uuid4(),
        conversation_id=uuid4(),
        direction=direction,
        sender_type="user",
        content_type="text",
        body_text="Draft",
        status=MessageStatus.DRAFT,
        created_at=datetime.now(UTC),
    )


def test_archived_conversation_is_read_only() -> None:
    conversation = _conversation(status=ConversationStatus.ARCHIVED)

    with pytest.raises(ConversationReadOnlyError):
        ConversationService.update(conversation, subject="Forbidden")


def test_unread_count_can_never_be_negative() -> None:
    conversation = _conversation()

    with pytest.raises(InboxDomainError, match="cannot be negative"):
        ConversationService.set_unread_count(conversation, -1)


def test_first_and_last_message_timestamps_and_inbound_counter() -> None:
    conversation = _conversation()
    first_at = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    second_at = first_at + timedelta(minutes=5)
    command = InboundMessageCommand(
        sender_type="external",
        sender_identifier="customer@example.com",
        body_text="Hello",
    )

    MessageService.receive(_session(), conversation, command, now=first_at)
    MessageService.receive(_session(), conversation, command, now=second_at)

    assert conversation.first_message_at == first_at
    assert conversation.last_message_at == second_at
    assert conversation.unread_count == 2


def test_inbound_message_reopens_resolved_conversation() -> None:
    conversation = _conversation(status=ConversationStatus.RESOLVED)
    conversation.resolved_at = datetime.now(UTC)

    MessageService.receive(
        _session(),
        conversation,
        InboundMessageCommand(
            sender_type="external",
            sender_identifier="external-42",
            body_text="New reply",
        ),
    )

    assert conversation.status == ConversationStatus.OPEN
    assert conversation.resolved_at is None
    assert conversation.unread_count == 1


def test_draft_can_transition_to_queued() -> None:
    message = _outbound_draft()

    MessageService.transition(message, MessageStatus.QUEUED)

    assert message.status == MessageStatus.QUEUED


def test_queued_message_can_transition_to_sent() -> None:
    message = _outbound_draft()
    message.status = MessageStatus.QUEUED
    sent_at = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)

    MessageService.transition(message, MessageStatus.SENT, now=sent_at)

    assert message.status == MessageStatus.SENT
    assert message.sent_at == sent_at


def test_sent_message_cannot_be_modified() -> None:
    message = _outbound_draft()
    message.status = MessageStatus.SENT

    with pytest.raises(InboxDomainError, match="Only draft"):
        MessageService.update_draft(message, MessageDraftUpdate(body_text="Changed"))


def test_internal_message_cannot_enter_customer_delivery_lifecycle() -> None:
    message = _outbound_draft(direction=MessageDirection.INTERNAL)

    with pytest.raises(InvalidMessageTransitionError, match="customer delivery"):
        MessageService.transition(message, MessageStatus.QUEUED)


def test_system_event_requires_dedicated_internal_service() -> None:
    conversation = _conversation()
    with pytest.raises(ValidationError, match="authorized internal service"):
        MessageDraftCreate(
            conversation_id=conversation.id,
            content_type=MessageContentType.SYSTEM_EVENT,
            body_text="Forbidden public event",
        )

    event = MessageService.create_system_event(
        _session(),
        conversation,
        SystemEventCommand(body_text="Assignment changed"),
    )

    assert event.content_type == MessageContentType.SYSTEM_EVENT
    assert event.direction == MessageDirection.INTERNAL
    assert event.status == MessageStatus.RECEIVED


def test_participant_public_identity_is_strictly_validated() -> None:
    with pytest.raises(ValidationError, match="contact_id is required"):
        ParticipantCreate(participant_type=ConversationParticipantType.CONTACT)
    with pytest.raises(ValidationError, match="authorized internal service"):
        ParticipantCreate(
            participant_type=ConversationParticipantType.SYSTEM,
            external_identifier="system:router",
        )

    external = ParticipantCreate(
        participant_type=ConversationParticipantType.EXTERNAL,
        email="participant@example.com",
    )
    assert str(external.email) == "participant@example.com"


def test_notes_are_internal_objects_not_messages() -> None:
    conversation = _conversation()

    note = NoteService.create(
        _session(),
        conversation,
        author_membership_id=uuid4(),
        body="  Internal context only  ",
    )

    assert note.body == "Internal context only"
    assert not isinstance(note, Message)


def test_duplicate_tag_link_is_rejected_by_domain_service() -> None:
    conversation = _conversation()
    tag = ConversationTag(
        id=uuid4(),
        company_id=conversation.company_id,
        name="VIP",
    )

    with pytest.raises(DuplicateConversationTagError):
        TagService.link(
            _session(scalar_result=conversation.id),
            conversation,
            tag,
            created_by_membership_id=uuid4(),
        )


def test_closed_conversation_requires_explicit_reopen() -> None:
    conversation = _conversation(status=ConversationStatus.CLOSED)
    conversation.closed_at = datetime.now(UTC)

    with pytest.raises(ConversationReadOnlyError):
        ConversationService.update(conversation, subject="Blocked")

    ConversationService.reopen(conversation)
    ConversationService.update(conversation, subject="Allowed")
    assert conversation.status == ConversationStatus.OPEN
    assert conversation.closed_at is None
    assert conversation.subject == "Allowed"


def test_human_takeover_disables_future_ai_automation_flag() -> None:
    conversation = _conversation()

    ConversationService.update(conversation, human_takeover=True)

    assert conversation.human_takeover is True
    assert conversation.ai_enabled is False


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (ConversationCreate, {"company_id": str(uuid4())}),
        (NoteCreate, {"company_id": str(uuid4()), "conversation_id": str(uuid4()), "body": "x"}),
        (TagCreate, {"company_id": str(uuid4()), "name": "VIP"}),
    ],
)
def test_public_schemas_reject_company_id(schema: type[Any], payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="company_id"):
        schema.model_validate(payload)


def test_no_public_inbox_schema_declares_company_id() -> None:
    public_schemas = (
        ConversationCreate,
        ConversationUpdate,
        ConversationRead,
        ConversationListItem,
        MessageDraftCreate,
        MessageDraftUpdate,
        MessageRead,
        ParticipantCreate,
        ParticipantRead,
        NoteCreate,
        NoteRead,
        TagCreate,
        TagRead,
        AttachmentMetadataRead,
    )

    for schema in public_schemas:
        assert "company_id" not in schema.model_fields


def test_message_read_hides_internal_metadata_and_flags_untrusted_html() -> None:
    source = _outbound_draft()
    source.body_html = "<script>unsafe()</script>"
    source.error_message = "private stack trace"
    source.message_metadata = {"token": "secret"}

    result = MessageRead.model_validate(source).model_dump()

    assert result["html_requires_sanitization"] is True
    assert "error_message" not in result
    assert "metadata" not in result


def test_attachment_read_does_not_expose_internal_storage_key() -> None:
    source = MessageAttachment(
        id=uuid4(),
        company_id=uuid4(),
        message_id=uuid4(),
        filename="document.pdf",
        mime_type="application/pdf",
        size_bytes=12,
        scan_status="clean",
        storage_key="tenant/private/document.pdf",
        created_at=datetime.now(UTC),
    )
    result = AttachmentMetadataRead.model_validate(source)

    assert "storage_key" not in result.model_dump()
