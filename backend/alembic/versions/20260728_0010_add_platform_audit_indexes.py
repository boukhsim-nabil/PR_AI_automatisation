"""Add platform audit query indexes.

Revision ID: 20260728_0010
Revises: 20260728_0009
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0010"
down_revision: str | None = "20260728_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_platform_audit_logs_correlation_id"),
        "platform_audit_logs",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_platform_audit_logs_created_at"),
        "platform_audit_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_audit_logs_created_at"), table_name="platform_audit_logs")
    op.drop_index(op.f("ix_platform_audit_logs_correlation_id"), table_name="platform_audit_logs")
