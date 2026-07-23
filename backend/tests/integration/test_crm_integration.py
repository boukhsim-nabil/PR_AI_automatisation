from typing import Protocol
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Contact, CrmActivity, CrmTask, Lead

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
