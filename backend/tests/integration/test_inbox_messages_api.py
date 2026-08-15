from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import app.api.routes.inbox_messages as message_routes
from app.db.models import (
    AuditLog,
    Contact,
    Conversation,
    ConversationNote,
    Message,
    MessageAttachment,
    Permission,
    Role,
    RolePermission,
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
    unread_count: int = 0,
    contact_id: UUID | None = None,
) -> Conversation:
    company_id = identity.other_company_id if other_tenant else identity.company_id
    membership_id = identity.other_membership_id if other_tenant else identity.membership_id
    with Session(engine, expire_on_commit=False) as session:
        conversation = Conversation(
            company_id=company_id,
            contact_id=contact_id,
            channel="internal",
            status=status,
            unread_count=unread_count,
            priority="normal",
            created_by_membership_id=membership_id,
            resolved_at=datetime.now(UTC) if status == "resolved" else None,
            archived_at=datetime.now(UTC) if status == "archived" else None,
        )
        session.add(conversation)
        session.commit()
        return conversation


def _contact(engine: Engine, identity: IntegrationIdentity) -> Contact:
    with Session(engine, expire_on_commit=False) as session:
        suffix = uuid4().hex
        contact = Contact(
            company_id=identity.company_id,
            first_name="Inbound",
            last_name="Sender",
            email=f"inbound-{suffix}@example.com",
            email_normalized=f"inbound-{suffix}@example.com",
            created_by_membership_id=identity.membership_id,
        )
        session.add(contact)
        session.commit()
        return contact


