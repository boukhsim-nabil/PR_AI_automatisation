"""Create tenant-scoped CRM contacts and leads.

Revision ID: 20260722_0006
Revises: 20260722_0005
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260722_0006"
down_revision: str | None = "20260722_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
    ]


def _person_columns() -> list[sa.Column]:
    return [
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("organization", sa.String(length=255), nullable=True),
        sa.Column("responsible_id", postgresql.UUID(as_uuid=True), nullable=True),
    ]


def _tracking_columns() -> list[sa.Column]:
    return [
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _tenant_foreign_keys(table: str) -> list[sa.Constraint]:
    return [
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f(f"fk_{table}_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f(f"fk_{table}_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "responsible_id"],
            ["memberships.company_id", "memberships.id"],
            name=op.f(f"fk_{table}_company_id_responsible_id_memberships"),
            ondelete="RESTRICT",
        ),
    ]


def _create_indexes(table: str, extra: tuple[str, ...] = ()) -> None:
    for column in ("archived_at", "company_id", "created_by", *extra):
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _enable_rls(table: str) -> None:
    tenant = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"
    op.execute(f"ALTER TABLE {table} OWNER TO automation_migrator")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO automation_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"FOR ALL TO automation_app USING ({tenant}) WITH CHECK ({tenant})"
    )


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_memberships_company_id_id"),
        "memberships",
        ["company_id", "id"],
    )
    op.create_table(
        "contacts",
        *_identity_columns(),
        *_person_columns(),
        *_tracking_columns(),
        *_tenant_foreign_keys("contacts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
        sa.UniqueConstraint(
            "company_id",
            "email_normalized",
            name=op.f("uq_contacts_company_id_email_normalized"),
        ),
    )
    _create_indexes("contacts")
    op.create_index(
        "ix_contacts_company_id_archived_at",
        "contacts",
        ["company_id", "archived_at"],
    )

    op.create_table(
        "leads",
        *_identity_columns(),
        *_person_columns(),
        sa.Column("need", sa.Text(), nullable=True),
        sa.Column("budget", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("urgency", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("next_action", sa.String(length=500), nullable=True),
        *_tracking_columns(),
        sa.CheckConstraint(
            "budget IS NULL OR budget >= 0",
            name=op.f("ck_leads_budget_non_negative"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name=op.f("ck_leads_priority_allowed"),
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name=op.f("ck_leads_score_range"),
        ),
        sa.CheckConstraint(
            "status IN ('new', 'to_qualify', 'qualified', 'appointment_scheduled', "
            "'proposal_sent', 'won', 'lost', 'archived')",
            name=op.f("ck_leads_status_allowed"),
        ),
        sa.CheckConstraint(
            "urgency IS NULL OR urgency IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_leads_urgency_allowed"),
        ),
        *_tenant_foreign_keys("leads"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
        sa.UniqueConstraint(
            "company_id",
            "email_normalized",
            name=op.f("uq_leads_company_id_email_normalized"),
        ),
    )
    _create_indexes("leads", ("source",))
    for column in ("archived_at", "priority", "status"):
        op.create_index(
            f"ix_leads_company_id_{column}",
            "leads",
            ["company_id", column],
        )

    _enable_rls("contacts")
    _enable_rls("leads")


def downgrade() -> None:
    op.drop_table("leads")
    op.drop_table("contacts")
    op.drop_constraint(op.f("uq_memberships_company_id_id"), "memberships", type_="unique")
