"""Allow tenant-scoped removal of conversation tag links.

Revision ID: 20260808_0017
Revises: 20260806_0016
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260808_0017"
down_revision: str | None = "20260806_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_EXPRESSION = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"
POLICY_NAME = "conversation_tag_links_tenant_delete"


def upgrade() -> None:
    op.execute("GRANT DELETE ON conversation_tag_links TO automation_app")
    op.execute(
        f"CREATE POLICY {POLICY_NAME} ON conversation_tag_links "
        f"FOR DELETE TO automation_app USING ({TENANT_EXPRESSION})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY {POLICY_NAME} ON conversation_tag_links")
    op.execute("REVOKE DELETE ON conversation_tag_links FROM automation_app")
