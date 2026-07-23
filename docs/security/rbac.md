# Socle RBAC

## Source d’autorité

Le frontend ne transmet jamais de rôle. Le JWT identifie l’utilisateur, le
tenant et le membership, mais chaque décision d’autorisation recharge le
membership depuis PostgreSQL, vérifie qu’il est actif, puis utilise son
`role_id` courant. Un rôle absent équivaut à zéro permission.

Les routes peuvent utiliser la dépendance :

```python
Depends(require_permission("crm.read"))
```

Une permission absente renvoie `403 Permission denied`. Un membership, un
utilisateur ou une entreprise inactive renvoie `403 Active membership
required`.

## Rôles système initiaux

- `owner` et `admin` : toutes les permissions initiales.
- `manager` : lecture entreprise/membres, CRM complet, gestion des workflows et
  lecture de l’audit.
- `sales` : lecture entreprise/membres, lecture/création/mise à jour CRM et
  lecture des workflows.
- `support` : lecture entreprise/membres, lecture/mise à jour CRM et lecture des
  workflows.
- `viewer` : lecture entreprise/membres/CRM/workflows.

Les codes sont stables et le champ `is_system` distingue ces rôles des futurs
rôles personnalisés. Le seed synchronise exactement leurs permissions et peut
être rejoué sans créer de doublons.

## Initialisation

Après application des migrations :

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe .\scripts\seed_rbac.py
```

Le seed utilisateur local `scripts/seed.py` appelle aussi le seed RBAC et
attribue explicitement le rôle `owner` au membership local qu’il gère.

## Limites actuelles

- Aucun écran ni endpoint de gestion des membres ou des rôles n’est exposé.
- Les rôles initiaux sont globaux. L’affectation à un utilisateur reste
  tenant-scoped via `memberships`, protégé par RLS.
- `is_system` est un indicateur de domaine ; les futurs services de gestion
  devront interdire la suppression ou le changement de code de ces rôles.
- Modifier un rôle ou ses permissions prend effet à la requête suivante, sans
  attendre l’expiration du JWT.
