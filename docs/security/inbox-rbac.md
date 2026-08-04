# RBAC de l’Inbox

Le lot M3.1-B enregistre les permissions Inbox sous forme de codes stables. Il
n’ajoute encore aucun endpoint : les dépendances d’autorisation seront appliquées
au lot API ultérieur.

| Rôle | Permissions Inbox |
| --- | --- |
| `owner` | Toutes |
| `admin` | Toutes |
| `manager` | Toutes les permissions opérationnelles |
| `support` | `read`, `reply`, `assign`, `update_status`, `notes.create`, `takeover` |
| `sales` | `read`, `reply`, `notes.create` |
| `viewer` | `read` uniquement |

Les codes complets sont préfixés par `inbox.`. La migration et le seed utilisent
des insertions idempotentes. Le seed synchronise seulement les associations
déclarées : les permissions CRM, audit, membres, société et workflows conservent
leur répartition existante.

Les autorisations applicatives ne remplacent pas l’isolation PostgreSQL. Toutes
les tables M3.1-B forcent RLS avec `app.current_company_id`, et toutes leurs clés
étrangères métier incluent `company_id`.
