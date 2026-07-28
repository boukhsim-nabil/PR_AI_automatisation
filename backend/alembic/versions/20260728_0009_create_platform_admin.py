"""Create platform administration and owner invitations.

Revision ID: 20260728_0009
Revises: 20260723_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260728_0009"
down_revision: str | None = "20260723_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("legal_name", sa.String(255)))
    op.add_column("companies", sa.Column("slug", sa.String(160)))
    op.add_column(
        "companies", sa.Column("country", sa.String(2), server_default="MA", nullable=False)
    )
    op.alter_column("companies", "default_language", new_column_name="language")
    op.add_column(
        "companies", sa.Column("currency", sa.String(3), server_default="MAD", nullable=False)
    )
    op.add_column(
        "companies",
        sa.Column("onboarding_status", sa.String(32), server_default="not_started", nullable=False),
    )
    op.add_column(
        "companies", sa.Column("plan_code", sa.String(64), server_default="trial", nullable=False)
    )
    op.add_column("companies", sa.Column("trial_ends_at", sa.DateTime(timezone=True)))
    op.add_column(
        "companies",
        sa.Column(
            "created_by_platform_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("companies", sa.Column("suspended_at", sa.DateTime(timezone=True)))
    op.add_column("companies", sa.Column("suspension_reason", sa.String(1000)))
    op.execute(
        "UPDATE companies SET slug = lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g')) "
        "|| '-' || substr(id::text, 1, 8) WHERE slug IS NULL"
    )
    op.alter_column("companies", "slug", nullable=False)
    op.create_unique_constraint(op.f("uq_companies_slug"), "companies", ["slug"])
    op.alter_column("companies", "timezone", server_default="Africa/Casablanca")
    op.alter_column("companies", "status", server_default="pending")
    op.create_check_constraint(
        op.f("ck_companies_status_allowed"),
        "companies",
        "status IN ('pending','onboarding','active','suspended','closed')",
    )

    op.create_table(
        "platform_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_platform_roles_code")),
    )
    op.create_table(
        "platform_user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["platform_role_id"], ["platform_roles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "platform_role_id", name=op.f("pk_platform_user_roles")),
    )
    op.create_table(
        "platform_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("mfa_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_sessions")),
    )
    op.create_index(op.f("ix_platform_sessions_user_id"), "platform_sessions", ["user_id"])
    op.create_table(
        "company_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column(
            "invitation_type", sa.String(32), server_default="owner_invitation", nullable=False
        ),
        sa.Column("target_role_code", sa.String(64), server_default="owner", nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("invited_by_platform_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_platform_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_company_invitations_token_hash")),
        sa.CheckConstraint(
            "status IN ('pending','accepted','expired','revoked')",
            name=op.f("ck_company_invitations_status_allowed"),
        ),
        sa.CheckConstraint(
            "invitation_type = 'owner_invitation'",
            name=op.f("ck_company_invitations_type_owner_only"),
        ),
        sa.CheckConstraint(
            "target_role_code = 'owner'", name=op.f("ck_company_invitations_target_owner_only")
        ),
    )
    op.create_index(
        "uq_company_invitations_active_owner",
        "company_invitations",
        ["company_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "platform_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("company_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_audit_logs")),
    )
    op.create_index(
        op.f("ix_platform_audit_logs_company_id"), "platform_audit_logs", ["company_id"]
    )
    op.create_index(op.f("ix_platform_audit_logs_action"), "platform_audit_logs", ["action"])
    op.execute(
        "INSERT INTO platform_roles (code,name) VALUES "
        "('platform_super_admin','Platform Super Administrator') ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("platform_audit_logs")
    op.drop_table("company_invitations")
    op.drop_table("platform_sessions")
    op.drop_table("platform_user_roles")
    op.drop_table("platform_roles")
    op.drop_constraint(op.f("ck_companies_status_allowed"), "companies", type_="check")
    op.drop_constraint(op.f("uq_companies_slug"), "companies", type_="unique")
    for column in (
        "suspension_reason",
        "suspended_at",
        "created_by_platform_user_id",
        "trial_ends_at",
        "plan_code",
        "onboarding_status",
        "currency",
        "country",
        "slug",
        "legal_name",
    ):
        op.drop_column("companies", column)
    op.alter_column("companies", "language", new_column_name="default_language")
    op.alter_column("companies", "timezone", server_default="UTC")
    op.alter_column("companies", "status", server_default="active")
