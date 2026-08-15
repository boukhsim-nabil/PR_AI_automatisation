# Séparation plateforme et tenant

| Domaine | Identité | Rôle PostgreSQL | Accès |
|---|---|---|---|
| Tenant | JWT avec `company_id` et `membership_id` | `automation_app` | tables du tenant via `SET LOCAL app.current_company_id` et RLS |
| Plateforme | JWT `platform_access` et `PlatformSession` | `automation_platform_app` | companies et tables plateforme uniquement |
| Migration | opérateur de déploiement | `automation_migrator` | DDL, `BYPASSRLS`, jamais utilisé par l'API |

`automation_platform_app` est `NOLOGIN`, `NOINHERIT` et `NOBYPASSRLS`. Il ne reçoit
aucun `SELECT` sur contacts, leads, tâches, activités, Inbox ou audit tenant. Le résumé
d'usage n'accorde aucun accès brut aux données CRM.

`company_invitations` et `platform_audit_logs` forcent RLS. Le contexte
`app.current_platform_user_id` est transactionnel. L'acceptation publique utilise
seulement le hash du token dans `app.current_invitation_token_hash`. Les fonctions
`SECURITY DEFINER` sont limitées à la révocation de sessions, la création d'un User
invité, l'acceptation Owner et l'écriture append-only d'audit.

Un rôle tenant ne peut pas présenter son JWT au portail. Inversement, un token plateforme
ne contient aucun tenant et est refusé par les routes métier. Il n'existe ni impersonation
ni ouverture des prospects d'un client.

En production et en staging, `DATABASE_URL` doit utiliser un login non-superuser qui
n'est jamais membre de `automation_migrator`. L'API verifie cette propriete avant tout
`SET LOCAL ROLE` et refuse la transaction si l'identite est privilegiee. Alembic et le
bootstrap utilisent exclusivement `MIGRATION_DATABASE_URL`, fourni pour la duree de
l'operation puis retire. Aucun login partage entre API et migration n'est autorise hors
environnement local de test.
