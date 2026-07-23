"""Enable tenant row-level security for memberships.

Revision ID: 20260722_0002
Revises: 20260718_0001
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260722_0002"
down_revision: str | None = "20260718_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_EXPRESSION = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"


def upgrade() -> None:
    # Cluster-level roles deliberately have NOLOGIN. Deployments attach distinct
    # login roles to them and keep credentials outside migrations.
    op.execute(
        """
        DO $roles$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'automation_app') THEN
                CREATE ROLE automation_app
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'automation_migrator') THEN
                CREATE ROLE automation_migrator
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS;
            END IF;

            EXECUTE format('GRANT automation_app TO %I', current_user);
            EXECUTE format('GRANT automation_migrator TO %I', current_user);
        END
        $roles$;
        """
    )

    op.execute("GRANT USAGE ON SCHEMA public TO automation_app")
    op.execute("ALTER TABLE companies OWNER TO automation_migrator")
    op.execute("ALTER TABLE users OWNER TO automation_migrator")
    op.execute("ALTER TABLE memberships OWNER TO automation_migrator")
    op.execute("ALTER TABLE alembic_version OWNER TO automation_migrator")
    op.execute("GRANT SELECT ON companies, users TO automation_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON memberships TO automation_app")
    op.execute("GRANT USAGE, CREATE ON SCHEMA public TO automation_migrator")
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO automation_migrator")
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO automation_migrator")

    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY memberships_tenant_isolation
        ON memberships
        FOR ALL
        TO automation_app
        USING ({TENANT_EXPRESSION})
        WITH CHECK ({TENANT_EXPRESSION})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS memberships_tenant_isolation ON memberships")
    op.execute("ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON memberships FROM automation_app")
    op.execute("REVOKE SELECT ON companies, users FROM automation_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM automation_app")
    # Roles are cluster-level objects and are intentionally retained on downgrade.
