"""Correct the CRM lead priority constraint conversion order.

Revision ID: 20260723_0008
Revises: 20260723_0007
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0008"
down_revision: str | None = "20260723_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_leads_priority_allowed"),
        "leads",
        type_="check",
    )
    op.execute("UPDATE leads SET priority = 'medium' WHERE priority = 'normal'")
    op.create_check_constraint(
        op.f("ck_leads_priority_allowed"),
        "leads",
        "priority IN ('low', 'medium', 'high')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_leads_priority_allowed"),
        "leads",
        type_="check",
    )
    op.execute("UPDATE leads SET priority = 'normal' WHERE priority = 'medium'")
    op.create_check_constraint(
        op.f("ck_leads_priority_allowed"),
        "leads",
        "priority IN ('low', 'normal', 'high', 'urgent')",
    )
