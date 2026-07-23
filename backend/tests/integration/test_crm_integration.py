from typing import Protocol
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    Contact,
    CrmActivity,
    CrmTask,
    Lead,
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


def _token(
    client: TestClient,
    *,
    email: str,
    password: str,
    company_id: UUID,
) -> str:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password, "company_id": str(company_id)},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _owner_headers(client: TestClient, identity: IntegrationIdentity) -> dict[str, str]:
    token = _token(
        client,
        email=identity.email,
        password=identity.password,
        company_id=identity.company_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _viewer_headers(client: TestClient, identity: IntegrationIdentity) -> dict[str, str]:
    token = _token(
        client,
        email=identity.other_email,
        password=identity.other_password,
        company_id=identity.other_company_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _create_contact(client: TestClient, headers: dict[str, str], email: str) -> dict:
    response = client.post(
        "/v1/crm/contacts",
        headers=headers,
        json={
            "first_name": "Lina",
            "last_name": "Martin",
            "email": email,
            "phone": "+212 6 12-34-56-78",
            "organization_name": "Northwind",
            "consent_email": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_lead(client: TestClient, headers: dict[str, str], contact_id: str) -> dict:
    response = client.post(
        "/v1/crm/leads",
        headers=headers,
        json={
            "contact_id": contact_id,
            "title": "Automatisation commerciale",
            "need_description": "Qualifier les demandes entrantes",
            "estimated_budget": "15000.00",
            "score": 72,
            "priority": "high",
            "source": "form",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_contact_normalization_duplicate_and_tenant_aware_uniqueness(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    contact = _create_contact(integration_client, headers, "Lina.Martin@Example.com")
    assert "company_id" not in contact
    assert "email_normalized" not in contact

    with Session(migrated_engine) as session:
        stored = session.get(Contact, UUID(contact["id"]))
        assert stored is not None
        assert stored.email_normalized == "lina.martin@example.com"
        assert stored.phone_normalized == "+212612345678"
        session.add(
            Contact(
                company_id=integration_identity.other_company_id,
                created_by_membership_id=integration_identity.other_membership_id,
                first_name="Other",
                last_name="Tenant",
                email="lina.martin@example.com",
                email_normalized="lina.martin@example.com",
            )
        )
        session.commit()

    duplicate = integration_client.post(
        "/v1/crm/contacts",
        headers=headers,
        json={"last_name": "Duplicate", "email": "lina.martin@example.com"},
    )
    assert duplicate.status_code == 409


def test_lead_validation_and_cross_tenant_assignment_are_enforced(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    contact = _create_contact(integration_client, headers, "lead-rules@example.com")

    invalid_score = integration_client.post(
        "/v1/crm/leads",
        headers=headers,
        json={"contact_id": contact["id"], "title": "Invalid", "score": 101},
    )
    assert invalid_score.status_code == 422

    lead = _create_lead(integration_client, headers, contact["id"])
    lost_without_reason = integration_client.post(
        f"/v1/crm/leads/{lead['id']}/status",
        headers=headers,
        json={"status": "lost"},
    )
    assert lost_without_reason.status_code == 422

    cross_assignment = integration_client.post(
        f"/v1/crm/leads/{lead['id']}/assign",
        headers=headers,
        json={"assigned_membership_id": str(integration_identity.other_membership_id)},
    )
    assert cross_assignment.status_code == 422


def test_cross_tenant_lead_read_and_update_are_impossible(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine) as session:
        foreign_contact = Contact(
            company_id=integration_identity.other_company_id,
            created_by_membership_id=integration_identity.other_membership_id,
            last_name="Foreign Contact",
        )
        session.add(foreign_contact)
        session.flush()
        foreign_lead = Lead(
            company_id=integration_identity.other_company_id,
            contact_id=foreign_contact.id,
            title="Foreign Lead",
            created_by_membership_id=integration_identity.other_membership_id,
        )
        session.add(foreign_lead)
        session.commit()
        foreign_id = foreign_lead.id

    headers = _owner_headers(integration_client, integration_identity)
    assert integration_client.get(f"/v1/crm/leads/{foreign_id}", headers=headers).status_code == 404
    assert (
        integration_client.patch(
            f"/v1/crm/leads/{foreign_id}",
            headers=headers,
            json={"score": 90},
        ).status_code
        == 404
    )

    with migrated_engine.connect() as connection, connection.begin():
        connection.execute(text("SET LOCAL ROLE automation_app"))
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(integration_identity.company_id)},
        )
        result = connection.execute(
            update(Lead).where(Lead.id == foreign_id).values(title="Compromised")
        )
        assert result.rowcount == 0


def test_archive_blocks_future_modifications_and_new_leads(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    contact = _create_contact(integration_client, headers, "archive@example.com")
    lead = _create_lead(integration_client, headers, contact["id"])

    archive_lead = integration_client.post(f"/v1/crm/leads/{lead['id']}/archive", headers=headers)
    assert archive_lead.status_code == 204
    blocked_update = integration_client.patch(
        f"/v1/crm/leads/{lead['id']}", headers=headers, json={"score": 99}
    )
    assert blocked_update.status_code == 409

    assert (
        integration_client.post(
            f"/v1/crm/contacts/{contact['id']}/archive", headers=headers
        ).status_code
        == 204
    )
    blocked_lead = integration_client.post(
        "/v1/crm/leads",
        headers=headers,
        json={"contact_id": contact["id"], "title": "Blocked"},
    )
    assert blocked_lead.status_code == 409


def test_status_assignment_activities_tasks_and_audit_are_persisted(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    contact = _create_contact(integration_client, headers, "history@example.com")
    lead = _create_lead(integration_client, headers, contact["id"])

    assignment = integration_client.post(
        f"/v1/crm/leads/{lead['id']}/assign",
        headers=headers,
        json={"assigned_membership_id": str(integration_identity.membership_id)},
    )
    assert assignment.status_code == 200
    won = integration_client.post(
        f"/v1/crm/leads/{lead['id']}/status",
        headers=headers,
        json={"status": "won"},
    )
    assert won.status_code == 200

    note = integration_client.post(
        f"/v1/crm/leads/{lead['id']}/activities",
        headers=headers,
        json={"activity_type": "note", "subject": "Compte-rendu", "description": "RAS"},
    )
    assert note.status_code == 201
    assert (
        integration_client.post(
            f"/v1/crm/leads/{lead['id']}/activities",
            headers=headers,
            json={"activity_type": "system", "subject": "Forged"},
        ).status_code
        == 422
    )

    task = integration_client.post(
        "/v1/crm/tasks",
        headers=headers,
        json={
            "lead_id": lead["id"],
            "title": "Préparer le contrat",
            "priority": "urgent",
            "assigned_membership_id": str(integration_identity.membership_id),
        },
    )
    assert task.status_code == 201
    completed = integration_client.post(
        f"/v1/crm/tasks/{task.json()['id']}/complete", headers=headers
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None

    activities = integration_client.get(
        f"/v1/crm/leads/{lead['id']}/activities", headers=headers
    ).json()["items"]
    activity_types = {item["activity_type"] for item in activities}
    assert {"assignment", "status_change", "system", "note", "task"} <= activity_types

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(AuditLog).where(
                    AuditLog.action == "crm.lead.status_changed",
                    AuditLog.resource_id == lead["id"],
                )
            )
            is not None
        )
        assert session.scalar(select(CrmTask).where(CrmTask.id == UUID(task.json()["id"])))

    note_id = UUID(note.json()["id"])
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET LOCAL ROLE automation_app"))
        connection.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(integration_identity.company_id)},
        )
        with pytest.raises(DBAPIError):
            connection.execute(
                update(CrmActivity).where(CrmActivity.id == note_id).values(subject="Tampered")
            )
        transaction.rollback()


def test_viewer_is_read_only(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
) -> None:
    headers = _viewer_headers(integration_client, integration_identity)
    assert integration_client.get("/v1/crm/leads", headers=headers).status_code == 200
    denied = integration_client.post(
        "/v1/crm/contacts",
        headers=headers,
        json={"last_name": "Forbidden"},
    )
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Permission denied"}


def test_atomic_contact_and_lead_creation_and_duplicate_handling(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    payload = {
        "contact": {
            "first_name": "Atomic",
            "last_name": "Prospect",
            "email": "Atomic.Prospect@Example.com",
        },
        "lead": {
            "title": "Atomic opportunity",
            "score": 64,
            "priority": "medium",
        },
    }
    response = integration_client.post(
        "/v1/crm/leads/with-contact",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["lead"]["contact_id"] == created["contact"]["id"]
    assert "company_id" not in created["contact"]
    assert "company_id" not in created["lead"]

    duplicate = integration_client.post(
        "/v1/crm/leads/with-contact",
        headers=headers,
        json=payload,
    )
    assert duplicate.status_code == 409
    with Session(migrated_engine) as session:
        contacts = session.scalars(
            select(Contact).where(Contact.email_normalized == "atomic.prospect@example.com")
        ).all()
        assert len(contacts) == 1
        assert session.scalar(
            select(AuditLog).where(
                AuditLog.action == "crm.lead.created",
                AuditLog.resource_id == created["lead"]["id"],
            )
        )


def test_atomic_creation_rolls_back_contact_when_lead_flush_fails(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.orm import Session as SqlAlchemySession

    original_flush = SqlAlchemySession.flush

    def fail_target_lead_flush(
        session: SqlAlchemySession,
        objects: object | None = None,
    ) -> None:
        if any(
            isinstance(item, Lead) and item.title == "Force integration rollback"
            for item in session.new
        ):
            raise RuntimeError("synthetic lead persistence failure")
        original_flush(session, objects)

    monkeypatch.setattr(SqlAlchemySession, "flush", fail_target_lead_flush)
    headers = _owner_headers(integration_client, integration_identity)
    with pytest.raises(RuntimeError, match="synthetic lead persistence failure"):
        integration_client.post(
            "/v1/crm/leads/with-contact",
            headers=headers,
            json={
                "contact": {
                    "last_name": "Rollback",
                    "email": "rollback-atomic@example.com",
                },
                "lead": {"title": "Force integration rollback"},
            },
        )

    with Session(migrated_engine) as session:
        assert (
            session.scalar(
                select(Contact).where(Contact.email_normalized == "rollback-atomic@example.com")
            )
            is None
        )


def test_cross_tenant_contacts_tasks_and_activities_are_hidden_and_audited(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        foreign_contact = Contact(
            company_id=integration_identity.other_company_id,
            created_by_membership_id=integration_identity.other_membership_id,
            last_name="Hidden Contact",
        )
        session.add(foreign_contact)
        session.flush()
        foreign_lead = Lead(
            company_id=integration_identity.other_company_id,
            contact_id=foreign_contact.id,
            title="Hidden Lead",
            created_by_membership_id=integration_identity.other_membership_id,
        )
        foreign_task = CrmTask(
            company_id=integration_identity.other_company_id,
            contact_id=foreign_contact.id,
            title="Hidden Task",
            created_by_membership_id=integration_identity.other_membership_id,
        )
        session.add_all([foreign_lead, foreign_task])
        session.commit()
        contact_id = foreign_contact.id
        lead_id = foreign_lead.id
        task_id = foreign_task.id

    headers = _owner_headers(integration_client, integration_identity)
    assert (
        integration_client.get(f"/v1/crm/contacts/{contact_id}", headers=headers).status_code == 404
    )
    assert (
        integration_client.patch(
            f"/v1/crm/contacts/{contact_id}",
            headers=headers,
            json={"last_name": "Compromised"},
        ).status_code
        == 404
    )
    task_list = integration_client.get(
        f"/v1/crm/tasks?contact_id={contact_id}",
        headers=headers,
    )
    assert task_list.status_code == 200
    assert task_list.json()["items"] == []
    assert (
        integration_client.patch(
            f"/v1/crm/tasks/{task_id}",
            headers=headers,
            json={"title": "Compromised"},
        ).status_code
        == 404
    )
    assert (
        integration_client.post(
            f"/v1/crm/leads/{lead_id}/activities",
            headers=headers,
            json={"activity_type": "note", "subject": "Cross tenant"},
        ).status_code
        == 404
    )

    with Session(migrated_engine) as session:
        denied_resource_ids = set(
            session.scalars(
                select(AuditLog.resource_id).where(
                    AuditLog.company_id == integration_identity.company_id,
                    AuditLog.action == "security.cross_tenant",
                )
            )
        )
        assert {str(contact_id), str(task_id), str(lead_id)} <= denied_resource_ids


def test_assignees_require_members_read_and_do_not_expose_email(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    owner_headers = _owner_headers(integration_client, integration_identity)
    allowed = integration_client.get("/v1/crm/assignees", headers=owner_headers)
    assert allowed.status_code == 200
    assert allowed.json()
    assert set(allowed.json()[0]) == {"membership_id", "display_name", "status", "role"}

    with Session(migrated_engine) as session:
        viewer = session.scalar(select(Role).where(Role.code == "viewer"))
        members_read = session.scalar(select(Permission).where(Permission.code == "members.read"))
        assert viewer is not None and members_read is not None
        link = session.get(RolePermission, (viewer.id, members_read.id))
        assert link is not None
        viewer_role_id = viewer.id
        members_read_id = members_read.id
        session.delete(link)
        session.commit()

    try:
        viewer_headers = _viewer_headers(integration_client, integration_identity)
        assert (
            integration_client.get("/v1/crm/assignees", headers=viewer_headers).status_code == 403
        )
        assert integration_client.get("/v1/crm/leads", headers=viewer_headers).status_code == 200
    finally:
        with Session(migrated_engine) as session:
            session.add(
                RolePermission(
                    role_id=viewer_role_id,
                    permission_id=members_read_id,
                )
            )
            session.commit()


def test_lead_archive_is_idempotent_and_pagination_is_bounded(
    integration_client: TestClient,
    integration_identity: IntegrationIdentity,
    migrated_engine: Engine,
) -> None:
    headers = _owner_headers(integration_client, integration_identity)
    contact = _create_contact(integration_client, headers, "idempotent-archive@example.com")
    lead = _create_lead(integration_client, headers, contact["id"])

    assert (
        integration_client.post(f"/v1/crm/leads/{lead['id']}/archive", headers=headers).status_code
        == 204
    )
    assert (
        integration_client.post(f"/v1/crm/leads/{lead['id']}/archive", headers=headers).status_code
        == 204
    )
    with Session(migrated_engine) as session:
        archive_activities = session.scalars(
            select(CrmActivity).where(
                CrmActivity.lead_id == UUID(lead["id"]),
                CrmActivity.activity_type == "status_change",
                CrmActivity.subject == "Prospect archivé",
            )
        ).all()
        assert len(archive_activities) == 1

    for path in ("contacts", "leads", "tasks"):
        response = integration_client.get(f"/v1/crm/{path}?page=101", headers=headers)
        assert response.status_code == 422
