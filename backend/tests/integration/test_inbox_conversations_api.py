from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    Contact,
    Conversation,
    ConversationParticipant,
    ConversationTag,
    ConversationTagLink,
    Lead,
    Membership,
    Message,
    Role,
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


def _contact(
    engine: Engine,
    *,
    company_id: UUID,
    membership_id: UUID,
    suffix: str,
) -> Contact:
    with Session(engine, expire_on_commit=False) as session:
        contact = Contact(
            company_id=company_id,
            first_name="Inbox",
            last_name=f"Contact {suffix}",
            email=f"inbox-{suffix}@example.com",
            email_normalized=f"inbox-{suffix}@example.com",
            organization_name="Northwind",
            created_by_membership_id=membership_id,
        )
        session.add(contact)
        session.commit()
        return contact


def _lead(
    engine: Engine,
    *,
    company_id: UUID,
    membership_id: UUID,
    contact_id: UUID,
    suffix: str,
) -> Lead:
    with Session(engine, expire_on_commit=False) as session:
        lead = Lead(
            company_id=company_id,
            contact_id=contact_id,
            title=f"Inbox lead {suffix}",
            created_by_membership_id=membership_id,
        )
        session.add(lead)
        session.commit()
        return lead


def _conversation(
    engine: Engine,
    identity: IntegrationIdentity,
    *,
    other_tenant: bool = False,
    subject: str | None = None,
    status: str = "open",
    priority: str = "normal",
    unread_count: int = 0,
    created_at: datetime | None = None,
) -> Conversation:
    company_id = identity.other_company_id if other_tenant else identity.company_id
    membership_id = identity.other_membership_id if other_tenant else identity.membership_id
    with Session(engine, expire_on_commit=False) as session:
        conversation = Conversation(
            company_id=company_id,
            channel="internal",
            subject=subject or f"Conversation {uuid4().hex[:8]}",
            status=status,
            priority=priority,
            unread_count=unread_count,
            created_by_membership_id=membership_id,
            created_at=created_at or datetime.now(UTC),
            updated_at=created_at or datetime.now(UTC),
            resolved_at=datetime.now(UTC) if status == "resolved" else None,
            closed_at=datetime.now(UTC) if status == "closed" else None,
        )
        session.add(conversation)
        session.commit()
        return conversation


