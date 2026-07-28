"""Secure platform database access without tenant-table bypass.

Revision ID: 20260728_0011
Revises: 20260728_0010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0011"
down_revision: str | None = "20260728_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_ADMIN_EXPRESSION = """
EXISTS (
    SELECT 1
    FROM platform_user_roles pur
    JOIN platform_roles pr ON pr.id = pur.platform_role_id
    WHERE pur.user_id =
        NULLIF(current_setting('app.current_platform_user_id', true), '')::uuid
      AND pr.code = 'platform_super_admin'
)
"""
INVITATION_TOKEN_EXPRESSION = """
token_hash = NULLIF(current_setting('app.current_invitation_token_hash', true), '')
"""


def upgrade() -> None:
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'automation_platform_app'
            ) THEN
                CREATE ROLE automation_platform_app
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            EXECUTE format('GRANT automation_platform_app TO %I', current_user);
        END
        $roles$;
        """
    )
    for table in (
        "platform_roles",
        "platform_user_roles",
        "platform_sessions",
        "company_invitations",
        "platform_audit_logs",
    ):
        op.execute(f"ALTER TABLE {table} OWNER TO automation_migrator")

    op.execute("GRANT USAGE ON SCHEMA public TO automation_platform_app")
    op.execute("GRANT SELECT ON users, roles TO automation_platform_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON companies TO automation_platform_app")
    op.execute("GRANT SELECT ON platform_roles, platform_user_roles TO automation_platform_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON platform_sessions, company_invitations "
        "TO automation_platform_app"
    )
    op.execute("GRANT SELECT, INSERT ON platform_audit_logs TO automation_platform_app")

    for table in ("company_invitations", "platform_audit_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY company_invitations_platform_select
        ON company_invitations FOR SELECT TO automation_platform_app
        USING (({PLATFORM_ADMIN_EXPRESSION}) OR ({INVITATION_TOKEN_EXPRESSION}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY company_invitations_platform_insert
        ON company_invitations FOR INSERT TO automation_platform_app
        WITH CHECK ({PLATFORM_ADMIN_EXPRESSION})
        """
    )
    op.execute(
        f"""
        CREATE POLICY company_invitations_platform_update
        ON company_invitations FOR UPDATE TO automation_platform_app
        USING (({PLATFORM_ADMIN_EXPRESSION}) OR ({INVITATION_TOKEN_EXPRESSION}))
        WITH CHECK (({PLATFORM_ADMIN_EXPRESSION}) OR ({INVITATION_TOKEN_EXPRESSION}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY platform_audit_logs_platform_select
        ON platform_audit_logs FOR SELECT TO automation_platform_app
        USING ({PLATFORM_ADMIN_EXPRESSION})
        """
    )
    op.execute(
        """
        CREATE POLICY platform_audit_logs_platform_insert
        ON platform_audit_logs FOR INSERT TO automation_platform_app
        WITH CHECK (true)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_revoke_company_sessions(target_company_id uuid)
        RETURNS void
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            UPDATE auth_sessions
            SET revoked_at = now()
            WHERE company_id = target_company_id AND revoked_at IS NULL;
        $$;
        """
    )
    op.execute("ALTER FUNCTION platform_revoke_company_sessions(uuid) OWNER TO automation_migrator")
    op.execute("REVOKE ALL ON FUNCTION platform_revoke_company_sessions(uuid) FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform_revoke_company_sessions(uuid) "
        "TO automation_platform_app"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_create_invited_user(
            invited_email text,
            invited_password_hash text,
            invited_display_name text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            new_user_id uuid;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM company_invitations
                WHERE email_normalized = lower(trim(invited_email))
                  AND token_hash =
                    NULLIF(current_setting('app.current_invitation_token_hash', true), '')
                  AND status = 'pending'
                  AND expires_at > now()
            ) THEN
                RAISE EXCEPTION 'valid invitation context required';
            END IF;
            INSERT INTO users (email, password_hash, display_name, status)
            VALUES (
                lower(trim(invited_email)),
                invited_password_hash,
                invited_display_name,
                'active'
            )
            RETURNING id INTO new_user_id;
            RETURN new_user_id;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_accept_owner_invitation(
            target_invitation_id uuid,
            target_user_id uuid
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
            invitation company_invitations%ROWTYPE;
            owner_role_id uuid;
        BEGIN
            SELECT * INTO invitation
            FROM company_invitations
            WHERE id = target_invitation_id
              AND token_hash =
                NULLIF(current_setting('app.current_invitation_token_hash', true), '')
              AND status = 'pending'
              AND expires_at > now()
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM users
                WHERE id = target_user_id AND email = invitation.email_normalized
            ) THEN
                RETURN false;
            END IF;
            SELECT id INTO owner_role_id FROM roles WHERE code = 'owner';
            IF owner_role_id IS NULL THEN
                RAISE EXCEPTION 'owner role unavailable';
            END IF;
            INSERT INTO memberships (
                company_id, user_id, role_id, status, joined_at
            )
            VALUES (
                invitation.company_id,
                target_user_id,
                owner_role_id,
                'active',
                now()
            )
            ON CONFLICT (company_id, user_id)
            DO UPDATE SET role_id = owner_role_id, status = 'active', joined_at = now();
            UPDATE company_invitations
            SET status = 'accepted', accepted_at = now(), updated_at = now()
            WHERE id = invitation.id;
            UPDATE companies
            SET status = 'onboarding',
                onboarding_status = 'owner_accepted',
                updated_at = now()
            WHERE id = invitation.company_id;
            RETURN true;
        END;
        $$;
        """
    )
    for signature in (
        "platform_create_invited_user(text,text,text)",
        "platform_accept_owner_invitation(uuid,uuid)",
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO automation_migrator")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO automation_platform_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS platform_accept_owner_invitation(uuid,uuid)")
    op.execute("DROP FUNCTION IF EXISTS platform_create_invited_user(text,text,text)")
    op.execute("DROP FUNCTION IF EXISTS platform_revoke_company_sessions(uuid)")
    for table in ("platform_audit_logs", "company_invitations"):
        op.execute(f"DROP POLICY IF EXISTS {table}_platform_select ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_platform_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_platform_update ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT ON platform_audit_logs FROM automation_platform_app")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON platform_sessions, company_invitations "
        "FROM automation_platform_app"
    )
    op.execute("REVOKE SELECT ON platform_roles, platform_user_roles FROM automation_platform_app")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON companies FROM automation_platform_app")
    op.execute("REVOKE SELECT ON users, roles FROM automation_platform_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM automation_platform_app")
