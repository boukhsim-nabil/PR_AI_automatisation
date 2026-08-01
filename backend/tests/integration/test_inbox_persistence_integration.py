from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from app.db.models import Contact, Conversation, Lead, Message

pytestmark = pytest.mark.integration


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID


@dataclass(frozen=True, slots=True)
class InboxResources:
    contact_id: UUID
    lead_id: UUID
    other_contact_id: UUID
    other_lead_id: UUID


def _set_app_context(connection, company_id: UUID | None = None) -> None:
    connection.execute(text("SET LOCAL ROLE automation_app"))
    if company_id is not None:
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )


@pytest.fixture()
def inbox_resources(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> InboxResources:
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        contact_id = connection.scalar(
            insert(Contact)
            .values(
                company_id=integration_identity.company_id,
                created_by_membership_id=integration_identity.membership_id,
                last_name="Inbox Alpha",
            )
            .returning(Contact.id)
        )
        other_contact_id = connection.scalar(
            insert(Contact)
            .values(
                company_id=integration_identity.other_company_id,
                created_by_membership_id=integration_identity.other_membership_id,
                last_name="Inbox Beta",
            )
            .returning(Contact.id)
        )
        assert contact_id is not None
        assert other_contact_id is not None
        lead_id = connection.scalar(
            insert(Lead)
            .values(
                company_id=integration_identity.company_id,
                contact_id=contact_id,
                title="Inbox Lead Alpha",
                created_by_membership_id=integration_identity.membership_id,
            )
            .returning(Lead.id)
        )
        other_lead_id = connection.scalar(
            insert(Lead)
            .values(
                company_id=integration_identity.other_company_id,
                contact_id=other_contact_id,
                title="Inbox Lead Beta",
                created_by_membership_id=integration_identity.other_membership_id,
            )
            .returning(Lead.id)
        )
        assert lead_id is not None
        assert other_lead_id is not None
    return InboxResources(contact_id, lead_id, other_contact_id, other_lead_id)


def _create_conversation(
    connection,
    identity: IntegrationIdentity,
    *,
    other_tenant: bool = False,
    external_id: str | None = None,
) -> UUID:
    company_id = identity.other_company_id if other_tenant else identity.company_id
    membership_id = identity.other_membership_id if other_tenant else identity.membership_id
    conversation_id = connection.scalar(
        insert(Conversation)
        .values(
            company_id=company_id,
            channel="email",
            external_conversation_id=external_id,
            created_by_membership_id=membership_id,
        )
        .returning(Conversation.id)
    )
    assert conversation_id is not None
    return conversation_id


def _create_message(
    connection,
    *,
    company_id: UUID,
    conversation_id: UUID,
    external_id: str | None = None,
    sender_membership_id: UUID | None = None,
    sender_contact_id: UUID | None = None,
    reply_to_message_id: UUID | None = None,
) -> UUID:
    message_id = connection.scalar(
        insert(Message)
        .values(
            company_id=company_id,
            conversation_id=conversation_id,
            direction="inbound",
            sender_type="user"
            if sender_membership_id
            else "contact"
            if sender_contact_id
            else "external",
            sender_membership_id=sender_membership_id,
            sender_contact_id=sender_contact_id,
            content_type="text",
            body_text="Inbox integration message",
            external_message_id=external_id,
            reply_to_message_id=reply_to_message_id,
            status="received",
        )
        .returning(Message.id)
    )
    assert message_id is not None
    return message_id


def test_conversation_creation_accepts_same_tenant_contact_and_lead(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_resources: InboxResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        conversation_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.company_id,
                contact_id=inbox_resources.contact_id,
                lead_id=inbox_resources.lead_id,
                channel="internal",
                assigned_membership_id=integration_identity.membership_id,
                created_by_membership_id=integration_identity.membership_id,
            )
            .returning(Conversation.id)
        )
        assert conversation_id is not None
        stored = connection.execute(
            select(Conversation.unread_count, Conversation.priority).where(
                Conversation.id == conversation_id
            )
        ).one()
        assert stored.unread_count == 0
        assert stored.priority == "normal"


@pytest.mark.parametrize("foreign_field", ["contact_id", "lead_id"])
def test_conversation_rejects_cross_tenant_contact_or_lead(
    foreign_field: str,
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_resources: InboxResources,
) -> None:
    foreign_id = (
        inbox_resources.other_contact_id
        if foreign_field == "contact_id"
        else inbox_resources.other_lead_id
    )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(Conversation).values(
                    company_id=integration_identity.company_id,
                    channel="internal",
                    created_by_membership_id=integration_identity.membership_id,
                    **{foreign_field: foreign_id},
                )
            )


@pytest.mark.parametrize("membership_field", ["assigned_membership_id", "created_by_membership_id"])
def test_conversation_rejects_cross_tenant_membership_reference(
    membership_field: str,
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(Conversation).values(
                    company_id=integration_identity.company_id,
                    channel="internal",
                    **{membership_field: integration_identity.other_membership_id},
                )
            )


