"""Create append-only tenant audit logs.

Revision ID: 20260722_0005
Revises: 20260722_0004
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260722_0005"
down_revision: str | None = "20260722_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["memberships.id"],
            name=op.f("fk_audit_logs_actor_membership_id_memberships"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_audit_logs_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    for column in (
        "action",
        "company_id",
        "correlation_id",
        "created_at",
        "resource_type",
        "result",
    ):
        op.create_index(op.f(f"ix_audit_logs_{column}"), "audit_logs", [column])
    op.execute("ALTER TABLE audit_logs OWNER TO automation_migrator")
    op.execute("GRANT SELECT, INSERT ON audit_logs TO automation_app")
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM automation_app")
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    tenant = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"
    op.execute(
        "CREATE POLICY audit_logs_tenant_select ON audit_logs "
        f"FOR SELECT TO automation_app USING ({tenant})"
    )
    op.execute(
        "CREATE POLICY audit_logs_tenant_insert ON audit_logs "
        f"FOR INSERT TO automation_app WITH CHECK ({tenant})"
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
