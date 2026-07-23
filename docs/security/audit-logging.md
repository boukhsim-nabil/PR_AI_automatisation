# Journal d’audit

## Garanties

`audit_logs` est tenant-scoped par `company_id` et protégé par PostgreSQL RLS.
Le rôle `automation_app` possède uniquement `SELECT` et `INSERT`; `UPDATE` et
`DELETE` sont révoqués. Aucun endpoint applicatif de modification ou de
suppression n’existe.

Les écritures passent par `AuditService`. Les événements sont mis en attente
sur la requête puis persistés dans une transaction séparée après la réponse.
Ainsi, un login refusé ou une transaction métier annulée conserve son événement
d’audit.

## Corrélation

Chaque requête reçoit un UUID de corrélation. Un header entrant
`X-Correlation-ID` n’est conservé que s’il contient un UUID valide; sinon un
nouvel UUID est généré. Toutes les réponses renvoient ce même header et les
événements produits par la requête l’enregistrent.

## Métadonnées et secrets

Le nettoyage récursif remplace par `[REDACTED]` toute valeur dont la clé évoque
un mot de passe, cookie, JWT, token, clé API, clé privée, authorization ou
secret. Les chaînes au format JWT et les valeurs `Bearer` sont également
supprimées. Les routes ne doivent malgré tout transmettre que des métadonnées
minimales et non sensibles.

## Événements initiaux

- `auth.login` : succès et échec;
- `auth.refresh` : succès, expiration, révocation, réutilisation ou membership
  inactif;
- `auth.logout` et `auth.logout_all`;
- `security.cross_tenant`;
- `authorization.permission_denied`.

Une future modification métier doit utiliser le même service, par exemple :

```python
AuditService.record(
    request.scope,
    AuditEvent(
        company_id=access.company.id,
        actor_user_id=access.user.id,
        actor_membership_id=access.membership.id,
        action="crm.contact.updated",
        result="success",
        resource_type="crm_contact",
        resource_id=str(contact.id),
        metadata={"changed_fields": ["status"]},
    ),
)
```

## Consultation

`GET /v1/audit-logs` exige `audit.read`. Les paramètres disponibles sont :

- `action`, `result`, `resource_type` : filtres exacts;
- `limit` : 1 à 100, 50 par défaut;
- `offset` : pagination à partir de zéro.

RLS limite ensuite les résultats à l’entreprise du membership actif, même si
un filtre applicatif est oublié.

## Limites

- Un échec de login portant un `company_id` inexistant ne peut pas être inséré
  dans une table tenant-scoped avec clé étrangère; l’erreur de persistance est
  journalisée côté serveur.
- L’écriture après réponse privilégie la conservation des refus sans faire
  échouer la requête utilisateur. Pour une garantie réglementaire stricte, une
  file transactionnelle/outbox et un stockage d’audit dédié seront nécessaires.
- Le rôle `automation_migrator` reste capable d’administrer la table; ses accès
  doivent être limités, supervisés et séparés du runtime FastAPI.
