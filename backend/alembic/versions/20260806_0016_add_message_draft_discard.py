"""Add safe draft discard and simulated inbound permission.

Revision ID: 20260806_0016
Revises: 20260805_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260806_0016"
down_revision: str | None = "20260805_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION_CODE = "inbox.simulate_inbound"


def _install_message_lifecycle(*, allow_discard: bool) -> None:
    discarded_guard = (
        """
            IF OLD.discarded_at IS NOT NULL THEN
                RAISE EXCEPTION 'discarded draft is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.discarded_at IS NOT NULL THEN
                IF OLD.status <> 'draft' OR NEW.status <> 'draft' THEN
                    RAISE EXCEPTION 'only a draft can be discarded'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF (to_jsonb(NEW) - ARRAY['discarded_at', 'updated_at'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['discarded_at', 'updated_at'])
                THEN
                    RAISE EXCEPTION 'draft discard changed message content'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;
        """
        if allow_discard
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION enforce_message_lifecycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            {discarded_guard}
            IF OLD.direction = 'internal'
               AND NEW.status IN ('queued', 'sent', 'delivered', 'read')
            THEN
                RAISE EXCEPTION 'internal message cannot enter customer delivery lifecycle'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.status = 'draft' AND NEW.status = 'draft' THEN
                IF (to_jsonb(NEW) - ARRAY['subject', 'body_text', 'body_html', 'updated_at'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['subject', 'body_text', 'body_html', 'updated_at'])
                THEN
                    RAISE EXCEPTION 'draft update contains immutable fields'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'draft' AND NEW.status = 'queued' THEN
                IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status', 'updated_at'])
                THEN
                    RAISE EXCEPTION 'draft to queued transition changed message content'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status IN ('draft', 'queued') AND NEW.status = 'failed' THEN
                IF (to_jsonb(NEW) - ARRAY['status', 'updated_at', 'error_code', 'error_message'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status', 'updated_at', 'error_code', 'error_message'])
                THEN
                    RAISE EXCEPTION 'failed transition changed immutable message fields'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.status = 'queued' AND NEW.status = 'sent' THEN
                IF NEW.sent_at IS NULL THEN
                    RAISE EXCEPTION 'sent_at is required when message becomes sent'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF (to_jsonb(NEW) - ARRAY['status', 'updated_at', 'sent_at'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status', 'updated_at', 'sent_at'])
                THEN
                    RAISE EXCEPTION 'queued to sent transition changed immutable message fields'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            IF (OLD.status = 'sent' AND NEW.status = 'delivered')
               OR (OLD.status = 'delivered' AND NEW.status = 'read')
            THEN
                IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status', 'updated_at'])
                THEN
                    RAISE EXCEPTION 'delivery transition changed immutable message fields'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'message status is immutable or transition is invalid: % -> %',
                OLD.status, NEW.status
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute("ALTER FUNCTION enforce_message_lifecycle() OWNER TO automation_migrator")
    op.execute("REVOKE ALL ON FUNCTION enforce_message_lifecycle() FROM PUBLIC")


def upgrade() -> None:
    op.add_column("messages", sa.Column("discarded_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_messages_company_conversation_discarded",
        "messages",
        ["company_id", "conversation_id", "discarded_at"],
    )
    _install_message_lifecycle(allow_discard=True)
    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, code, description)
            VALUES (gen_random_uuid(), :code, :description)
            ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
            """
        ).bindparams(
            code=PERMISSION_CODE,
            description="Simuler une reception Inbox hors production.",
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
              FROM roles, permissions
             WHERE roles.code IN ('owner', 'admin')
               AND permissions.code = :code
            ON CONFLICT DO NOTHING
            """
        ).bindparams(code=PERMISSION_CODE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions
             WHERE permission_id = (SELECT id FROM permissions WHERE code = :code)
            """
        ).bindparams(code=PERMISSION_CODE)
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=PERMISSION_CODE)
    )
    _install_message_lifecycle(allow_discard=False)
    op.drop_index("ix_messages_company_conversation_discarded", table_name="messages")
    op.drop_column("messages", "discarded_at")
