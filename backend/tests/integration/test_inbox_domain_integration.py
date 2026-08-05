from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import pytest
from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import (
    Conversation,
    ConversationNote,
    ConversationParticipant,
    ConversationTag,
    ConversationTagLink,
    Message,
    MessageAttachment,
    MessageStatus,
)
from app.schemas.inbox import InboundMessageCommand, MessageDraftCreate
from app.services.inbox import ConversationService, InboxDomainError, MessageService

pytestmark = pytest.mark.integration


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID


@dataclass(frozen=True, slots=True)
class CompleteInboxAggregate:
    conversation_id: UUID
    message_id: UUID
    participant_id: UUID
    note_id: UUID
    tag_id: UUID
    attachment_id: UUID


def _set_context(target: Session | Connection, company_id: UUID | None = None) -> None:
    target.execute(text("SET LOCAL ROLE automation_app"))
    if company_id is not None:
        target.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )


def _create_complete_aggregate(
    connection: Connection,
    identity: IntegrationIdentity,
) -> CompleteInboxAggregate:
    conversation_id = connection.scalar(
        insert(Conversation)
        .values(
            company_id=identity.company_id,
            channel="internal",
            created_by_membership_id=identity.membership_id,
        )
        .returning(Conversation.id)
    )
    message_id = connection.scalar(
        insert(Message)
        .values(
            company_id=identity.company_id,
            conversation_id=conversation_id,
            direction="internal",
            sender_type="user",
            sender_membership_id=identity.membership_id,
            content_type="text",
            body_text="Complete aggregate",
            status="received",
        )
        .returning(Message.id)
    )
    participant_id = connection.scalar(
        insert(ConversationParticipant)
        .values(
            company_id=identity.company_id,
            conversation_id=conversation_id,
            participant_type="external",
            external_identifier="aggregate-external",
        )
        .returning(ConversationParticipant.id)
    )
    note_id = connection.scalar(
        insert(ConversationNote)
        .values(
            company_id=identity.company_id,
            conversation_id=conversation_id,
            author_membership_id=identity.membership_id,
            body="Internal aggregate note",
        )
        .returning(ConversationNote.id)
    )
    tag_id = connection.scalar(
        insert(ConversationTag)
        .values(company_id=identity.company_id, name="Aggregate")
        .returning(ConversationTag.id)
    )
    connection.execute(
        insert(ConversationTagLink).values(
            company_id=identity.company_id,
            conversation_id=conversation_id,
            tag_id=tag_id,
            created_by_membership_id=identity.membership_id,
        )
    )
    attachment_id = connection.scalar(
        insert(MessageAttachment)
        .values(
            company_id=identity.company_id,
            message_id=message_id,
            filename="aggregate.txt",
            mime_type="text/plain",
            size_bytes=42,
            storage_key="tenant/inbox/aggregate.txt",
        )
        .returning(MessageAttachment.id)
    )
    assert all(
        (
            conversation_id,
            message_id,
            participant_id,
            note_id,
            tag_id,
            attachment_id,
        )
    )
    return CompleteInboxAggregate(
        conversation_id=conversation_id,
        message_id=message_id,
        participant_id=participant_id,
        note_id=note_id,
        tag_id=tag_id,
        attachment_id=attachment_id,
    )


