"""Enforce persisted Inbox lifecycle invariants.

Revision ID: 20260805_0015
Revises: 20260804_0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260805_0015"
down_revision: str | None = "20260804_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION require_writable_conversation() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            conversation_status text;
            conversation_archived_at timestamptz;
        BEGIN
            IF NULLIF(current_setting('app.current_company_id', true), '') IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT status, archived_at
              INTO conversation_status, conversation_archived_at
              FROM public.conversations
             WHERE company_id = NEW.company_id
               AND id = NEW.conversation_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'conversation does not exist in the current tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF conversation_status IN ('closed', 'archived')
               OR conversation_archived_at IS NOT NULL
            THEN
                RAISE EXCEPTION 'closed or archived conversation cannot accept child changes'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("ALTER FUNCTION require_writable_conversation() OWNER TO automation_migrator")
    op.execute("REVOKE ALL ON FUNCTION require_writable_conversation() FROM PUBLIC")

    for table in (
        "messages",
        "conversation_participants",
        "conversation_notes",
        "conversation_tag_links",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_require_writable_conversation
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION require_writable_conversation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION require_writable_attachment_conversation() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            conversation_status text;
            conversation_archived_at timestamptz;
        BEGIN
            IF NULLIF(current_setting('app.current_company_id', true), '') IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT conversations.status, conversations.archived_at
              INTO conversation_status, conversation_archived_at
              FROM public.messages
              JOIN public.conversations
                ON conversations.company_id = messages.company_id
               AND conversations.id = messages.conversation_id
             WHERE messages.company_id = NEW.company_id
               AND messages.id = NEW.message_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'message does not exist in the current tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF conversation_status IN ('closed', 'archived')
               OR conversation_archived_at IS NOT NULL
            THEN
                RAISE EXCEPTION 'closed or archived conversation cannot accept attachment changes'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION require_writable_attachment_conversation() OWNER TO automation_migrator"
    )
    op.execute("REVOKE ALL ON FUNCTION require_writable_attachment_conversation() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER trg_message_attachments_require_writable_conversation
        BEFORE INSERT OR UPDATE ON message_attachments
        FOR EACH ROW EXECUTE FUNCTION require_writable_attachment_conversation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_conversation_lifecycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF OLD.status = 'archived' OR OLD.archived_at IS NOT NULL THEN
                RAISE EXCEPTION 'archived conversation is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF OLD.status = 'closed' THEN
                IF NEW.status IN ('closed', 'archived') THEN
                    RAISE EXCEPTION 'closed conversation requires explicit reopen'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF (to_jsonb(NEW) - ARRAY['status', 'closed_at', 'resolved_at', 'updated_at'])
                    IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY['status', 'closed_at', 'resolved_at', 'updated_at'])
                THEN
                    RAISE EXCEPTION 'closed conversation may only be reopened before modification'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_conversations_enforce_lifecycle
        BEFORE UPDATE ON conversations
        FOR EACH ROW EXECUTE FUNCTION enforce_conversation_lifecycle()
        """
    )
    op.execute("ALTER FUNCTION enforce_conversation_lifecycle() OWNER TO automation_migrator")
    op.execute("REVOKE ALL ON FUNCTION enforce_conversation_lifecycle() FROM PUBLIC")

    op.execute(
        """
        CREATE FUNCTION enforce_message_lifecycle() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
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
    op.execute(
        """
        CREATE TRIGGER trg_messages_enforce_lifecycle
        BEFORE UPDATE ON messages
        FOR EACH ROW EXECUTE FUNCTION enforce_message_lifecycle()
        """
    )
    op.execute("ALTER FUNCTION enforce_message_lifecycle() OWNER TO automation_migrator")
    op.execute("REVOKE ALL ON FUNCTION enforce_message_lifecycle() FROM PUBLIC")


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_message_attachments_require_writable_conversation ON message_attachments"
    )
    op.execute("DROP FUNCTION require_writable_attachment_conversation()")
    for table in (
        "conversation_tag_links",
        "conversation_notes",
        "conversation_participants",
        "messages",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_require_writable_conversation ON {table}")
    op.execute("DROP FUNCTION require_writable_conversation()")
    op.execute("DROP TRIGGER trg_messages_enforce_lifecycle ON messages")
    op.execute("DROP FUNCTION enforce_message_lifecycle()")
    op.execute("DROP TRIGGER trg_conversations_enforce_lifecycle ON conversations")
    op.execute("DROP FUNCTION enforce_conversation_lifecycle()")
