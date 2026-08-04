from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Permission, Role, RolePermission

ROLE_DEFINITIONS = {
    "owner": ("Owner", "Accès complet et responsabilité de l’entreprise."),
    "admin": ("Admin", "Administration opérationnelle complète."),
    "manager": ("Manager", "Pilotage des équipes, du CRM et des workflows."),
    "sales": ("Sales", "Gestion commerciale et suivi des prospects."),
    "support": ("Support", "Consultation et mise à jour pour le support client."),
    "viewer": ("Viewer", "Consultation en lecture seule."),
}

PERMISSION_DEFINITIONS = {
    "company.read": "Consulter les informations de l’entreprise.",
    "company.manage": "Modifier les paramètres de l’entreprise.",
    "members.read": "Consulter les membres de l’entreprise.",
    "members.manage": "Inviter, modifier ou retirer des membres.",
    "crm.read": "Consulter les données CRM.",
    "crm.create": "Créer des données CRM.",
    "crm.update": "Modifier des données CRM.",
    "crm.delete": "Supprimer des données CRM.",
    "crm.archive": "Archiver des contacts et prospects CRM.",
    "crm.assign": "Attribuer des prospects à des membres actifs.",
    "crm.activities.create": "Créer des activités CRM utilisateur.",
    "crm.tasks.manage": "Créer et gérer des tâches CRM.",
    "workflows.read": "Consulter les workflows.",
    "workflows.manage": "Créer et modifier les workflows.",
    "audit.read": "Consulter le journal d’audit.",
    "inbox.read": "Consulter les conversations et messages de l’Inbox.",
    "inbox.create": "Créer des conversations dans l’Inbox.",
    "inbox.reply": "Répondre aux conversations de l’Inbox.",
    "inbox.assign": "Attribuer les conversations de l’Inbox.",
    "inbox.update_status": "Modifier le statut des conversations de l’Inbox.",
    "inbox.manage_priority": "Modifier la priorité des conversations de l’Inbox.",
    "inbox.notes.create": "Créer des notes internes dans l’Inbox.",
    "inbox.tags.manage": "Créer et associer des tags de l’Inbox.",
    "inbox.archive": "Archiver des conversations de l’Inbox.",
    "inbox.takeover": "Prendre le contrôle humain d’une conversation.",
}

ALL_PERMISSIONS = frozenset(PERMISSION_DEFINITIONS)
ROLE_PERMISSION_CODES = {
    "owner": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS,
    "manager": frozenset(
        {
            "company.read",
            "members.read",
            "crm.read",
            "crm.create",
            "crm.update",
            "crm.delete",
            "crm.archive",
            "crm.assign",
            "crm.activities.create",
            "crm.tasks.manage",
            "workflows.read",
            "workflows.manage",
            "audit.read",
            "inbox.read",
            "inbox.create",
            "inbox.reply",
            "inbox.assign",
            "inbox.update_status",
            "inbox.manage_priority",
            "inbox.notes.create",
            "inbox.tags.manage",
            "inbox.archive",
            "inbox.takeover",
        }
    ),
    "sales": frozenset(
        {
            "company.read",
            "members.read",
            "crm.read",
            "crm.create",
            "crm.update",
            "crm.archive",
            "crm.assign",
            "crm.activities.create",
            "crm.tasks.manage",
            "workflows.read",
            "inbox.read",
            "inbox.reply",
            "inbox.notes.create",
        }
    ),
    "support": frozenset(
        {
            "company.read",
            "members.read",
            "crm.read",
            "crm.update",
            "crm.activities.create",
            "crm.tasks.manage",
            "workflows.read",
            "inbox.read",
            "inbox.reply",
            "inbox.assign",
            "inbox.update_status",
            "inbox.notes.create",
            "inbox.takeover",
        }
    ),
    "viewer": frozenset(
        {"company.read", "members.read", "crm.read", "workflows.read", "inbox.read"}
    ),
}


def seed_rbac(session: Session) -> dict[str, Role]:
    """Create or synchronize system roles, permissions and their mappings."""
    roles = {
        role.code: role
        for role in session.scalars(select(Role).where(Role.code.in_(ROLE_DEFINITIONS)))
    }
    for code, (name, description) in ROLE_DEFINITIONS.items():
        role = roles.get(code)
        if role is None:
            role = Role(code=code, name=name, description=description, is_system=True)
            session.add(role)
            roles[code] = role
        else:
            role.name = name
            role.description = description
            role.is_system = True

    permissions = {
        permission.code: permission
        for permission in session.scalars(
            select(Permission).where(Permission.code.in_(PERMISSION_DEFINITIONS))
        )
    }
    for code, description in PERMISSION_DEFINITIONS.items():
        permission = permissions.get(code)
        if permission is None:
            permission = Permission(code=code, description=description)
            session.add(permission)
            permissions[code] = permission
        else:
            permission.description = description

    session.flush()

    role_ids = [role.id for role in roles.values()]
    existing_links = {
        (link.role_id, link.permission_id): link
        for link in session.scalars(
            select(RolePermission).where(RolePermission.role_id.in_(role_ids))
        )
    }
    desired_pairs = {
        (roles[role_code].id, permissions[permission_code].id)
        for role_code, permission_codes in ROLE_PERMISSION_CODES.items()
        for permission_code in permission_codes
    }

    for pair, link in existing_links.items():
        if pair not in desired_pairs:
            session.delete(link)
    for role_id, permission_id in desired_pairs - set(existing_links):
        session.add(RolePermission(role_id=role_id, permission_id=permission_id))

    session.flush()
    return roles
