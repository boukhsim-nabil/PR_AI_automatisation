from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.db.models import (
    Contact,
    Conversation,
    ConversationNote,
    ConversationParticipant,
    ConversationTag,
    ConversationTagLink,
    Message,
    MessageAttachment,
    Permission,
    Role,
    RolePermission,
)
from app.db.seeds.rbac import PERMISSION_DEFINITIONS, ROLE_PERMISSION_CODES, seed_rbac

pytestmark = pytest.mark.integration

INBOX_PERMISSION_CODES = frozenset(
    {
        "inbox.read",
        "inbox.create",
        "inbox.reply",
        "inbox.assign",
        "inbox.update_status",
        "inbox.manage_priority",
        "inbox.notes.create",
        "inbox.tags.manage",
        "inbox.archive",
        "inbox.takeover",
    }
)


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID


@dataclass(frozen=True, slots=True)
class InboxMetadataResources:
    contact_id: UUID
    other_contact_id: UUID
    conversation_id: UUID
    other_conversation_id: UUID
    message_id: UUID
    other_message_id: UUID


def _set_app_context(connection: Any, company_id: UUID | None = None) -> None:
    connection.execute(text("SET LOCAL ROLE automation_app"))
    if company_id is not None:
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )


@pytest.fixture()
def inbox_metadata_resources(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> InboxMetadataResources:
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        contact_id = connection.scalar(
            insert(Contact)
            .values(
                company_id=integration_identity.company_id,
                created_by_membership_id=integration_identity.membership_id,
                last_name="Metadata Alpha",
            )
            .returning(Contact.id)
        )
        other_contact_id = connection.scalar(
            insert(Contact)
            .values(
                company_id=integration_identity.other_company_id,
                created_by_membership_id=integration_identity.other_membership_id,
                last_name="Metadata Beta",
            )
            .returning(Contact.id)
        )
        assert contact_id is not None
        assert other_contact_id is not None

        conversation_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.company_id,
                channel="internal",
                created_by_membership_id=integration_identity.membership_id,
            )
            .returning(Conversation.id)
        )
        other_conversation_id = connection.scalar(
            insert(Conversation)
            .values(
                company_id=integration_identity.other_company_id,
                channel="internal",
                created_by_membership_id=integration_identity.other_membership_id,
            )
            .returning(Conversation.id)
        )
        assert conversation_id is not None
        assert other_conversation_id is not None

        message_id = connection.scalar(
            insert(Message)
            .values(
                company_id=integration_identity.company_id,
                conversation_id=conversation_id,
                direction="internal",
                sender_type="user",
                sender_membership_id=integration_identity.membership_id,
                content_type="text",
                body_text="Alpha message",
                status="sent",
            )
            .returning(Message.id)
        )
        other_message_id = connection.scalar(
            insert(Message)
            .values(
                company_id=integration_identity.other_company_id,
                conversation_id=other_conversation_id,
                direction="internal",
                sender_type="user",
                sender_membership_id=integration_identity.other_membership_id,
                content_type="text",
                body_text="Beta message",
                status="sent",
            )
            .returning(Message.id)
        )
        assert message_id is not None
        assert other_message_id is not None

    return InboxMetadataResources(
        contact_id=contact_id,
        other_contact_id=other_contact_id,
        conversation_id=conversation_id,
        other_conversation_id=other_conversation_id,
        message_id=message_id,
        other_message_id=other_message_id,
    )


def test_participant_is_created_and_contact_data_is_normalized(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        participant_id = connection.scalar(
            insert(ConversationParticipant)
            .values(
                company_id=integration_identity.company_id,
                conversation_id=inbox_metadata_resources.conversation_id,
                participant_type="external",
                email="  Person@Example.COM ",
                phone="+212 6 12-34-56-78",
            )
            .returning(ConversationParticipant.id)
        )
        assert participant_id is not None
        normalized = connection.execute(
            select(
                ConversationParticipant.email_normalized,
                ConversationParticipant.phone_normalized,
            ).where(ConversationParticipant.id == participant_id)
        ).one()
        assert normalized.email_normalized == "person@example.com"
        assert normalized.phone_normalized == "212612345678"


def test_participant_without_usable_identity_is_rejected(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationParticipant).values(
                    company_id=integration_identity.company_id,
                    conversation_id=inbox_metadata_resources.conversation_id,
                    participant_type="external",
                )
            )


def test_duplicate_normalized_participant_is_rejected(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        connection.execute(
            insert(ConversationParticipant).values(
                company_id=integration_identity.company_id,
                conversation_id=inbox_metadata_resources.conversation_id,
                participant_type="external",
                email="duplicate@example.com",
            )
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationParticipant).values(
                    company_id=integration_identity.company_id,
                    conversation_id=inbox_metadata_resources.conversation_id,
                    participant_type="external",
                    email=" DUPLICATE@EXAMPLE.COM ",
                )
            )