def test_active_same_tenant_membership_can_be_assigned(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with Session(migrated_engine) as session, session.begin():
        _set_context(session, integration_identity.company_id)
        conversation = Conversation(
            company_id=integration_identity.company_id,
            channel="internal",
            status="open",
            priority="normal",
        )
        session.add(conversation)
        session.flush()

        ConversationService.assign(session, conversation, integration_identity.membership_id)
        assert conversation.assigned_membership_id == integration_identity.membership_id

        with pytest.raises(InboxDomainError, match="active and belong"):
            ConversationService.assign(
                session,
                conversation,
                integration_identity.other_membership_id,
            )


def test_inbound_message_state_and_timestamps_are_persisted(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    first_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    second_at = first_at + timedelta(minutes=3)
    conversation_id: UUID
    with Session(migrated_engine) as session, session.begin():
        _set_context(session, integration_identity.company_id)
        conversation = Conversation(
            company_id=integration_identity.company_id,
            channel="email",
            status="resolved",
            priority="normal",
            unread_count=0,
            resolved_at=first_at - timedelta(hours=1),
        )
        session.add(conversation)
        session.flush()
        conversation_id = conversation.id
        command = InboundMessageCommand(
            sender_type="external",
            sender_identifier="mailbox@example.com",
            body_text="Inbound",
        )
        MessageService.receive(session, conversation, command, now=first_at)
        MessageService.receive(session, conversation, command, now=second_at)

    with Session(migrated_engine) as session, session.begin():
        _set_context(session, integration_identity.company_id)
        stored = session.get(Conversation, conversation_id)
        assert stored is not None
        assert stored.status == "open"
        assert stored.resolved_at is None
        assert stored.unread_count == 2
        assert stored.first_message_at == first_at
        assert stored.last_message_at == second_at
        statuses = session.scalars(
            select(Message.status)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        ).all()
        assert statuses == ["received", "received"]


def test_message_delivery_transitions_and_sent_timestamp_are_persisted(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    sent_at = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
    message_id: UUID
    with Session(migrated_engine) as session, session.begin():
        _set_context(session, integration_identity.company_id)
        conversation = Conversation(
            company_id=integration_identity.company_id,
            channel="email",
            status="open",
            priority="normal",
        )
        session.add(conversation)
        session.flush()
        message = MessageService.create_draft(
            session,
            conversation,
            MessageDraftCreate(
                conversation_id=conversation.id,
                body_text="Outbound",
            ),
            sender_membership_id=integration_identity.membership_id,
        )
        session.flush()
        message_id = message.id
        MessageService.transition(message, MessageStatus.QUEUED)
        session.flush()
        MessageService.transition(message, MessageStatus.SENT, now=sent_at)

    with Session(migrated_engine) as session, session.begin():
        _set_context(session, integration_identity.company_id)
        stored = session.get(Message, message_id)
        assert stored is not None
        assert stored.status == "sent"
        assert stored.sent_at == sent_at
        assert stored.updated_at == sent_at


def test_all_inbox_tables_reject_direct_cross_tenant_reads_and_updates(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.company_id)
        aggregate = _create_complete_aggregate(connection, integration_identity)

    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.other_company_id)
        assert (
            connection.scalar(
                select(Conversation.id).where(Conversation.id == aggregate.conversation_id)
            )
            is None
        )
        assert (
            connection.scalar(select(Message.id).where(Message.id == aggregate.message_id)) is None
        )
        assert (
            connection.scalar(
                select(ConversationParticipant.id).where(
                    ConversationParticipant.id == aggregate.participant_id
                )
            )
            is None
        )
        assert (
            connection.scalar(
                select(ConversationNote.id).where(ConversationNote.id == aggregate.note_id)
            )
            is None
        )
        assert (
            connection.scalar(
                select(ConversationTag.id).where(ConversationTag.id == aggregate.tag_id)
            )
            is None
        )
        assert (
            connection.scalar(
                select(ConversationTagLink.tag_id).where(
                    ConversationTagLink.tag_id == aggregate.tag_id
                )
            )
            is None
        )
        assert (
            connection.scalar(
                select(MessageAttachment.id).where(MessageAttachment.id == aggregate.attachment_id)
            )
            is None
        )

        updates = (
            update(Conversation)
            .where(Conversation.id == aggregate.conversation_id)
            .values(subject="Forbidden"),
            update(Message).where(Message.id == aggregate.message_id).values(status="read"),
            update(ConversationParticipant)
            .where(ConversationParticipant.id == aggregate.participant_id)
            .values(display_name="Forbidden"),
            update(ConversationNote)
            .where(ConversationNote.id == aggregate.note_id)
            .values(body="Forbidden"),
            update(ConversationTag)
            .where(ConversationTag.id == aggregate.tag_id)
            .values(description="Forbidden"),
            update(ConversationTagLink)
            .where(ConversationTagLink.tag_id == aggregate.tag_id)
            .values(created_at=datetime.now(UTC)),
            update(MessageAttachment)
            .where(MessageAttachment.id == aggregate.attachment_id)
            .values(scan_status="clean"),
        )
        for statement in updates:
            assert connection.execute(statement).rowcount == 0


def test_all_inbox_tables_are_invisible_without_tenant_context(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.company_id)
        _create_complete_aggregate(connection, integration_identity)

    with migrated_engine.begin() as connection:
        _set_context(connection)
        for model in (
            Conversation,
            Message,
            ConversationParticipant,
            ConversationNote,
            ConversationTag,
            ConversationTagLink,
            MessageAttachment,
        ):
            assert connection.execute(select(model)).all() == []


def test_received_message_is_immutable_for_direct_application_sql(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with pytest.raises(DBAPIError, match="message status is immutable"):
        with migrated_engine.begin() as connection:
            _set_context(connection, integration_identity.company_id)
            aggregate = _create_complete_aggregate(connection, integration_identity)
            connection.execute(
                update(Message)
                .where(Message.id == aggregate.message_id)
                .values(body_text="Forbidden direct rewrite")
            )


def test_persisted_message_lifecycle_allows_only_expected_changes(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    sent_at = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.company_id)
        conversation_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.company_id,
                channel="email",
                status="open",
                priority="normal",
            )
            .returning(Conversation.id)
        )
        message_id = connection.scalar(
            insert(Message)
            .values(
                company_id=integration_identity.company_id,
                conversation_id=conversation_id,
                direction="outbound",
                sender_type="user",
                sender_membership_id=integration_identity.membership_id,
                content_type="text",
                body_text="Draft v1",
                status="draft",
            )
            .returning(Message.id)
        )
        connection.execute(
            update(Message).where(Message.id == message_id).values(body_text="Draft v2")
        )
        connection.execute(update(Message).where(Message.id == message_id).values(status="queued"))
        connection.execute(
            update(Message).where(Message.id == message_id).values(status="sent", sent_at=sent_at)
        )
        connection.execute(
            update(Message).where(Message.id == message_id).values(status="delivered")
        )
        connection.execute(update(Message).where(Message.id == message_id).values(status="read"))
        stored = connection.execute(
            select(Message.status, Message.body_text, Message.sent_at).where(
                Message.id == message_id
            )
        ).one()
        assert stored == ("read", "Draft v2", sent_at)


def test_invalid_persisted_message_transition_is_rejected(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with pytest.raises(DBAPIError, match="transition is invalid"):
        with migrated_engine.begin() as connection:
            _set_context(connection, integration_identity.company_id)
            conversation_id = connection.scalar(
                insert(Conversation)
                .values(
                    company_id=integration_identity.company_id,
                    channel="email",
                    status="open",
                    priority="normal",
                )
                .returning(Conversation.id)
            )
            message_id = connection.scalar(
                insert(Message)
                .values(
                    company_id=integration_identity.company_id,
                    conversation_id=conversation_id,
                    direction="outbound",
                    sender_type="user",
                    sender_membership_id=integration_identity.membership_id,
                    content_type="text",
                    body_text="Queued",
                    status="queued",
                )
                .returning(Message.id)
            )
            connection.execute(
                update(Message).where(Message.id == message_id).values(status="read")
            )


def test_archived_and_closed_conversation_guards_are_persisted(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    archived_id: UUID
    closed_id: UUID
    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.company_id)
        archived_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.company_id,
                channel="internal",
                status="archived",
                priority="normal",
                archived_at=datetime.now(UTC),
            )
            .returning(Conversation.id)
        )
        closed_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.company_id,
                channel="internal",
                status="closed",
                priority="normal",
                closed_at=datetime.now(UTC),
            )
            .returning(Conversation.id)
        )
        assert archived_id is not None
        assert closed_id is not None

    with pytest.raises(DBAPIError, match="archived conversation is immutable"):
        with migrated_engine.begin() as connection:
            _set_context(connection, integration_identity.company_id)
            connection.execute(
                update(Conversation)
                .where(Conversation.id == archived_id)
                .values(subject="Forbidden")
            )

    with pytest.raises(DBAPIError, match="may only be reopened"):
        with migrated_engine.begin() as connection:
            _set_context(connection, integration_identity.company_id)
            connection.execute(
                update(Conversation)
                .where(Conversation.id == closed_id)
                .values(status="open", closed_at=None, subject="Combined change")
            )

    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.company_id)
        connection.execute(
            update(Conversation)
            .where(Conversation.id == closed_id)
            .values(status="open", closed_at=None)
        )
        connection.execute(
            update(Conversation).where(Conversation.id == closed_id).values(subject="Allowed")
        )
        assert (
            connection.scalar(select(Conversation.subject).where(Conversation.id == closed_id))
            == "Allowed"
        )