def test_conversation_rejects_negative_unread_count(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(Conversation).values(
                    company_id=integration_identity.company_id,
                    channel="api",
                    unread_count=-1,
                )
            )


def test_external_conversation_id_is_unique_per_tenant_and_channel(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    external_id = "external-conversation-shared"
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        _create_conversation(connection, integration_identity, external_id=external_id)
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        _create_conversation(
            connection, integration_identity, other_tenant=True, external_id=external_id
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            _create_conversation(connection, integration_identity, external_id=external_id)


def test_message_creation_and_same_tenant_sender_are_accepted(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        conversation_id = _create_conversation(connection, integration_identity)
        message_id = _create_message(
            connection,
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
            sender_membership_id=integration_identity.membership_id,
        )
        stored = connection.execute(
            select(Message.body_text, Message.message_metadata).where(Message.id == message_id)
        ).one()
        assert stored.body_text == "Inbox integration message"
        assert stored[1] == {}


def test_message_is_invisible_and_unmodifiable_from_other_tenant(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        conversation_id = _create_conversation(connection, integration_identity)
        message_id = _create_message(
            connection,
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
        )
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        assert connection.scalar(select(Message.id).where(Message.id == message_id)) is None
        result = connection.execute(
            update(Message).where(Message.id == message_id).values(status="read")
        )
        assert result.rowcount == 0


@pytest.mark.parametrize("sender_field", ["sender_membership_id", "sender_contact_id"])
def test_message_rejects_sender_from_other_tenant(
    sender_field: str,
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_resources: InboxResources,
) -> None:
    foreign_sender_id = (
        integration_identity.other_membership_id
        if sender_field == "sender_membership_id"
        else inbox_resources.other_contact_id
    )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            conversation_id = _create_conversation(connection, integration_identity)
            _create_message(
                connection,
                company_id=integration_identity.company_id,
                conversation_id=conversation_id,
                **{sender_field: foreign_sender_id},
            )


def test_message_rejects_conversation_from_other_tenant(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        foreign_conversation = _create_conversation(
            connection, integration_identity, other_tenant=True
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            _create_message(
                connection,
                company_id=integration_identity.company_id,
                conversation_id=foreign_conversation,
            )


def test_reply_to_message_must_belong_to_same_conversation(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            first_conversation = _create_conversation(connection, integration_identity)
            second_conversation = _create_conversation(connection, integration_identity)
            original_message = _create_message(
                connection,
                company_id=integration_identity.company_id,
                conversation_id=first_conversation,
            )
            _create_message(
                connection,
                company_id=integration_identity.company_id,
                conversation_id=second_conversation,
                reply_to_message_id=original_message,
            )


def test_external_message_id_is_tenant_aware_and_idempotent(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    external_id = "external-message-shared"
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        conversation_id = _create_conversation(connection, integration_identity)
        _create_message(
            connection,
            company_id=integration_identity.company_id,
            conversation_id=conversation_id,
            external_id=external_id,
        )
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        other_conversation_id = _create_conversation(
            connection, integration_identity, other_tenant=True
        )
        _create_message(
            connection,
            company_id=integration_identity.other_company_id,
            conversation_id=other_conversation_id,
            external_id=external_id,
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            conversation_id = connection.scalar(
                select(Conversation.id).where(
                    Conversation.company_id == integration_identity.company_id
                )
            )
            assert conversation_id is not None
            _create_message(
                connection,
                company_id=integration_identity.company_id,
                conversation_id=conversation_id,
                external_id=external_id,
            )


def test_rls_without_tenant_context_reads_nothing_and_rejects_writes(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        _create_conversation(connection, integration_identity)
    with migrated_engine.begin() as connection:
        _set_app_context(connection)
        assert connection.execute(select(Conversation.id)).scalars().all() == []
        assert connection.execute(select(Message.id)).scalars().all() == []
    with pytest.raises(DBAPIError, match="row-level security"):
        with migrated_engine.begin() as connection:
            _set_app_context(connection)
            connection.execute(
                insert(Conversation).values(
                    company_id=integration_identity.company_id,
                    channel="internal",
                )
            )


def test_tenant_context_does_not_leak_between_pooled_transactions(
    test_database_url: str,
    integration_identity: IntegrationIdentity,
) -> None:
    single_connection_engine = create_engine(
        test_database_url,
        pool_size=1,
        max_overflow=0,
        connect_args={"connect_timeout": 5},
    )
    try:
        with single_connection_engine.begin() as connection:
            backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
            _set_app_context(connection, integration_identity.company_id)
            _create_conversation(connection, integration_identity)
            assert connection.scalar(select(Conversation.id)) is not None
        with single_connection_engine.begin() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) == backend_pid
            _set_app_context(connection)
            assert connection.execute(select(Conversation.id)).scalars().all() == []
    finally:
        single_connection_engine.dispose()


def test_application_role_cannot_physically_delete_messages(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            conversation_id = _create_conversation(connection, integration_identity)
            message_id = _create_message(
                connection,
                company_id=integration_identity.company_id,
                conversation_id=conversation_id,
            )
            connection.execute(delete(Message).where(Message.id == message_id))
