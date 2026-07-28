"""Add append-only platform audit writer.

Revision ID: 20260728_0012
Revises: 20260728_0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0012"
down_revision: str | None = "20260728_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_write_audit(
            audit_actor_user_id uuid,
            audit_company_id uuid,
            audit_action text,
            audit_result text,
            audit_resource_type text,
            audit_resource_id text,
            audit_correlation_id uuid,
            audit_metadata jsonb
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            event_id uuid;
        BEGIN
            INSERT INTO platform_audit_logs (
                actor_user_id,
                company_id,
                action,
                result,
                resource_type,
                resource_id,
                correlation_id,
                metadata
            )
            VALUES (
                audit_actor_user_id,
                audit_company_id,
                audit_action,
                audit_result,
                audit_resource_type,
                audit_resource_id,
                audit_correlation_id,
                COALESCE(audit_metadata, '{}'::jsonb)
            )
            RETURNING id INTO event_id;
            RETURN event_id;
        END;
        $$;
        """
    )
    op.execute(
        "ALTER FUNCTION platform_write_audit(uuid,uuid,text,text,text,text,uuid,jsonb) "
        "OWNER TO automation_migrator"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "platform_write_audit(uuid,uuid,text,text,text,text,uuid,jsonb) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "platform_write_audit(uuid,uuid,text,text,text,text,uuid,jsonb) "
        "TO automation_platform_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS platform_write_audit(uuid,uuid,text,text,text,text,uuid,jsonb)"
    )
