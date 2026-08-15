from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, func, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    Contact,
    Conversation,
    ConversationNote,
    ConversationTag,
    ConversationTagLink,
    CrmActivity,
    CrmTask,
    Lead,
    Membership,
    Message,
    Permission,
    Role,
    RolePermission,
    User,
)

pytestmark = pytest.mark.integration


class IntegrationIdentity(Protocol):
    company_id: UUID
    other_company_id: UUID
    membership_id: UUID
    other_membership_id: UUID
    email: str
    password: str
    other_email: str
    other_password: str


def _headers(
    client: TestClient,
    *,
    email: str,
    password: str,
    company_id: UUID,
) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password, "company_id": str(company_id)},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _owner_headers(client: TestClient, identity: IntegrationIdentity) -> dict[str, str]:
    return _headers(
        client,
        email=identity.email,
        password=identity.password,
        company_id=identity.company_id,
    )


def _viewer_headers(client: TestClient, identity: IntegrationIdentity) -> dict[str, str]:
    return _headers(
        client,
        email=identity.other_email,
        password=identity.other_password,
        company_id=identity.other_company_id,
    )


def _conversation(
    engine: Engine,
    identity: IntegrationIdentity,
    *,
    other_tenant: bool = False,
    status: str = "open",
    contact_id: UUID | None = None,
    lead_id: UUID | None = None,
) -> Conversation:
    company_id = identity.other_company_id if other_tenant else identity.company_id
    membership_id = identity.other_membership_id if other_tenant else identity.membership_id
    with Session(engine, expire_on_commit=False) as session:
        item = Conversation(
            company_id=company_id,
            contact_id=contact_id,
            lead_id=lead_id,
            channel="internal",
            subject=f"Collaboration {uuid4().hex[:8]}",
            status=status,
            priority="normal",
            created_by_membership_id=membership_id,
            archived_at=datetime.now(UTC) if status == "archived" else None,
        )
        session.add(item)
        session.commit()
        return item


def _crm_resources(
    engine: Engine,
    identity: IntegrationIdentity,
) -> tuple[Contact, Lead]:
    with Session(engine, expire_on_commit=False) as session:
        contact = Contact(
            company_id=identity.company_id,
            first_name="Nadia",
            last_name="Inbox",
            email="nadia.inbox@example.com",
            email_normalized="nadia.inbox@example.com",
            phone="+212600000001",
            organization_name="Inbox Maroc",
            created_by_membership_id=identity.membership_id,
        )
        session.add(contact)
        session.flush()
        lead = Lead(
            company_id=identity.company_id,
            contact_id=contact.id,
            title="Projet Inbox",
            score=72,
            priority="high",
            next_action="Rappeler demain",
            assigned_membership_id=identity.membership_id,
            created_by_membership_id=identity.membership_id,
        )
        session.add(lead)
        session.commit()
        return contact, lead


def test_note_lifecycle_is_internal_audited_and_absent_from_messages(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    created = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/notes",
        headers=headers,
        json={"body": "Note strictement interne"},
    )
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["author_membership_id"] == str(integration_identity.membership_id)
    assert "company_id" not in note

    listed = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}/notes", headers=headers
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [note["id"]]

    updated = integration_client.patch(
        f"/v1/inbox/notes/{note['id']}",
        headers=headers,
        json={"body": "Note interne modifiée"},
    )
    assert updated.status_code == 200
    assert updated.json()["body"] == "Note interne modifiée"

    archived = integration_client.post(f"/v1/inbox/notes/{note['id']}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (
        integration_client.patch(
            f"/v1/inbox/notes/{note['id']}",
            headers=headers,
            json={"body": "Interdit"},
        ).status_code
        == 409
    )

    messages = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}/messages", headers=headers
    )
    assert messages.status_code == 200
    assert all(item["id"] != note["id"] for item in messages.json()["items"])
    with Session(migrated_engine) as session:
        actions = set(
            session.scalars(select(AuditLog.action).where(AuditLog.resource_id == note["id"]))
        )
    assert {"inbox.note.created", "inbox.note.updated", "inbox.note.archived"} <= actions


