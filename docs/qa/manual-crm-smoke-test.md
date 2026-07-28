# Smoke test manuel CRM

Date :

Testeur :

Version / commit :

Environnement : PostgreSQL de test uniquement (`automation_test`, port `55432`)

## Comptes synthétiques

| Tenant | Rôle | Email | Résultat de connexion |
|---|---|---|---|
| Tenant A — E2E Synthetic Tenant | Owner | `e2e-user@example.com` | À renseigner |
| Tenant A — E2E Synthetic Tenant | Sales | `e2e-sales@example.com` | À renseigner |
| Tenant A — E2E Synthetic Tenant | Viewer | `e2e-viewer@example.com` | À renseigner |
| Tenant B — E2E Foreign Tenant | Owner | `e2e-foreign@example.com` | À renseigner |

## Scénarios CRM

| # | Scénario | Attendu | Résultat | Preuve / remarque |
|---:|---|---|---|---|
| 1 | Créer un prospect avec Owner dans le Tenant A | Contact et lead créés ensemble | À tester | |
| 2 | Créer le même email dans le Tenant B | Création autorisée | À tester | |
| 3 | Recréer le même email dans le Tenant A | Conflit 409, aucun contact orphelin | À tester | |
| 4 | Changer le statut d’un prospect | Statut et activité mis à jour | À tester | |
| 5 | Passer à `lost` sans motif | Validation refusée | À tester | |
| 6 | Passer à `lost` avec motif | Statut accepté et activité créée | À tester | |
| 7 | Attribuer le prospect au compte Sales | Attribution et activité créées | À tester | |
| 8 | Créer puis terminer une tâche | `completed_at` renseigné | À tester | |
| 9 | Archiver deux fois le même prospect | Succès idempotent, une seule activité | À tester | |
| 10 | Ouvrir l’URL du prospect Tenant A depuis le Tenant B | Réponse 404 sans fuite de données | À tester | |
| 11 | Essayer une modification avec Viewer | Réponse 403 / action absente de l’interface | À tester | |
| 12 | Se déconnecter puis réutiliser une ancienne page | Redirection vers la connexion | À tester | |

## Vérifications PostgreSQL en lecture seule

| Élément | Vérification | Résultat / remarque |
|---|---|---|
| Tables | `contacts`, `leads`, `crm_activities`, `crm_tasks`, `audit_logs`, `auth_sessions` | À vérifier |
| Clés étrangères | Relations tenant-aware et memberships | À vérifier |
| Contraintes | Emails tenant-aware, statuts, scores et priorités | À vérifier |
| Index | Index CRM par tenant et filtres principaux | À vérifier |
| RLS | Policies forcées sur les tables CRM | À vérifier |
| Données | Séparation Tenant A / Tenant B | À vérifier |
| Audit | Connexions, modifications, refus et tentatives inter-tenant | À vérifier |
| Sessions | Sessions actives et révoquées | À vérifier |
| Activités | Historique des statuts, attributions, notes et tâches | À vérifier |

Ne modifier aucune donnée avec pgAdmin, DBeaver ou psql. Toutes les opérations
manuelles doivent passer par l’application, et uniquement sur la base de test.

## Décision

- [ ] Conforme
- [ ] Conforme avec réserves
- [ ] Non conforme

Réserves ou anomalies :