@pytest.mark.parametrize(
    ("participant_type", "identity_field", "foreign_identity"),
    [
        ("contact", "contact_id", "other_contact_id"),
        ("user", "membership_id", "other_membership_id"),
    ],
)
def test_participant_rejects_cross_tenant_contact_or_membership(
    participant_type: str,
    identity_field: str,
    foreign_identity: str,
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    foreign_id = (
        getattr(inbox_metadata_resources, foreign_identity)
        if hasattr(inbox_metadata_resources, foreign_identity)
        else getattr(integration_identity, foreign_identity)
    )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationParticipant).values(
                    company_id=integration_identity.company_id,
                    conversation_id=inbox_metadata_resources.conversation_id,
                    participant_type=participant_type,
                    **{identity_field: foreign_id},
                )
            )


def test_note_is_tenant_scoped_and_separate_from_messages(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        connection.execute(
            insert(ConversationNote).values(
                id=inbox_metadata_resources.message_id,
                company_id=integration_identity.company_id,
                conversation_id=inbox_metadata_resources.conversation_id,
                author_membership_id=integration_identity.membership_id,
                body="Note strictement interne",
            )
        )
        assert (
            connection.scalar(
                select(ConversationNote.body).where(
                    ConversationNote.id == inbox_metadata_resources.message_id
                )
            )
            == "Note strictement interne"
        )
        assert (
            connection.scalar(
                select(Message.body_text).where(Message.id == inbox_metadata_resources.message_id)
            )
            == "Alpha message"
        )


def test_note_is_invisible_from_another_tenant(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        note_id = connection.scalar(
            insert(ConversationNote)
            .values(
                company_id=integration_identity.company_id,
                conversation_id=inbox_metadata_resources.conversation_id,
                author_membership_id=integration_identity.membership_id,
                body="Invisible depuis Beta",
            )
            .returning(ConversationNote.id)
        )
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        assert (
            connection.scalar(select(ConversationNote.id).where(ConversationNote.id == note_id))
            is None
        )


def test_note_rejects_author_from_another_tenant(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationNote).values(
                    company_id=integration_identity.company_id,
                    conversation_id=inbox_metadata_resources.conversation_id,
                    author_membership_id=integration_identity.other_membership_id,
                    body="Auteur invalide",
                )
            )


def test_tag_name_is_unique_after_normalization_in_one_tenant(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        connection.execute(
            insert(ConversationTag).values(
                company_id=integration_identity.company_id,
                name="  VIP  ",
            )
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationTag).values(
                    company_id=integration_identity.company_id,
                    name="vip",
                )
            )


def test_same_tag_name_is_allowed_in_two_tenants(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    for company_id in (
        integration_identity.company_id,
        integration_identity.other_company_id,
    ):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, company_id)
            normalized_name = connection.scalar(
                insert(ConversationTag)
                .values(company_id=company_id, name="Priority Customer")
                .returning(ConversationTag.normalized_name)
            )
            assert normalized_name == "priority customer"


def test_cross_tenant_tag_association_is_rejected(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        foreign_tag_id = connection.scalar(
            insert(ConversationTag)
            .values(company_id=integration_identity.other_company_id, name="Foreign")
            .returning(ConversationTag.id)
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationTagLink).values(
                    company_id=integration_identity.company_id,
                    conversation_id=inbox_metadata_resources.conversation_id,
                    tag_id=foreign_tag_id,
                    created_by_membership_id=integration_identity.membership_id,
                )
            )


def test_conversation_tag_association_is_unique(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        tag_id = connection.scalar(
            insert(ConversationTag)
            .values(company_id=integration_identity.company_id, name="Unique Link")
            .returning(ConversationTag.id)
        )
        values = {
            "company_id": integration_identity.company_id,
            "conversation_id": inbox_metadata_resources.conversation_id,
            "tag_id": tag_id,
            "created_by_membership_id": integration_identity.membership_id,
        }
        connection.execute(insert(ConversationTagLink).values(**values))
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(insert(ConversationTagLink).values(**values))


def test_attachment_metadata_is_created_for_same_tenant_message(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        attachment_id = connection.scalar(
            insert(MessageAttachment)
            .values(
                company_id=integration_identity.company_id,
                message_id=inbox_metadata_resources.message_id,
                filename="invoice.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                storage_key="tenant-a/inbox/invoice.pdf",
            )
            .returning(MessageAttachment.id)
        )
        assert attachment_id is not None
        assert (
            connection.scalar(
                select(MessageAttachment.scan_status).where(MessageAttachment.id == attachment_id)
            )
            == "pending"
        )


def test_attachment_is_invisible_from_another_tenant(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.company_id)
        attachment_id = connection.scalar(
            insert(MessageAttachment)
            .values(
                company_id=integration_identity.company_id,
                message_id=inbox_metadata_resources.message_id,
                filename="private.txt",
                mime_type="text/plain",
                size_bytes=12,
                storage_key="tenant-a/inbox/private.txt",
            )
            .returning(MessageAttachment.id)
        )
    with migrated_engine.begin() as connection:
        _set_app_context(connection, integration_identity.other_company_id)
        assert (
            connection.scalar(
                select(MessageAttachment.id).where(MessageAttachment.id == attachment_id)
            )
            is None
        )


def test_attachment_rejects_cross_tenant_message(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(MessageAttachment).values(
                    company_id=integration_identity.company_id,
                    message_id=inbox_metadata_resources.other_message_id,
                    filename="foreign.txt",
                    mime_type="text/plain",
                    size_bytes=10,
                    storage_key="tenant-a/inbox/foreign.txt",
                )
            )


@pytest.mark.parametrize("size_bytes", [-1, 0])
def test_attachment_rejects_non_positive_size(
    size_bytes: int,
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(MessageAttachment).values(
                    company_id=integration_identity.company_id,
                    message_id=inbox_metadata_resources.message_id,
                    filename="empty.txt",
                    mime_type="text/plain",
                    size_bytes=size_bytes,
                    storage_key="tenant-a/inbox/empty.txt",
                )
            )


def test_all_metadata_tables_hide_rows_without_tenant_and_reject_writes(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    tag_id: UUID
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_migrator"))
        tag_id = connection.scalar(
            insert(ConversationTag)
            .values(company_id=integration_identity.company_id, name="RLS Fixture")
            .returning(ConversationTag.id)
        )
        assert tag_id is not None

    models = (
        ConversationParticipant,
        ConversationNote,
        ConversationTag,
        ConversationTagLink,
        MessageAttachment,
    )
    with migrated_engine.begin() as connection:
        _set_app_context(connection)
        for model in models:
            assert connection.execute(select(model)).all() == []

    writes = (
        insert(ConversationParticipant).values(
            company_id=integration_identity.company_id,
            conversation_id=inbox_metadata_resources.conversation_id,
            participant_type="external",
            external_identifier="no-context",
        ),
        insert(ConversationNote).values(
            company_id=integration_identity.company_id,
            conversation_id=inbox_metadata_resources.conversation_id,
            author_membership_id=integration_identity.membership_id,
            body="No context",
        ),
        insert(ConversationTag).values(
            company_id=integration_identity.company_id,
            name="No Context",
        ),
        insert(ConversationTagLink).values(
            company_id=integration_identity.company_id,
            conversation_id=inbox_metadata_resources.conversation_id,
            tag_id=tag_id,
            created_by_membership_id=integration_identity.membership_id,
        ),
        insert(MessageAttachment).values(
            company_id=integration_identity.company_id,
            message_id=inbox_metadata_resources.message_id,
            filename="no-context.txt",
            mime_type="text/plain",
            size_bytes=1,
            storage_key="tenant-a/inbox/no-context.txt",
        ),
    )
    for statement in writes:
        with pytest.raises(DBAPIError, match="row-level security"):
            with migrated_engine.begin() as connection:
                _set_app_context(connection)
                connection.execute(statement)


def test_tenant_context_does_not_leak_for_metadata_tables(
    test_database_url: str,
    integration_identity: IntegrationIdentity,
) -> None:
    engine = create_engine(
        test_database_url,
        pool_size=1,
        max_overflow=0,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.begin() as connection:
            backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
            _set_app_context(connection, integration_identity.company_id)
            connection.execute(
                insert(ConversationTag).values(
                    company_id=integration_identity.company_id,
                    name=f"Pool {uuid4()}",
                )
            )
            assert connection.scalar(select(func.count()).select_from(ConversationTag)) == 1
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) == backend_pid
            _set_app_context(connection)
            assert connection.scalar(select(func.count()).select_from(ConversationTag)) == 0
    finally:
        engine.dispose()


def test_application_role_cannot_physically_delete_notes(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
    inbox_metadata_resources: InboxMetadataResources,
) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        with migrated_engine.begin() as connection:
            _set_app_context(connection, integration_identity.company_id)
            note_id = connection.scalar(
                insert(ConversationNote)
                .values(
                    company_id=integration_identity.company_id,
                    conversation_id=inbox_metadata_resources.conversation_id,
                    author_membership_id=integration_identity.membership_id,
                    body="Note non supprimable physiquement",
                )
                .returning(ConversationNote.id)
            )
            connection.execute(delete(ConversationNote).where(ConversationNote.id == note_id))


def test_inbox_permissions_seed_is_idempotent_and_role_scoped(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        seed_rbac(session)
        seed_rbac(session)
        session.commit()

        permissions = session.scalars(
            select(Permission).where(Permission.code.in_(INBOX_PERMISSION_CODES))
        ).all()
        assert {permission.code for permission in permissions} == INBOX_PERMISSION_CODES
        assert len(permissions) == len(INBOX_PERMISSION_CODES)
        assert INBOX_PERMISSION_CODES <= set(PERMISSION_DEFINITIONS)

        for role_code, expected_codes in ROLE_PERMISSION_CODES.items():
            role = session.scalar(select(Role).where(Role.code == role_code))
            assert role is not None
            actual_codes = set(
                session.scalars(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role.id)
                )
            )
            assert (
                actual_codes & INBOX_PERMISSION_CODES
                == set(expected_codes) & INBOX_PERMISSION_CODES
            )


def test_application_role_has_rls_and_no_bypass(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        role = connection.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'automation_app'")
        ).one()
        assert role.rolsuper is False
        assert role.rolbypassrls is False
