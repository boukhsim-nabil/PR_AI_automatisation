"""Create complementary tenant-isolated Inbox data.

Revision ID: 20260804_0014
Revises: 20260801_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260804_0014"
down_revision: str | None = "20260801_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_EXPRESSION = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"

INBOX_PERMISSIONS = {
    "inbox.read": "Consulter les conversations et messages de l'Inbox.",
    "inbox.create": "Creer des conversations dans l'Inbox.",
    "inbox.reply": "Repondre aux conversations de l'Inbox.",
    "inbox.assign": "Attribuer les conversations de l'Inbox.",
    "inbox.update_status": "Modifier le statut des conversations de l'Inbox.",
    "inbox.manage_priority": "Modifier la priorite des conversations de l'Inbox.",
    "inbox.notes.create": "Creer des notes internes dans l'Inbox.",
    "inbox.tags.manage": "Creer et associer des tags de l'Inbox.",
    "inbox.archive": "Archiver des conversations de l'Inbox.",
    "inbox.takeover": "Prendre le controle humain d'une conversation.",
}

ROLE_INBOX_PERMISSIONS = {
    "owner": tuple(INBOX_PERMISSIONS),
    "admin": tuple(INBOX_PERMISSIONS),
    "manager": tuple(INBOX_PERMISSIONS),
    "support": (
        "inbox.read",
        "inbox.reply",
        "inbox.assign",
        "inbox.update_status",
        "inbox.notes.create",
        "inbox.takeover",
    ),
    "sales": ("inbox.read", "inbox.reply", "inbox.notes.create"),
    "viewer": ("inbox.read",),
}


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


def _seed_inbox_permissions() -> None:
    for code, description in INBOX_PERMISSIONS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO permissions (id, code, description)
                VALUES (gen_random_uuid(), :code, :description)
                ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
                """
            ).bindparams(code=code, description=description)
        )

    for role_code, permission_codes in ROLE_INBOX_PERMISSIONS.items():
        for permission_code in permission_codes:
            op.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT roles.id, permissions.id
                    FROM roles, permissions
                    WHERE roles.code = :role_code AND permissions.code = :permission_code
                    ON CONFLICT DO NOTHING
                    """
                ).bindparams(role_code=role_code, permission_code=permission_code)
            )


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_messages_company_id_id"), "messages", ["company_id", "id"])

    op.create_table(
        "conversation_participants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_type", sa.String(16), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_identifier", sa.String(512), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column(
            "email_normalized",
            sa.String(320),
            sa.Computed("NULLIF(lower(trim(email)), '')", persisted=True),
            nullable=True,
        ),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column(
            "phone_normalized",
            sa.String(40),
            sa.Computed(
                "NULLIF(replace(replace(replace(replace(replace(replace(replace(trim(phone), "
                "' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), '/', ''), '')",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "participant_type IN ('contact', 'user', 'external', 'system', 'ai_agent')",
            name=op.f("ck_conversation_participants_participant_type_allowed"),
        ),
        sa.CheckConstraint(
            "(participant_type = 'contact' AND contact_id IS NOT NULL) OR "
            "(participant_type = 'user' AND membership_id IS NOT NULL) OR "
            "(participant_type = 'external' AND "
            "(external_identifier IS NOT NULL OR email_normalized IS NOT NULL "
            "OR phone_normalized IS NOT NULL)) OR "
            "(participant_type IN ('system', 'ai_agent') AND external_identifier IS NOT NULL)",
            name=op.f("ck_conversation_participants_usable_identity_required"),
        ),
        sa.CheckConstraint(
            "external_identifier IS NULL OR length(trim(external_identifier)) > 0",
            name=op.f("ck_conversation_participants_external_identifier_non_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_conversation_participants_company_id_companies"),
            ondelete="CASCADE",
        ),
        _tenant_resource_fk("conversation_participants", "conversation_id", "conversations"),
        _tenant_resource_fk("conversation_participants", "contact_id", "contacts"),
        _tenant_resource_fk("conversation_participants", "membership_id", "memberships"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_participants")),
    )
    op.create_index(
        "uq_conversation_participants_contact_not_null",
        "conversation_participants",
        ["company_id", "conversation_id", "contact_id"],
        unique=True,
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_participants_membership_not_null",
        "conversation_participants",
        ["company_id", "conversation_id", "membership_id"],
        unique=True,
        postgresql_where=sa.text("membership_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_participants_external_not_null",
        "conversation_participants",
        ["company_id", "conversation_id", "participant_type", "external_identifier"],
        unique=True,
        postgresql_where=sa.text("external_identifier IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_participants_email_not_null",
        "conversation_participants",
        ["company_id", "conversation_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("email_normalized IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_participants_phone_not_null",
        "conversation_participants",
        ["company_id", "conversation_id", "phone_normalized"],
        unique=True,
        postgresql_where=sa.text("phone_normalized IS NOT NULL"),
    )
    op.create_index(
        "ix_conversation_participants_company_conversation",
        "conversation_participants",
        ["company_id", "conversation_id"],
    )

    op.create_table(
        "conversation_notes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(trim(body)) > 0", name=op.f("ck_conversation_notes_body_non_empty")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_conversation_notes_company_id_companies"),
            ondelete="CASCADE",
        ),
        _tenant_resource_fk("conversation_notes", "conversation_id", "conversations"),
        _tenant_resource_fk("conversation_notes", "author_membership_id", "memberships"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_notes")),
    )
    op.create_index(
        "ix_conversation_notes_company_conversation_created",
        "conversation_notes",
        ["company_id", "conversation_id", "created_at"],
    )
    op.create_index(
        "ix_conversation_notes_company_archived",
        "conversation_notes",
        ["company_id", "archived_at"],
    )

    op.create_table(
        "conversation_tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "normalized_name",
            sa.String(120),
            sa.Computed("lower(trim(name))", persisted=True),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name=op.f("ck_conversation_tags_name_non_empty")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_conversation_tags_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_tags")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_conversation_tags_company_id_id")),
        sa.UniqueConstraint(
            "company_id",
            "normalized_name",
            name=op.f("uq_conversation_tags_company_id_normalized_name"),
        ),
    )
    op.create_index(
        "ix_conversation_tags_company_name",
        "conversation_tags",
        ["company_id", "normalized_name"],
    )

    op.create_table(
        "conversation_tag_links",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_conversation_tag_links_company_id_companies"),
            ondelete="CASCADE",
        ),
        _tenant_resource_fk("conversation_tag_links", "conversation_id", "conversations"),
        _tenant_resource_fk("conversation_tag_links", "tag_id", "conversation_tags"),
        _tenant_resource_fk("conversation_tag_links", "created_by_membership_id", "memberships"),
        sa.PrimaryKeyConstraint(
            "company_id",
            "conversation_id",
            "tag_id",
            name=op.f("pk_conversation_tag_links"),
        ),
    )
    op.create_index(
        "ix_conversation_tag_links_company_tag",
        "conversation_tag_links",
        ["company_id", "tag_id"],
    )

    op.create_table(
        "message_attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("scan_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name=op.f("ck_message_attachments_size_bytes_positive")
        ),
        sa.CheckConstraint(
            "scan_status IN ('pending', 'clean', 'infected', 'rejected')",
            name=op.f("ck_message_attachments_scan_status_allowed"),
        ),
        sa.CheckConstraint(
            "length(trim(filename)) > 0",
            name=op.f("ck_message_attachments_filename_non_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(mime_type)) > 0",
            name=op.f("ck_message_attachments_mime_type_non_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(storage_key)) > 0 AND storage_key NOT LIKE '%://%'",
            name=op.f("ck_message_attachments_storage_key_internal"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_message_attachments_company_id_companies"),
            ondelete="CASCADE",
        ),
        _tenant_resource_fk("message_attachments", "message_id", "messages"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_attachments")),
    )
    op.create_index(
        "ix_message_attachments_company_message_created",
        "message_attachments",
        ["company_id", "message_id", "created_at"],
    )
    op.create_index(
        "ix_message_attachments_company_scan_status",
        "message_attachments",
        ["company_id", "scan_status"],
    )

    for table in (
        "conversation_participants",
        "conversation_notes",
        "conversation_tags",
        "conversation_tag_links",
        "message_attachments",
    ):
        _enable_rls(table)

    _seed_inbox_permissions()


def downgrade() -> None:
    permission_codes = ", ".join(f"'{code}'" for code in INBOX_PERMISSIONS)
    op.execute(f"DELETE FROM permissions WHERE code IN ({permission_codes})")
    op.drop_table("message_attachments")
    op.drop_table("conversation_tag_links")
    op.drop_table("conversation_tags")
    op.drop_table("conversation_notes")
    op.drop_table("conversation_participants")
    op.drop_constraint(op.f("uq_messages_company_id_id"), "messages", type_="unique")