def _create_api_conversation(
    client: TestClient,
    headers: dict[str, str],
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "channel": "internal",
        "subject": f"API conversation {uuid4().hex[:8]}",
        "priority": "normal",
    }
    payload.update(overrides)
    response = client.post("/v1/inbox/conversations", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_derives_tenant_and_rejects_privileged_fields(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    body = _create_api_conversation(integration_client, headers, subject="Secure creation")
    assert "company_id" not in body
    assert body["status"] == "open"
    assert body["unread_count"] == 0
    with Session(migrated_engine) as session:
        stored = session.get(Conversation, UUID(str(body["id"])))
        assert stored is not None
        assert stored.company_id == integration_identity.company_id
        assert stored.created_by_membership_id == integration_identity.membership_id

    for forbidden in (
        {"company_id": str(integration_identity.other_company_id)},
        {"created_by_membership_id": str(integration_identity.other_membership_id)},
        {"unread_count": 99},
        {"human_takeover": True},
        {"status": "resolved"},
    ):
        response = integration_client.post(
            "/v1/inbox/conversations",
            headers=headers,
            json={"channel": "internal", **forbidden},
        )
        assert response.status_code == 422


def test_create_accepts_coherent_contact_and_lead(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    contact = _contact(
        migrated_engine,
        company_id=integration_identity.company_id,
        membership_id=integration_identity.membership_id,
        suffix=uuid4().hex,
    )
    lead = _lead(
        migrated_engine,
        company_id=integration_identity.company_id,
        membership_id=integration_identity.membership_id,
        contact_id=contact.id,
        suffix=uuid4().hex,
    )
    body = _create_api_conversation(
        integration_client,
        _owner_headers(integration_client, integration_identity),
        contact_id=str(contact.id),
        lead_id=str(lead.id),
    )
    assert body["contact_id"] == str(contact.id)
    assert body["lead_id"] == str(lead.id)


@pytest.mark.parametrize("resource", ["contact", "lead"])
def test_create_refuses_foreign_contact_or_lead(
    resource: str,
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    contact = _contact(
        migrated_engine,
        company_id=integration_identity.other_company_id,
        membership_id=integration_identity.other_membership_id,
        suffix=uuid4().hex,
    )
    value: UUID = contact.id
    if resource == "lead":
        value = _lead(
            migrated_engine,
            company_id=integration_identity.other_company_id,
            membership_id=integration_identity.other_membership_id,
            contact_id=contact.id,
            suffix=uuid4().hex,
        ).id
    response = integration_client.post(
        "/v1/inbox/conversations",
        headers=_owner_headers(integration_client, integration_identity),
        json={"channel": "internal", f"{resource}_id": str(value)},
    )
    assert response.status_code == 422
    assert "company" not in response.text.lower()
    with Session(migrated_engine) as session:
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.company_id == integration_identity.company_id,
                AuditLog.action == "security.cross_tenant",
                AuditLog.resource_type == resource,
                AuditLog.resource_id == str(value),
            )
        )
    assert audit is not None


def test_create_refuses_inactive_assignee(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        role = session.scalar(select(Role).where(Role.code == "support"))
        user = User(email=f"inactive-{uuid4().hex}@example.com", status="active")
        session.add(user)
        session.flush()
        membership = Membership(
            company_id=integration_identity.company_id,
            user_id=user.id,
            role_id=role.id if role else None,
            status="inactive",
        )
        session.add(membership)
        session.commit()
    response = integration_client.post(
        "/v1/inbox/conversations",
        headers=_owner_headers(integration_client, integration_identity),
        json={
            "channel": "internal",
            "assigned_membership_id": str(membership.id),
        },
    )
    assert response.status_code == 422


def test_list_is_tenant_isolated_and_supports_filters(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    own = _conversation(
        migrated_engine,
        integration_identity,
        subject="Needle Support",
        priority="urgent",
        unread_count=2,
    )
    _conversation(
        migrated_engine,
        integration_identity,
        other_tenant=True,
        subject="Needle Foreign",
        priority="urgent",
        unread_count=2,
    )
    response = integration_client.get(
        "/v1/inbox/conversations",
        headers=_owner_headers(integration_client, integration_identity),
        params={"search": "Needle", "priority": "urgent", "unread_only": True},
    )
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert str(own.id) in ids
    assert len(ids) == 1


def test_cursor_pagination_has_no_duplicates(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    base = datetime.now(UTC) - timedelta(days=1)
    created = {
        str(
            _conversation(
                migrated_engine,
                integration_identity,
                created_at=base + timedelta(minutes=index),
            ).id
        )
        for index in range(4)
    }
    headers = _owner_headers(integration_client, integration_identity)
    first = integration_client.get(
        "/v1/inbox/conversations",
        headers=headers,
        params={"sort_by": "created_at", "sort_direction": "asc", "page_size": 2},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["has_more"] is True
    second = integration_client.get(
        "/v1/inbox/conversations",
        headers=headers,
        params={
            "sort_by": "created_at",
            "sort_direction": "asc",
            "page_size": 100,
            "cursor": first_body["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert created.issubset(first_ids | second_ids)


def test_invalid_cursor_and_page_size_are_rejected(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    assert (
        integration_client.get(
            "/v1/inbox/conversations", headers=headers, params={"cursor": "invalid"}
        ).status_code
        == 422
    )
    assert (
        integration_client.get(
            "/v1/inbox/conversations", headers=headers, params={"page_size": 101}
        ).status_code
        == 422
    )


def test_detail_returns_summaries_without_full_history(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    contact = _contact(
        migrated_engine,
        company_id=integration_identity.company_id,
        membership_id=integration_identity.membership_id,
        suffix=uuid4().hex,
    )
    lead = _lead(
        migrated_engine,
        company_id=integration_identity.company_id,
        membership_id=integration_identity.membership_id,
        contact_id=contact.id,
        suffix=uuid4().hex,
    )
    with Session(migrated_engine, expire_on_commit=False) as session:
        conversation = Conversation(
            company_id=integration_identity.company_id,
            contact_id=contact.id,
            lead_id=lead.id,
            channel="internal",
            created_by_membership_id=integration_identity.membership_id,
        )
        session.add(conversation)
        session.flush()
        participant = ConversationParticipant(
            company_id=integration_identity.company_id,
            conversation_id=conversation.id,
            participant_type="contact",
            contact_id=contact.id,
            display_name="Inbox contact",
            email=contact.email,
        )
        tag = ConversationTag(
            company_id=integration_identity.company_id,
            name=f"VIP {uuid4().hex[:8]}",
        )
        session.add_all([participant, tag])
        session.flush()
        session.add(
            ConversationTagLink(
                company_id=integration_identity.company_id,
                conversation_id=conversation.id,
                tag_id=tag.id,
                created_by_membership_id=integration_identity.membership_id,
            )
        )
        session.add_all(
            [
                Message(
                    company_id=integration_identity.company_id,
                    conversation_id=conversation.id,
                    direction="internal",
                    sender_type="system",
                    content_type="system_event",
                    body_text=f"Event {index}",
                    status="received",
                )
                for index in range(2)
            ]
        )
        session.commit()
        conversation_id = conversation.id

    response = integration_client.get(
        f"/v1/inbox/conversations/{conversation_id}",
        headers=_owner_headers(integration_client, integration_identity),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contact"]["id"] == str(contact.id)
    assert body["lead"]["id"] == str(lead.id)
    assert body["message_count"] == 2
    assert len(body["participants"]) == 1
    assert len(body["tags"]) == 1
    assert "messages" not in body
    assert "body_html" not in body["last_message"]


def test_foreign_detail_and_update_are_opaque_404(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    foreign = _conversation(migrated_engine, integration_identity, other_tenant=True)
    headers = _owner_headers(integration_client, integration_identity)
    assert (
        integration_client.get(f"/v1/inbox/conversations/{foreign.id}", headers=headers).status_code
        == 404
    )
    assert (
        integration_client.patch(
            f"/v1/inbox/conversations/{foreign.id}",
            headers=headers,
            json={"subject": "Forbidden"},
        ).status_code
        == 404
    )


def test_patch_subject_and_creation_are_audited(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    created = _create_api_conversation(integration_client, headers, subject="Before update")
    conversation_id = UUID(str(created["id"]))
    response = integration_client.patch(
        f"/v1/inbox/conversations/{conversation_id}",
        headers=headers,
        json={"subject": "After update"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["subject"] == "After update"
    with Session(migrated_engine) as session:
        actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.company_id == integration_identity.company_id,
                    AuditLog.resource_id == str(conversation_id),
                )
            )
        )
    assert {
        "inbox.conversation.created",
        "inbox.conversation.updated",
    }.issubset(actions)


def test_assignment_is_idempotent_and_foreign_assignment_is_refused(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    url = f"/v1/inbox/conversations/{conversation.id}/assign"
    first = integration_client.post(
        url,
        headers=headers,
        json={"assigned_membership_id": str(integration_identity.membership_id)},
    )
    assert first.status_code == 200, first.text
    with Session(migrated_engine) as session:
        count_before = session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation.id)
        )
    repeated = integration_client.post(
        url,
        headers=headers,
        json={"assigned_membership_id": str(integration_identity.membership_id)},
    )
    assert repeated.status_code == 200
    with Session(migrated_engine) as session:
        count_after = session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation.id)
        )
    assert count_after == count_before
    foreign = integration_client.post(
        url,
        headers=headers,
        json={"assigned_membership_id": str(integration_identity.other_membership_id)},
    )
    assert foreign.status_code == 422
    with Session(migrated_engine) as session:
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.company_id == integration_identity.company_id,
                AuditLog.action == "security.cross_tenant",
                AuditLog.resource_type == "membership",
                AuditLog.resource_id == str(integration_identity.other_membership_id),
            )
        )
    assert audit is not None


def test_status_lifecycle_resolution_closure_and_reopen(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    status_url = f"/v1/inbox/conversations/{conversation.id}/status"
    resolved = integration_client.post(status_url, headers=headers, json={"status": "resolved"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolved_at"] is not None
    closed = integration_client.post(status_url, headers=headers, json={"status": "closed"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["closed_at"] is not None
    invalid = integration_client.post(status_url, headers=headers, json={"status": "open"})
    assert invalid.status_code == 409
    reopened = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/reopen", headers=headers
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "open"
    assert reopened.json()["closed_at"] is None
    assert reopened.json()["resolved_at"] is None


def test_invalid_active_transition_is_rejected(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    response = integration_client.post(
        f"/v1/inbox/conversations/{conversation.id}/status",
        headers=_owner_headers(integration_client, integration_identity),
        json={"status": "closed"},
    )
    assert response.status_code == 422


def test_priority_changes_once_and_is_audited(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    url = f"/v1/inbox/conversations/{conversation.id}/priority"
    changed = integration_client.post(url, headers=headers, json={"priority": "urgent"})
    assert changed.status_code == 200, changed.text
    repeated = integration_client.post(url, headers=headers, json={"priority": "urgent"})
    assert repeated.status_code == 200
    with Session(migrated_engine) as session:
        audit_count = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.company_id == integration_identity.company_id,
                AuditLog.resource_id == str(conversation.id),
                AuditLog.action == "inbox.conversation.priority_changed",
            )
        )
    assert audit_count == 1


def test_archive_is_idempotent_and_blocks_future_changes(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    headers = _owner_headers(integration_client, integration_identity)
    archive_url = f"/v1/inbox/conversations/{conversation.id}/archive"
    first = integration_client.post(archive_url, headers=headers)
    second = integration_client.post(archive_url, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "archived"
    update_response = integration_client.patch(
        f"/v1/inbox/conversations/{conversation.id}",
        headers=headers,
        json={"subject": "Forbidden"},
    )
    assert update_response.status_code == 409


def test_mark_read_and_mark_unread_are_server_controlled(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity, unread_count=4)
    headers = _owner_headers(integration_client, integration_identity)
    base = f"/v1/inbox/conversations/{conversation.id}"
    read = integration_client.post(f"{base}/mark-read", headers=headers)
    assert read.status_code == 200
    assert read.json()["unread_count"] == 0
    unread = integration_client.post(f"{base}/mark-unread", headers=headers)
    assert unread.status_code == 200
    assert unread.json()["unread_count"] == 1
    assert (
        integration_client.post(
            f"{base}/mark-unread", headers=headers, json={"unread_count": 99}
        ).json()["unread_count"]
        == 1
    )


def test_takeover_and_release_do_not_reenable_ai(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity)
    with Session(migrated_engine) as session:
        stored = session.get(Conversation, conversation.id)
        assert stored is not None
        stored.ai_enabled = True
        session.commit()
    headers = _owner_headers(integration_client, integration_identity)
    base = f"/v1/inbox/conversations/{conversation.id}"
    takeover = integration_client.post(f"{base}/takeover", headers=headers)
    assert takeover.status_code == 200, takeover.text
    assert takeover.json()["human_takeover"] is True
    assert takeover.json()["ai_enabled"] is False
    release = integration_client.post(f"{base}/release", headers=headers)
    assert release.status_code == 200, release.text
    assert release.json()["human_takeover"] is False
    assert release.json()["ai_enabled"] is False


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("patch", "", {"subject": "Forbidden"}),
        ("post", "/assign", {"assigned_membership_id": None}),
        ("post", "/status", {"status": "pending"}),
        ("post", "/priority", {"priority": "high"}),
        ("post", "/archive", None),
        ("post", "/takeover", None),
    ],
)
def test_viewer_is_refused_on_writes(
    method: str,
    suffix: str,
    payload: dict[str, object] | None,
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity, other_tenant=True)
    response = integration_client.request(
        method,
        f"/v1/inbox/conversations/{conversation.id}{suffix}",
        headers=_viewer_headers(integration_client, integration_identity),
        json=payload,
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Permission denied"}


def test_viewer_can_read_own_tenant_and_owner_cannot_see_it(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    conversation = _conversation(migrated_engine, integration_identity, other_tenant=True)
    viewer = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}",
        headers=_viewer_headers(integration_client, integration_identity),
    )
    assert viewer.status_code == 200
    owner = integration_client.get(
        f"/v1/inbox/conversations/{conversation.id}",
        headers=_owner_headers(integration_client, integration_identity),
    )
    assert owner.status_code == 404


def test_list_query_count_does_not_scale_with_page_size(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    for index in range(6):
        _conversation(migrated_engine, integration_identity, subject=f"N plus one {index}")
    headers = _owner_headers(integration_client, integration_identity)

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
            response = integration_client.get(
                "/v1/inbox/conversations",
                headers=headers,
                params={"search": "N plus one", "page_size": page_size},
            )
            assert response.status_code == 200, response.text
        finally:
            event.remove(migrated_engine, "before_cursor_execute", capture)
        return len(statements)

    assert count_selects(1) == count_selects(6)