def test_archived_conversation_rejects_all_direct_child_insertions(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    conversation_id: UUID
    message_id: UUID
    tag_id: UUID
    with migrated_engine.begin() as connection:
        _set_context(connection, integration_identity.company_id)
        conversation_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.company_id,
                channel="internal",
                status="open",
                priority="normal",
            )
            .returning(Conversation.id)
        )
        message_id = connection.scalar(
            insert(Message)
            .values(
                company_id=integration_identity.company_id,
                conversation_id=conversation_id,
                direction="inbound",
                sender_type="external",
                content_type="text",
                body_text="Existing message",
                status="received",
            )
            .returning(Message.id)
        )
        tag_id = connection.scalar(
            insert(ConversationTag)
            .values(company_id=integration_identity.company_id, name="Archived guard")
            .returning(ConversationTag.id)
        )
        connection.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(status="archived", archived_at=datetime.now(UTC))
        )
        assert conversation_id is not None
        assert message_id is not None
        assert tag_id is not None

    insertions = (
        insert(Message).values(
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
            direction="inbound",
            sender_type="external",
            content_type="text",
            body_text="Late message",
            status="received",
        ),
        insert(ConversationParticipant).values(
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
            participant_type="external",
            external_identifier="late-participant",
        ),
        insert(ConversationNote).values(
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
            author_membership_id=integration_identity.membership_id,
            body="Late note",
        ),
        insert(ConversationTagLink).values(
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
            tag_id=tag_id,
            created_by_membership_id=integration_identity.membership_id,
        ),
        insert(MessageAttachment).values(
            company_id=integration_identity.company_id,
            message_id=message_id,
            filename="late.txt",
            mime_type="text/plain",
            size_bytes=1,
            storage_key="tenant/inbox/late.txt",
        ),
    )
    for statement in insertions:
        with pytest.raises(DBAPIError, match="closed or archived conversation"):
            with migrated_engine.begin() as connection:
                _set_context(connection, integration_identity.company_id)
                connection.execute(statement)