def test_notes_enforce_archived_rbac_and_tenant_isolation(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    archived = _conversation(migrated_engine, integration_identity, status="archived")
    foreign = _conversation(migrated_engine, integration_identity, other_tenant=True)
    owner = _owner_headers(integration_client, integration_identity)
    viewer = _viewer_headers(integration_client, integration_identity)
    assert (
        integration_client.post(
            f"/v1/inbox/conversations/{archived.id}/notes",
            headers=owner,
            json={"body": "Interdit"},
        ).status_code
        == 409
    )
    assert (
        integration_client.post(
            f"/v1/inbox/conversations/{foreign.id}/notes",
            headers=viewer,
            json={"body": "Viewer interdit"},
        ).status_code
        == 403
    )
    assert (
        integration_client.get(
            f"/v1/inbox/conversations/{foreign.id}/notes", headers=owner
        ).status_code
        == 404
    )


def test_tag_lifecycle_normalizes_is_idempotent_and_audited(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    created = integration_client.post(
        "/v1/inbox/tags",
        headers=headers,
        json={"name": "  Important  ", "description": "Prioritaire"},
    )
    assert created.status_code == 201, created.text
    tag = created.json()
    assert tag["name"] == "Important"
    assert tag["normalized_name"] == "important"
    duplicate = integration_client.post(
        "/v1/inbox/tags", headers=headers, json={"name": "IMPORTANT"}
    )
    assert duplicate.status_code == 409

    renamed = integration_client.patch(
        f"/v1/inbox/tags/{tag['id']}",
        headers=headers,
        json={"name": "Prioritaire"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["normalized_name"] == "prioritaire"

    first = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/tags/{tag['id']}", headers=headers
    )
    second = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/tags/{tag['id']}", headers=headers
    )
    assert first.status_code == second.status_code == 200
    with Session(migrated_engine) as session:
        link_count = session.scalar(
            select(func.count())
            .select_from(ConversationTagLink)
            .where(ConversationTagLink.conversation_id == conversation.id)
        )
    assert link_count == 1
    assert (
        integration_client.delete(
            f"/v1/inbox/conversations/{conversation.id}/tags/{tag['id']}", headers=headers
        ).status_code
        == 204
    )
    assert (
        integration_client.delete(
            f"/v1/inbox/conversations/{conversation.id}/tags/{tag['id']}", headers=headers
        ).status_code
        == 204
    )
    with Session(migrated_engine) as session:
        actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.resource_id.in_((tag["id"], str(conversation.id)))
                )
            )
        )
    assert {
        "inbox.tag.created",
        "inbox.tag.updated",
        "inbox.tag.added",
        "inbox.tag.removed",
    } <= actions


def test_tags_allow_same_name_across_tenants_and_refuse_cross_tenant_links(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    owner = _owner_headers(integration_client, integration_identity)
    conversation = _conversation(migrated_engine, integration_identity)
    foreign_conversation = _conversation(migrated_engine, integration_identity, other_tenant=True)
    with Session(migrated_engine, expire_on_commit=False) as session:
        own = ConversationTag(company_id=integration_identity.company_id, name="Shared")
        foreign = ConversationTag(company_id=integration_identity.other_company_id, name="Shared")
        session.add_all([own, foreign])
        session.flush()
        session.add(
            ConversationTagLink(
                company_id=integration_identity.other_company_id,
                conversation_id=foreign_conversation.id,
                tag_id=foreign.id,
                created_by_membership_id=integration_identity.other_membership_id,
            )
        )
        session.commit()
    assert (
        integration_client.post(
            f"/v1/inbox/conversations/{conversation.id}/tags/{foreign.id}", headers=owner
        ).status_code
        == 404
    )
    assert (
        integration_client.post(
            f"/v1/inbox/conversations/{conversation.id}/tags/{own.id}", headers=owner
        ).status_code
        == 200
    )
    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_app"))
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(integration_identity.company_id)},
        )
        result = connection.execute(
            delete(ConversationTagLink).where(
                ConversationTagLink.conversation_id == foreign_conversation.id
            )
        )
        assert result.rowcount == 0
    with Session(migrated_engine) as session:
        assert (
            session.get(
                ConversationTagLink,
                (
                    integration_identity.other_company_id,
                    foreign_conversation.id,
                    foreign.id,
                ),
            )
            is not None
        )


