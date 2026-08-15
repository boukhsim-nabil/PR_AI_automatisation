# Portail Super-Administration

Le portail `/admin` est réservé au rôle plateforme `platform_super_admin`. Ce rôle est
indépendant des rôles tenant et ne crée aucun `Membership`.

## Bootstrap sécurisé

Après `alembic upgrade head`, exécuter depuis `backend` :

```powershell
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://<migration_user>:<secret>@<host>:5432/<database>"
.\.venv\Scripts\python.exe -m scripts.bootstrap_platform_admin --email votre-administrateur@domaine.com
Remove-Item Env:MIGRATION_DATABASE_URL
```

Le mot de passe est demandé par saisie masquée et n'apparaît pas dans l'historique
PowerShell. La commande est idempotente et le compte doit être nominatif.

## Rotation et récupération

1. Bootstrapper un second compte nominatif contrôlé.
2. Vérifier sa connexion et son MFA.
3. Retirer l'association de l'ancien compte dans une procédure DBA approuvée.
4. Révoquer ses `platform_sessions` et conserver les audits.

En cas de perte totale d'accès, un DBA utilise la même commande depuis un environnement
de maintenance authentifié. Aucune route publique ne promeut un utilisateur. La MFA est
préparée par `users.mfa_enabled` et `platform_sessions.mfa_verified`; le challenge reste
à intégrer avant exposition Internet.

Les sessions plateforme sont distinctes et limitées à huit heures. L'access token expire
après dix minutes. Le cookie Next.js est HttpOnly, `SameSite=Strict` et `Secure` en
production.

Le login est limité à cinq échecs sur cinq minutes par couple IP/email. Ce garde-fou
est local au processus ; un déploiement avec plusieurs réplicas doit le remplacer par
un compteur Redis partagé. `mfa_verified` reste faux tant qu'un vrai challenge MFA
n'a pas été ajouté : activer le flag utilisateur ne simule jamais une vérification.