def _draft(
    client: TestClient,
    headers: dict[str, str],
    conversation_id: UUID,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {"content_type": "text", "body_text": "Draft body"}
    payload.update(overrides)
    response = client.post(
        f"/v1/inbox/conversations/{conversation_id}/drafts",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _direct_message(
    engine: Engine,
    identity: IntegrationIdentity,
    conversation_id: UUID,
    *,
    content_type: str = "text",
    status: str = "received",
    body: str = "Message",
    sender_type: str = "external",
    direction: str = "inbound",
    error_message: str | None = None,
) -> Message:
    with Session(engine, expire_on_commit=False) as session:
        message = Message(
            company_id=identity.company_id,
            conversation_id=conversation_id,
            direction=direction,
            sender_type=sender_type,
            sender_identifier="controlled-sender",
            content_type=content_type,
            body_text=body,
            body_html=body if content_type == "html" else None,
            status=status,
            error_message=error_message,
            received_at=datetime.now(UTC) if status == "received" else None,
        )
        session.add(message)
        session.commit()
        return message


def test_list_messages_is_chronological_and_excludes_notes(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    first = _direct_message(migrated_engine, integration_identity, conversation.id, body="First")
    second = _direct_message(migrated_engine, integration_identity, conversation.id, body="Second")
    with Session(migrated_engine) as session:
        session.add(
            ConversationNote(
                company_id=integration_identity.company_id,
                conversation_id=conversation.id,
                author_membership_id=integration_identity.membership_id,
                body="Internal note must never appear",
            )
        )
        session.commit()
    response = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}/messages",
        headers=_owner_headers(integration_client, integration_identity),
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    ids = [item["id"] for item in items]
    assert ids.index(str(first.id)) < ids.index(str(second.id))
    assert all(item.get("body_text") != "Internal note must never appear" for item in items)


def test_message_cursor_pagination_and_content_filter(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    for index in range(3):
        _direct_message(
            migrated_engine, integration_identity, conversation.id, body=f"Text {index}"
        )
    _direct_message(
        migrated_engine,
        integration_identity,
        conversation.id,
        body="<p>HTML</p>",
        content_type="html",
    )
    headers = _owner_headers(integration_client, integration_identity)
    url = f"/v1/inbox/conversations/{conversation.id}/messages"
    first = integration_client.get(
        url, headers=headers, params={"page_size": 2, "content_type": "text"}
    )
    assert first.status_code == 200
    assert first.json()["has_more"] is True
    second = integration_client.get(
        url,
        headers=headers,
        params={
            "page_size": 2,
            "content_type": "text",
            "cursor": first.json()["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    first_ids = {item["id"] for item in first.json()["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert all(item["content_type"] == "text" for item in first.json()["items"])


def test_create_and_update_draft_derives_author_and_tenant(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    body = _draft(integration_client, headers, conversation.id)
    assert body["direction"] == "outbound"
    assert body["status"] == "draft"
    updated = integration_client.patch(
        f"/v1/inbox/messages/{body['id']}/draft",
        headers=headers,
        json={"body_text": "Updated draft"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["body_text"] == "Updated draft"
    with Session(migrated_engine) as session:
        stored = session.get(Message, UUID(str(body["id"])))
        assert stored is not None
        assert stored.company_id == integration_identity.company_id
        assert stored.sender_membership_id == integration_identity.membership_id


@pytest.mark.parametrize(
    "forbidden",
    [
        {"company_id": str(uuid4())},
        {"sender_membership_id": str(uuid4())},
        {"status": "sent"},
        {"external_message_id": "forbidden"},
        {"sender_type": "system"},
        {"content_type": "system_event", "body_text": "forbidden"},
    ],
)
def test_draft_rejects_privileged_or_system_fields(
    forbidden: dict[str, str],
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    response = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/drafts",
        headers=_owner_headers(integration_client, integration_identity),
        json={"body_text": "Body", **forbidden},
    )
    assert response.status_code == 422


def test_delete_draft_is_logical_and_irreversible(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    draft = _draft(integration_client, headers, conversation.id)
    url = f"/v1/inbox/messages/{draft['id']}/draft"
    assert integration_client.delete(url, headers=headers).status_code == 204
    assert (
        integration_client.get(f"/v1/inbox/messages/{draft['id']}", headers=headers).status_code
        == 404
    )
    with Session(migrated_engine) as session:
        stored = session.get(Message, UUID(str(draft["id"])))
        assert stored is not None and stored.discarded_at is not None
    assert (
        integration_client.patch(url, headers=headers, json={"body_text": "Resurrect"}).status_code
        == 404
    )


def test_viewer_cannot_create_draft(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity, other_tenant=True)
    response = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/drafts",
        headers=_viewer_headers(integration_client, integration_identity),
        json={"body_text": "Forbidden"},
    )
    assert response.status_code == 403


def test_foreign_conversation_and_message_are_opaque_404(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    foreign = _conversation(migrated_engine, integration_identity, other_tenant=True)
    with Session(migrated_engine, expire_on_commit=False) as session:
        message = Message(
            company_id=integration_identity.other_company_id,
            conversation_id=foreign.id,
            direction="inbound",
            sender_type="external",
            sender_identifier="foreign",
            content_type="text",
            body_text="Hidden",
            status="received",
        )
        session.add(message)
        session.commit()
    headers = _owner_headers(integration_client, integration_identity)
    assert (
        integration_client.get(
            f"/v1/inbox/conversations/{foreign.id}/messages", headers=headers
        ).status_code
        == 404
    )
    assert (
        integration_client.get(f"/v1/inbox/messages/{message.id}", headers=headers).status_code
        == 404
    )


def test_archived_conversation_refuses_drafts(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity, status="archived")
    response = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/drafts",
        headers=_owner_headers(integration_client, integration_identity),
        json={"body_text": "Forbidden"},
    )
    assert response.status_code == 409


def test_draft_queues_then_sends_and_becomes_immutable(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    draft = _draft(integration_client, headers, conversation.id)
    base = f"/v1/inbox/messages/{draft['id']}"
    queued = integration_client.post(f"{base}/queue", headers=headers)
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "queued"
    assert (
        integration_client.patch(
            f"{base}/draft", headers=headers, json={"body_text": "Forbidden"}
        ).status_code
        == 422
    )
    assert integration_client.delete(f"{base}/draft", headers=headers).status_code == 422
    sent = integration_client.post(f"{base}/send", headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_at"] is not None
    assert (
        integration_client.patch(
            f"{base}/draft", headers=headers, json={"body_text": "Forbidden"}
        ).status_code
        == 422
    )
    with Session(migrated_engine) as session:
        stored_conversation = session.get(Conversation, conversation.id)
        event_count = session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.content_type == "system_event",
            )
        )
        assert stored_conversation is not None and stored_conversation.last_message_at is not None
        assert event_count == 1


def test_queue_and_send_create_audit_logs(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    draft = _draft(integration_client, headers, conversation.id)
    message_id = UUID(str(draft["id"]))
    integration_client.post(f"/v1/inbox/messages/{message_id}/queue", headers=headers)
    integration_client.post(f"/v1/inbox/messages/{message_id}/send", headers=headers)
    with Session(migrated_engine) as session:
        actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.company_id == integration_identity.company_id,
                    AuditLog.resource_id == str(message_id),
                )
            )
        )
    assert {"inbox.message.draft_created", "inbox.message.queued", "inbox.message.sent"} <= actions


def test_simulated_inbound_increments_unread_and_reopens_resolved(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    contact = _contact(migrated_engine, integration_identity)
    conversation = _conversation(
        migrated_engine,
        integration_identity,
        status="resolved",
        unread_count=2,
        contact_id=contact.id,
    )
    response = integration_client.post(
        "/v1/inbox/messages/simulate-inbound",
        headers=_owner_headers(integration_client, integration_identity),
        json={"conversation_id": str(conversation.id), "body_text": "Inbound"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["direction"] == "inbound"
    assert body["status"] == "received"
    assert body["received_at"] is not None
    with Session(migrated_engine) as session:
        stored = session.get(Conversation, conversation.id)
        assert stored is not None
        assert stored.status == "open"
        assert stored.unread_count == 3
        assert stored.last_message_at is not None


def test_simulated_inbound_is_idempotent_by_external_id(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    payload = {
        "conversation_id": str(conversation.id),
        "sender_identifier": "technical-sender",
        "body_text": "Inbound once",
        "external_message_id": f"sim-{uuid4().hex}",
    }
    first = integration_client.post(
        "/v1/inbox/messages/simulate-inbound", headers=headers, json=payload
    )
    second = integration_client.post(
        "/v1/inbox/messages/simulate-inbound", headers=headers, json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    with Session(migrated_engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.external_message_id == payload["external_message_id"])
        )
    assert count == 1


def test_simulated_inbound_refuses_archived_conversation(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity, status="archived")
    response = integration_client.post(
        "/v1/inbox/messages/simulate-inbound",
        headers=_owner_headers(integration_client, integration_identity),
        json={
            "conversation_id": str(conversation.id),
            "sender_identifier": "technical",
            "body_text": "Forbidden",
        },
    )
    assert response.status_code == 409


def test_reply_must_belong_to_same_conversation(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    first = _conversation(migrated_engine, integration_identity)
    second = _conversation(migrated_engine, integration_identity)
    reply = _direct_message(migrated_engine, integration_identity, second.id)
    response = integration_client.post(
        f"/v1/inbox/conversations/{first.id}/drafts",
        headers=_owner_headers(integration_client, integration_identity),
        json={"body_text": "Wrong reply", "reply_to_message_id": str(reply.id)},
    )
    assert response.status_code == 422


def test_html_is_untrusted_and_technical_error_is_hidden(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    message = _direct_message(
        migrated_engine,
        integration_identity,
        conversation.id,
        content_type="html",
        body="<script>alert(1)</script><p>Unsafe</p>",
        error_message="smtp-secret-stack-trace",
    )
    with Session(migrated_engine) as session:
        stored = session.get(Message, message.id)
        assert stored is not None
        session.add(
            MessageAttachment(
                company_id=integration_identity.company_id,
                message_id=message.id,
                filename="invoice.pdf",
                mime_type="application/pdf",
                size_bytes=128,
                storage_key="internal/secret/storage-key",
            )
        )
        session.commit()
    response = integration_client.get(
        f"/v1/inbox/messages/{message.id}",
        headers=_owner_headers(integration_client, integration_identity),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["html_requires_sanitization"] is True
    assert body["body_html"].startswith("<script>")
    assert "error_message" not in body
    assert "storage_key" not in body["attachments"][0]


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_simulation_requires_technical_permission_and_test_environment(
    environment: str,
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = _conversation(migrated_engine, integration_identity, other_tenant=True)
    viewer = integration_client.post(
        "/v1/inbox/messages/simulate-inbound",
        headers=_viewer_headers(integration_client, integration_identity),
        json={
            "conversation_id": str(foreign.id),
            "sender_identifier": "viewer",
            "body_text": "Forbidden",
        },
    )
    assert viewer.status_code == 403
    own = _conversation(migrated_engine, integration_identity)
    monkeypatch.setattr(message_routes, "settings", SimpleNamespace(environment=environment))
    outside_test = integration_client.post(
        "/v1/inbox/messages/simulate-inbound",
        headers=_owner_headers(integration_client, integration_identity),
        json={
            "conversation_id": str(own.id),
            "sender_identifier": "technical",
            "body_text": "Forbidden",
        },
    )
    assert outside_test.status_code == 404


def test_simulation_accepts_explicit_e2e_environment(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    monkeypatch.setattr(message_routes, "settings", SimpleNamespace(environment="e2e"))
    response = integration_client.post(
        "/v1/inbox/messages/simulate-inbound",
        headers=_owner_headers(integration_client, integration_identity),
        json={
            "conversation_id": str(conversation.id),
            "sender_identifier": "controlled-e2e-sender",
            "body_text": "Allowed in E2E",
        },
    )
    assert response.status_code == 201, response.text


def test_simulation_permission_is_limited_to_owner_and_admin(
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        role_codes = set(
            session.scalars(
                select(Role.code)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(Permission.code == "inbox.simulate_inbound")
            )
        )
    assert role_codes == {"owner", "admin"}


def test_sent_message_cannot_be_physically_deleted_by_application_role(
    migrated_engine: Engine,
    integration_identity: IntegrationIdentity,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    message = _direct_message(
        migrated_engine,
        integration_identity,
        conversation.id,
        status="sent",
        direction="outbound",
        sender_type="user",
    )
    with pytest.raises(DBAPIError):
        with migrated_engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE automation_app"))
            connection.execute(
                text("SELECT set_config('app.current_company_id', :company_id, true)"),
                {"company_id": str(integration_identity.company_id)},
            )
            connection.execute(delete(Message).where(Message.id == message.id))


def test_message_list_query_count_is_constant(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    for index in range(6):
        _direct_message(
            migrated_engine, integration_identity, conversation.id, body=f"Message {index}"
        )
    headers = _owner_headers(integration_client, integration_identity)
    url = f"/v1/inbox/conversations/{conversation.id}/messages"

    def count_selects(page_size: int) -> int:
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
            response = integration_client.get(url, headers=headers, params={"page_size": page_size})
            assert response.status_code == 200, response.text
        finally:
            event.remove(migrated_engine, "before_cursor_execute", capture)
        return len(statements)

    assert count_selects(1) == count_selects(6)
