"""Expand CRM into contacts, leads, activities, tasks and M2 permissions.

Revision ID: 20260723_0007
Revises: 20260722_0006
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260723_0007"
down_revision: str | None = "20260722_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_EXPRESSION = "company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid"


def _enable_mutable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} OWNER TO automation_migrator")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO automation_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"FOR ALL TO automation_app USING ({TENANT_EXPRESSION}) "
        f"WITH CHECK ({TENANT_EXPRESSION})"
    )


def _membership_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["company_id", column],
        ["memberships.company_id", "memberships.id"],
        name=op.f(f"fk_{table}_company_id_{column}_memberships"),
        ondelete="RESTRICT",
    )


def _resource_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["company_id", column],
        [f"{target}.company_id", f"{target}.id"],
        name=op.f(f"fk_{table}_company_id_{column}_{target}"),
        ondelete="RESTRICT",
    )


def _upgrade_contacts() -> None:
    op.add_column("contacts", sa.Column("phone_normalized", sa.String(40), nullable=True))
    op.add_column("contacts", sa.Column("job_title", sa.String(160), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("language", sa.String(10), server_default="fr", nullable=False),
    )
    op.add_column(
        "contacts",
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
    )
    op.add_column(
        "contacts",
        sa.Column("consent_email", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "contacts",
        sa.Column("consent_whatsapp", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "contacts",
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("contacts", "organization", new_column_name="organization_name")
    op.execute(
        """
        UPDATE contacts AS contact
        SET created_by_membership_id = (
                SELECT memberships.id
                FROM memberships
                WHERE memberships.company_id = contact.company_id
                  AND memberships.user_id = contact.created_by
                ORDER BY (memberships.status = 'active') DESC, memberships.created_at
                LIMIT 1
            ),
            phone_normalized = NULLIF(regexp_replace(contact.phone, '[^0-9+]', '', 'g'), ''),
            status = CASE WHEN contact.archived_at IS NULL THEN 'active' ELSE 'archived' END
        """
    )
    op.alter_column("contacts", "created_by_membership_id", nullable=False)
    op.drop_constraint(
        op.f("fk_contacts_company_id_responsible_id_memberships"),
        "contacts",
        type_="foreignkey",
    )
    op.drop_constraint(op.f("fk_contacts_created_by_users"), "contacts", type_="foreignkey")
    op.drop_index(op.f("ix_contacts_created_by"), table_name="contacts")
    op.drop_column("contacts", "responsible_id")
    op.drop_column("contacts", "created_by")
    op.create_unique_constraint(op.f("uq_contacts_company_id_id"), "contacts", ["company_id", "id"])
    op.create_foreign_key(
        op.f("fk_contacts_company_id_created_by_membership_id_memberships"),
        "contacts",
        "memberships",
        ["company_id", "created_by_membership_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_contacts_status_allowed"),
        "contacts",
        "status IN ('active', 'inactive', 'archived')",
    )
    op.create_index(op.f("ix_contacts_phone_normalized"), "contacts", ["phone_normalized"])
    op.create_index(
        op.f("ix_contacts_created_by_membership_id"),
        "contacts",
        ["created_by_membership_id"],
    )
    op.create_index("ix_contacts_company_id_status", "contacts", ["company_id", "status"])


def _upgrade_leads() -> None:
    op.add_column("leads", sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("leads", sa.Column("title", sa.String(255), nullable=True))
    op.add_column(
        "leads",
        sa.Column("currency", sa.String(3), server_default="MAD", nullable=False),
    )
    op.add_column("leads", sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("lost_reason", sa.String(1000), nullable=True))
    op.add_column(
        "leads",
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("leads", "need", new_column_name="need_description")
    op.alter_column("leads", "budget", new_column_name="estimated_budget")
    op.alter_column("leads", "responsible_id", new_column_name="assigned_membership_id")

    op.execute(
        """
        CREATE TEMPORARY TABLE crm_lead_contact_map (
            lead_id uuid PRIMARY KEY,
            contact_id uuid NOT NULL,
            creator_membership_id uuid NOT NULL
        ) ON COMMIT DROP
        """
    )
    op.execute(
        """
        INSERT INTO crm_lead_contact_map (lead_id, contact_id, creator_membership_id)
        SELECT lead.id,
               COALESCE(existing_contact.id, gen_random_uuid()),
               creator_membership.id
        FROM leads AS lead
        CROSS JOIN LATERAL (
            SELECT memberships.id
            FROM memberships
            WHERE memberships.company_id = lead.company_id
              AND memberships.user_id = lead.created_by
            ORDER BY (memberships.status = 'active') DESC, memberships.created_at
            LIMIT 1
        ) AS creator_membership
        LEFT JOIN LATERAL (
            SELECT contacts.id
            FROM contacts
            WHERE contacts.company_id = lead.company_id
              AND lead.email_normalized IS NOT NULL
              AND contacts.email_normalized = lead.email_normalized
            LIMIT 1
        ) AS existing_contact ON true
        """
    )
    op.execute(
        """
        INSERT INTO contacts (
            id, company_id, first_name, last_name, email, email_normalized,
            phone, phone_normalized, organization_name, language, status,
            consent_email, consent_whatsapp, created_by_membership_id,
            archived_at, created_at, updated_at
        )
        SELECT mapping.contact_id, lead.company_id, lead.first_name, lead.last_name,
               lead.email, lead.email_normalized, lead.phone,
               NULLIF(regexp_replace(lead.phone, '[^0-9+]', '', 'g'), ''),
               lead.organization, 'fr',
               CASE WHEN lead.archived_at IS NULL THEN 'active' ELSE 'archived' END,
               false, false, mapping.creator_membership_id,
               lead.archived_at, lead.created_at, lead.updated_at
        FROM leads AS lead
        JOIN crm_lead_contact_map AS mapping ON mapping.lead_id = lead.id
        WHERE NOT EXISTS (SELECT 1 FROM contacts WHERE contacts.id = mapping.contact_id)
        """
    )
    op.execute(
        """
        UPDATE leads AS lead
        SET contact_id = mapping.contact_id,
            created_by_membership_id = mapping.creator_membership_id,
            title = COALESCE(
                NULLIF(trim(concat_ws(' ', lead.first_name, lead.last_name)), ''),
                lead.organization,
                'Opportunité CRM'
            ),
            urgency = COALESCE(lead.urgency, 'medium'),
            source = CASE
                WHEN lead.source IN ('manual', 'form', 'email', 'whatsapp', 'referral', 'api')
                THEN lead.source ELSE 'manual' END,
            priority = CASE
                WHEN lead.priority = 'normal' THEN 'medium'
                WHEN lead.priority = 'urgent' THEN 'high'
                ELSE lead.priority END,
            lost_reason = CASE WHEN lead.status = 'lost' THEN 'Motif non renseigné (migration)' END
        FROM crm_lead_contact_map AS mapping
        WHERE mapping.lead_id = lead.id
        """
    )

    for constraint in (
        "fk_leads_company_id_responsible_id_memberships",
        "fk_leads_created_by_users",
        "uq_leads_company_id_email_normalized",
        "ck_leads_budget_non_negative",
        "ck_leads_priority_allowed",
        "ck_leads_score_range",
        "ck_leads_status_allowed",
        "ck_leads_urgency_allowed",
    ):
        constraint_type = "foreignkey" if constraint.startswith("fk_") else None
        if constraint.startswith("uq_"):
            constraint_type = "unique"
        op.drop_constraint(op.f(constraint), "leads", type_=constraint_type)

    op.drop_index(op.f("ix_leads_created_by"), table_name="leads")
    op.drop_index(op.f("ix_leads_source"), table_name="leads")
    for column in (
        "created_by",
        "last_name",
        "first_name",
        "email",
        "email_normalized",
        "phone",
        "organization",
    ):
        op.drop_column("leads", column)

    op.alter_column("leads", "contact_id", nullable=False)
    op.alter_column("leads", "title", nullable=False)
    op.alter_column("leads", "created_by_membership_id", nullable=False)
    op.alter_column("leads", "urgency", nullable=False, server_default="medium")
    op.alter_column(
        "leads", "source", existing_type=sa.String(120), type_=sa.String(16), nullable=False
    )
    op.alter_column("leads", "priority", server_default="medium")
    op.create_unique_constraint(op.f("uq_leads_company_id_id"), "leads", ["company_id", "id"])
    op.create_foreign_key(
        op.f("fk_leads_company_id_contact_id_contacts"),
        "leads",
        "contacts",
        ["company_id", "contact_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    for column in ("assigned_membership_id", "created_by_membership_id"):
        op.create_foreign_key(
            op.f(f"fk_leads_company_id_{column}_memberships"),
            "leads",
            "memberships",
            ["company_id", column],
            ["company_id", "id"],
            ondelete="RESTRICT",
        )
    checks = {
        "estimated_budget_non_negative": "estimated_budget IS NULL OR estimated_budget >= 0",
        "priority_allowed": "priority IN ('low', 'medium', 'high')",
        "score_range": "score >= 0 AND score <= 100",
        "status_allowed": (
            "status IN ('new', 'to_qualify', 'qualified', 'appointment_scheduled', "
            "'proposal_sent', 'won', 'lost', 'archived')"
        ),
        "urgency_allowed": "urgency IN ('low', 'medium', 'high', 'critical')",
        "source_allowed": ("source IN ('manual', 'form', 'email', 'whatsapp', 'referral', 'api')"),
        "lost_reason_required": (
            "status <> 'lost' OR (lost_reason IS NOT NULL AND length(trim(lost_reason)) > 0)"
        ),
    }
    for name, expression in checks.items():
        op.create_check_constraint(op.f(f"ck_leads_{name}"), "leads", expression)
    for column in ("contact_id", "created_by_membership_id", "next_action_at"):
        op.create_index(op.f(f"ix_leads_{column}"), "leads", [column])
    for name, columns in (
        ("ix_leads_company_id_source", ["company_id", "source"]),
        ("ix_leads_company_id_assigned", ["company_id", "assigned_membership_id"]),
        ("ix_leads_company_id_created_at", ["company_id", "created_at"]),
    ):
        op.create_index(name, "leads", columns)


def _create_activity_and_task_tables() -> None:
    op.create_table(
        "crm_activities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activity_type", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "activity_type IN ('note', 'call', 'email', 'whatsapp', 'meeting', 'task', "
            "'status_change', 'assignment', 'system')",
            name=op.f("ck_crm_activities_activity_type_allowed"),
        ),
        sa.CheckConstraint(
            "contact_id IS NOT NULL OR lead_id IS NOT NULL",
            name=op.f("ck_crm_activities_resource_required"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_crm_activities_company_id_companies"),
            ondelete="CASCADE",
        ),
        _resource_fk("crm_activities", "contact_id", "contacts"),
        _resource_fk("crm_activities", "lead_id", "leads"),
        _membership_fk("crm_activities", "actor_membership_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_activities")),
    )
    for column in (
        "activity_type",
        "actor_membership_id",
        "company_id",
        "contact_id",
        "created_at",
        "lead_id",
    ):
        op.create_index(op.f(f"ix_crm_activities_{column}"), "crm_activities", [column])
    op.create_index(
        "ix_crm_activities_company_lead_occurred",
        "crm_activities",
        ["company_id", "lead_id", "occurred_at"],
    )
    op.create_index(
        "ix_crm_activities_company_contact_occurred",
        "crm_activities",
        ["company_id", "contact_id", "occurred_at"],
    )
    op.execute("ALTER TABLE crm_activities OWNER TO automation_migrator")
    op.execute("GRANT SELECT, INSERT ON crm_activities TO automation_app")
    op.execute("REVOKE UPDATE, DELETE ON crm_activities FROM automation_app")
    op.execute("ALTER TABLE crm_activities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE crm_activities FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY crm_activities_tenant_select ON crm_activities "
        f"FOR SELECT TO automation_app USING ({TENANT_EXPRESSION})"
    )
    op.execute(
        "CREATE POLICY crm_activities_tenant_insert ON crm_activities "
        f"FOR INSERT TO automation_app WITH CHECK ({TENANT_EXPRESSION})"
    )

    op.create_table(
        "crm_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(16), server_default="medium", nullable=False),
        sa.Column("status", sa.String(16), server_default="todo", nullable=False),
        sa.Column("assigned_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name=op.f("ck_crm_tasks_priority_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'completed', 'cancelled')",
            name=op.f("ck_crm_tasks_status_allowed"),
        ),
        sa.CheckConstraint(
            "lead_id IS NOT NULL OR contact_id IS NOT NULL",
            name=op.f("ck_crm_tasks_resource_required"),
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name=op.f("ck_crm_tasks_completed_at_required"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_crm_tasks_company_id_companies"),
            ondelete="CASCADE",
        ),
        _resource_fk("crm_tasks", "contact_id", "contacts"),
        _resource_fk("crm_tasks", "lead_id", "leads"),
        _membership_fk("crm_tasks", "assigned_membership_id"),
        _membership_fk("crm_tasks", "created_by_membership_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_tasks")),
    )
    for column in (
        "company_id",
        "contact_id",
        "created_by_membership_id",
        "due_at",
        "lead_id",
    ):
        op.create_index(op.f(f"ix_crm_tasks_{column}"), "crm_tasks", [column])
    op.create_index(
        "ix_crm_tasks_company_status_due",
        "crm_tasks",
        ["company_id", "status", "due_at"],
    )
    op.create_index(
        "ix_crm_tasks_company_assigned_status",
        "crm_tasks",
        ["company_id", "assigned_membership_id", "status"],
    )
    op.create_index("ix_crm_tasks_company_lead", "crm_tasks", ["company_id", "lead_id"])
    _enable_mutable_rls("crm_tasks")


def _seed_permissions() -> None:
    permissions = {
        "crm.archive": "Archiver des contacts et prospects CRM.",
        "crm.assign": "Attribuer des prospects à des membres actifs.",
        "crm.activities.create": "Créer des activités CRM utilisateur.",
        "crm.tasks.manage": "Créer et gérer des tâches CRM.",
    }
    for code, description in permissions.items():
        op.execute(
            sa.text(
                """
                INSERT INTO permissions (id, code, description)
                VALUES (gen_random_uuid(), :code, :description)
                ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
                """
            ).bindparams(code=code, description=description)
        )
    role_permissions = {
        "owner": tuple(permissions),
        "admin": tuple(permissions),
        "manager": tuple(permissions),
        "sales": tuple(permissions),
        "support": ("crm.activities.create", "crm.tasks.manage"),
    }
    for role_code, codes in role_permissions.items():
        for permission_code in codes:
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
    _upgrade_contacts()
    _upgrade_leads()
    _create_activity_and_task_tables()
    _seed_permissions()


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade past CRM M2 is intentionally blocked because "
        "contact/lead normalization is lossy."
    )
