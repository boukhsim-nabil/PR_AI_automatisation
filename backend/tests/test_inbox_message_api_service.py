from unittest.mock import Mock

import pytest

from app.db.models import Conversation, Message
from app.schemas.inbox import MessageDraftPatch
from app.services.inbox import InboxDomainError
from app.services.inbox_messages import MessageApiService, SystemEventType

pytestmark = pytest.mark.unit


def _conversation() -> Conversation:
    return Conversation(
        channel="internal",
        status="open",
        priority="normal",
        unread_count=0,
    )


def _draft() -> Message:
    return Message(
        direction="outbound",
        sender_type="user",
        content_type="text",
        body_text="Draft",
        status="draft",
    )


def test_discarded_draft_is_no_longer_visible() -> None:
    message = _draft()
    MessageApiService.discard_draft(message)
    assert message.discarded_at is not None
    with pytest.raises(InboxDomainError, match="not found"):
        MessageApiService.update_draft(message, MessageDraftPatch(body_text="Resurrect"))


def test_empty_draft_cannot_be_queued() -> None:
    message = _draft()
    message.body_text = None
    with pytest.raises(InboxDomainError, match="requires"):
        MessageApiService.queue(_conversation(), message)


def test_queued_message_content_cannot_be_updated() -> None:
    message = _draft()
    MessageApiService.queue(_conversation(), message)
    with pytest.raises(InboxDomainError, match="active draft"):
        MessageApiService.update_draft(message, MessageDraftPatch(body_text="Forbidden"))


def test_named_system_event_uses_controlled_event_type(monkeypatch: pytest.MonkeyPatch) -> None:
    created = Message(
        direction="internal",
        sender_type="system",
        content_type="system_event",
        body_text="Event",
        status="received",
    )
    create = Mock(return_value=created)
    monkeypatch.setattr("app.services.inbox_messages.MessageService.create_system_event", create)
    result = MessageApiService.create_system_event(
        Mock(),
        _conversation(),
        SystemEventType.MESSAGE_SENT,
        subject="Sent",
        body="Message sent",
    )
    assert result.message_metadata == {"event_type": "message_sent"}
