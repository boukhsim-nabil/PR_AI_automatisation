from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.crm import (
    ActivityCreate,
    ContactCreate,
    LeadCreate,
    LeadStatus,
    LeadStatusChange,
    TaskCreate,
)
from app.services.crm import normalize_email, normalize_phone

pytestmark = pytest.mark.unit


def test_contact_schema_is_strict_and_normalizers_are_deterministic() -> None:
    contact = ContactCreate(
        first_name=" Lina ",
        last_name=" Martin ",
        email="Lina.Martin@Example.com",
        phone="+212 6 12-34-56-78",
    )

    assert contact.first_name == "Lina"
    assert normalize_email(str(contact.email)) == "lina.martin@example.com"
    assert normalize_phone(contact.phone) == "+212612345678"
    with pytest.raises(ValidationError):
        ContactCreate(last_name="Martin", company_id="forbidden")


def test_lead_schema_rejects_invalid_score() -> None:
    with pytest.raises(ValidationError):
        LeadCreate(
            contact_id="11111111-1111-4111-8111-111111111111",
            title="Qualification",
            score=101,
        )


def test_lead_creation_cannot_bypass_assignment_permission() -> None:
    with pytest.raises(ValidationError):
        LeadCreate(
            contact_id="11111111-1111-4111-8111-111111111111",
            title="Qualification",
            assigned_membership_id="22222222-2222-4222-8222-222222222222",
        )


def test_lead_schema_accepts_budget_and_mad_default() -> None:
    lead = LeadCreate(
        contact_id="11111111-1111-4111-8111-111111111111",
        title="Qualification",
        estimated_budget=Decimal("12500.50"),
    )

    assert lead.currency == "MAD"
    assert lead.estimated_budget == Decimal("12500.50")


def test_lost_status_requires_reason() -> None:
    with pytest.raises(ValidationError):
        LeadStatusChange(status=LeadStatus.LOST)
    assert LeadStatusChange(status=LeadStatus.LOST, lost_reason="Budget insuffisant")


def test_system_activity_cannot_be_created_manually() -> None:
    with pytest.raises(ValidationError):
        ActivityCreate(activity_type="system", subject="Forged system event")


def test_task_requires_a_contact_or_lead() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title="Relancer")
