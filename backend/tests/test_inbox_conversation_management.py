from unittest.mock import Mock

import pytest

from app.db.models import Conversation, ConversationPriority, ConversationStatus
from app.services.inbox import ConversationReadOnlyError
from app.services.inbox_conversations import (
    ConversationManagementService,
    InvalidConversationTransitionError,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def conversation() -> Conversation:
    return Conversation(
        channel="internal",
        status="open",
        priority="normal",
        unread_count=0,
        human_takeover=False,
        ai_enabled=True,
    )


@pytest.fixture(autouse=True)
def no_system_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConversationManagementService, "add_system_event", Mock())


def test_open_can_be_resolved(conversation: Conversation) -> None:
    changed = ConversationManagementService.change_status(
        Mock(), conversation, ConversationStatus.RESOLVED
    )
    assert changed is True
    assert conversation.status == ConversationStatus.RESOLVED
    assert conversation.resolved_at is not None


def test_invalid_transition_is_refused(conversation: Conversation) -> None:
    with pytest.raises(InvalidConversationTransitionError):
        ConversationManagementService.change_status(Mock(), conversation, ConversationStatus.CLOSED)


def test_closed_requires_explicit_reopen(conversation: Conversation) -> None:
    conversation.status = ConversationStatus.CLOSED
    with pytest.raises(ConversationReadOnlyError):
        ConversationManagementService.change_status(Mock(), conversation, ConversationStatus.OPEN)
    assert ConversationManagementService.reopen(Mock(), conversation) is True
    assert conversation.status == ConversationStatus.OPEN
    assert conversation.closed_at is None


def test_priority_is_idempotent(conversation: Conversation) -> None:
    assert (
        ConversationManagementService.change_priority(
            Mock(), conversation, ConversationPriority.NORMAL
        )
        is False
    )


def test_archive_is_idempotent_and_read_only(conversation: Conversation) -> None:
    db = Mock()
    assert ConversationManagementService.archive(db, conversation) is True
    assert conversation.status == ConversationStatus.ARCHIVED
    assert ConversationManagementService.archive(db, conversation) is False
    with pytest.raises(ConversationReadOnlyError):
        ConversationManagementService.mark_unread(conversation)


def test_mark_unread_never_accepts_a_client_counter(conversation: Conversation) -> None:
    assert ConversationManagementService.mark_unread(conversation) is True
    assert conversation.unread_count == 1
    assert ConversationManagementService.mark_unread(conversation) is False
    assert conversation.unread_count == 1


def test_takeover_disables_ai_but_release_does_not_enable_it(
    conversation: Conversation,
) -> None:
    db = Mock()
    assert ConversationManagementService.set_takeover(db, conversation, True) is True
    assert conversation.human_takeover is True
    assert conversation.ai_enabled is False
    assert ConversationManagementService.set_takeover(db, conversation, False) is True
    assert conversation.human_takeover is False
    assert conversation.ai_enabled is False