def test_assignees_are_minimal_active_tenant_only_and_require_assignment_permission(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    owner = _owner_headers(integration_client, integration_identity)
    viewer = _viewer_headers(integration_client, integration_identity)
    with Session(migrated_engine, expire_on_commit=False) as session:
        viewer_role = session.scalar(select(Role).where(Role.code == "viewer"))
        assert viewer_role is not None
        inactive_user = User(
            email=f"inactive-{uuid4().hex}@example.com",
            display_name="Inactive Member",
            status="active",
        )
        session.add(inactive_user)
        session.flush()
        inactive = Membership(
            company_id=integration_identity.company_id,
            user_id=inactive_user.id,
            role_id=viewer_role.id,
            status="suspended",
        )
        session.add(inactive)
        session.commit()
    response = integration_client.get("/v1/inbox/assignees", headers=owner)
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {item["membership_id"] for item in body}
    assert str(integration_identity.membership_id) in ids
    assert str(integration_identity.other_membership_id) not in ids
    assert str(inactive.id) not in ids
    assert all("email" not in item and item["status"] == "active" for item in body)
    assert integration_client.get("/v1/inbox/assignees", headers=viewer).status_code == 403


def test_crm_context_is_limited_tenant_scoped_and_summary_is_deterministic(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    contact, lead = _crm_resources(migrated_engine, integration_identity)
    conversation = _conversation(
        migrated_engine,
        integration_identity,
        contact_id=contact.id,
        lead_id=lead.id,
    )
    now = datetime.now(UTC)
    with Session(migrated_engine) as session:
        for index in range(12):
            session.add(
                CrmTask(
                    company_id=integration_identity.company_id,
                    lead_id=lead.id,
                    contact_id=contact.id,
                    title=f"Task {index}",
                    priority="high",
                    status="todo",
                    due_at=now - timedelta(days=1) if index < 2 else now + timedelta(days=index),
                    created_by_membership_id=integration_identity.membership_id,
                )
            )
            session.add(
                CrmActivity(
                    company_id=integration_identity.company_id,
                    contact_id=contact.id,
                    lead_id=lead.id,
                    actor_membership_id=integration_identity.membership_id,
                    activity_type="note",
                    subject=f"Activity {index}",
                    occurred_at=now + timedelta(seconds=index),
                )
            )
        session.add_all(
            [
                Message(
                    company_id=integration_identity.company_id,
                    conversation_id=conversation.id,
                    direction="inbound",
                    sender_type="external",
                    sender_identifier="crm-context",
                    content_type="text",
                    body_text="Inbound context",
                    status="received",
                    received_at=now,
                    created_at=now,
                ),
                ConversationNote(
                    company_id=integration_identity.company_id,
                    conversation_id=conversation.id,
                    author_membership_id=integration_identity.membership_id,
                    body="Internal context",
                ),
            ]
        )
        session.commit()
    headers = _owner_headers(integration_client, integration_identity)
    context = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}/crm-context", headers=headers
    )
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["contact"]["id"] == str(contact.id)
    assert body["lead"]["id"] == str(lead.id)
    assert len(body["tasks"]) == 10
    assert len(body["activities"]) == 10
    assert all("metadata" not in item for item in body["activities"])

    first = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}/summary", headers=headers
    )
    second = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}/summary", headers=headers
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    summary = first.json()
    assert summary["message_count"] == 1
    assert summary["note_count"] == 1
    assert summary["open_task_count"] == 12
    assert summary["overdue_task_count"] == 2
    assert summary["last_inbound_message"]["body_preview"] == "Inbound context"
    assert datetime.fromisoformat(summary["last_activity_at"]) >= now


def test_crm_context_requires_crm_read_and_foreign_resources_are_opaque(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    foreign = _conversation(migrated_engine, integration_identity, other_tenant=True)
    headers = _owner_headers(integration_client, integration_identity)
    assert (
        integration_client.get(
            f"/v1/inbox/conversations/{foreign.id}/crm-context", headers=headers
        ).status_code
        == 404
    )
    with Session(migrated_engine) as session:
        owner = session.scalar(select(Role).where(Role.code == "owner"))
        crm_read = session.scalar(select(Permission).where(Permission.code == "crm.read"))
        assert owner is not None and crm_read is not None
        owner_id = owner.id
        crm_read_id = crm_read.id
        link = session.get(RolePermission, (owner.id, crm_read.id))
        assert link is not None
        session.delete(link)
        session.commit()
    try:
        assert (
            integration_client.get(
                f"/v1/inbox/conversations/{foreign.id}/crm-context", headers=headers
            ).status_code
            == 403
        )
    finally:
        with Session(migrated_engine) as session:
            session.add(RolePermission(role_id=owner_id, permission_id=crm_read_id))
            session.commit()


def test_notes_query_count_is_constant_and_rls_hides_rows_without_context(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    with Session(migrated_engine) as session:
        session.add_all(
            [
                ConversationNote(
                    company_id=integration_identity.company_id,
                    conversation_id=conversation.id,
                    author_membership_id=integration_identity.membership_id,
                    body=f"Note {index}",
                )
                for index in range(5)
            ]
        )
        session.commit()
    headers = _owner_headers(integration_client, integration_identity)
    statements: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(migrated_engine, "before_cursor_execute", capture)
    try:
        response = integration_client.get(
            f"/v1/inbox/conversations/{conversation.id}/notes", headers=headers
        )
        assert response.status_code == 200
        assert len(response.json()) == 5
    finally:
        event.remove(migrated_engine, "before_cursor_execute", capture)
    assert len(statements) <= 7

    with migrated_engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE automation_app"))
        visible = connection.execute(select(ConversationNote.id)).all()
    assert visible == []
