"""Create tenant-isolated Inbox conversations and messages.

Revision ID: 20260801_0013
Revises: 20260728_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260801_0013"
down_revision: str | None = "20260728_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_EXPRESSION = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"


def _tenant_resource_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["company_id", column],
        [f"{target}.company_id", f"{target}.id"],
        name=op.f(f"fk_{table}_company_id_{column}_{target}"),
        ondelete="RESTRICT",
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} OWNER TO automation_migrator")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO automation_app")
    op.execute(f"REVOKE DELETE ON {table} FROM automation_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_select ON {table} "
        f"FOR SELECT TO automation_app USING ({TENANT_EXPRESSION})"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_insert ON {table} "
        f"FOR INSERT TO automation_app WITH CHECK ({TENANT_EXPRESSION})"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_update ON {table} "
        f"FOR UPDATE TO automation_app USING ({TENANT_EXPRESSION}) "
        f"WITH CHECK ({TENANT_EXPRESSION})"
    )


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(16), server_default="internal", nullable=False),
        sa.Column("external_conversation_id", sa.String(512), nullable=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("priority", sa.String(16), server_default="normal", nullable=False),
        sa.Column("assigned_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("human_takeover", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("unread_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "channel IN ('internal', 'email', 'whatsapp', 'sms', 'webchat', 'form', 'api')",
            name=op.f("ck_conversations_channel_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'pending', 'waiting_customer', 'waiting_internal', "
            "'resolved', 'closed', 'archived')",
            name=op.f("ck_conversations_status_allowed"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name=op.f("ck_conversations_priority_allowed"),
        ),
        sa.CheckConstraint(
            "unread_count >= 0", name=op.f("ck_conversations_unread_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_conversations_company_id_companies"),
            ondelete="CASCADE",
        ),
        _tenant_resource_fk("conversations", "contact_id", "contacts"),
        _tenant_resource_fk("conversations", "lead_id", "leads"),
        _tenant_resource_fk("conversations", "assigned_membership_id", "memberships"),
        _tenant_resource_fk("conversations", "created_by_membership_id", "memberships"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_conversations_company_id_id")),
    )
    op.create_index(
        "uq_conversations_company_channel_external_not_null",
        "conversations",
        ["company_id", "channel", "external_conversation_id"],
        unique=True,
        postgresql_where=sa.text("external_conversation_id IS NOT NULL"),
    )
    op.create_index(
        "ix_conversations_company_status_last_message",
        "conversations",
        ["company_id", "status", "last_message_at"],
    )
    op.create_index(
        "ix_conversations_company_assigned_status",
        "conversations",
        ["company_id", "assigned_membership_id", "status"],
    )
    op.create_index(
        "ix_conversations_company_priority_status",
        "conversations",
        ["company_id", "priority", "status"],
    )

    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("sender_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sender_contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sender_identifier", sa.String(320), nullable=True),
        sa.Column("content_type", sa.String(24), server_default="text", nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "body_html",
            sa.Text(),
            nullable=True,
            comment="Untrusted HTML; sanitize before any rendering or transformation.",
        ),
        sa.Column("external_message_id", sa.String(512), nullable=True),
        sa.Column("reply_to_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'internal')",
            name=op.f("ck_messages_direction_allowed"),
        ),
        sa.CheckConstraint(
            "sender_type IN ('contact', 'user', 'external', 'system', 'ai_agent')",
            name=op.f("ck_messages_sender_type_allowed"),
        ),
        sa.CheckConstraint(
            "content_type IN ('text', 'html', 'image', 'audio', 'video', 'document', "
            "'location', 'system_event')",
            name=op.f("ck_messages_content_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'queued', 'sent', 'delivered', 'read', 'failed', 'received')",
            name=op.f("ck_messages_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_messages_company_id_companies"),
            ondelete="CASCADE",
        ),
        _tenant_resource_fk("messages", "conversation_id", "conversations"),
        _tenant_resource_fk("messages", "sender_membership_id", "memberships"),
        _tenant_resource_fk("messages", "sender_contact_id", "contacts"),
        sa.ForeignKeyConstraint(
            ["company_id", "conversation_id", "reply_to_message_id"],
            ["messages.company_id", "messages.conversation_id", "messages.id"],
            name=op.f("fk_messages_company_id_conversation_id_reply_to_message_id_messages"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "company_id",
            "conversation_id",
            "id",
            name=op.f("uq_messages_company_id_conversation_id_id"),
        ),
    )
    op.create_index(
        "uq_messages_company_external_not_null",
        "messages",
        ["company_id", "external_message_id"],
        unique=True,
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_messages_company_conversation_created",
        "messages",
        ["company_id", "conversation_id", "created_at"],
    )
    op.create_index(
        "ix_messages_company_status_created",
        "messages",
        ["company_id", "status", "created_at"],
    )

    _enable_rls("conversations")
    _enable_rls("messages")


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
