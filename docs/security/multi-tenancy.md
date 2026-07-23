# Isolation multi-tenant avec PostgreSQL RLS

## Périmètre actuel

La migration `20260722_0002` active et force Row-Level Security sur toutes les
tables actuellement porteuses de `company_id`. À ce jour, seule la table
`memberships` répond à ce critère. Les anciennes migrations ne sont pas
modifiées.

Chaque future migration ajoutant une table avec `company_id` doit également :

1. activer `ENABLE ROW LEVEL SECURITY` et `FORCE ROW LEVEL SECURITY` ;
2. créer une politique `USING` et `WITH CHECK` basée sur
   `app.current_company_id` ;
3. accorder uniquement les privilèges nécessaires à `automation_app` ;
4. ajouter des tests PostgreSQL d’isolation en lecture et en écriture.

## Mécanisme transactionnel

La politique compare `company_id` à :

```sql
NULLIF(current_setting('app.current_company_id', true), '')::uuid
```

FastAPI ouvre une transaction par dépendance `get_db`, exécute
`SET LOCAL ROLE automation_app`, puis configure le tenant authentifié avec :

```sql
SELECT set_config('app.current_company_id', '<company UUID>', true);
```

Le troisième argument `true` rend la valeur locale à la transaction. Un
`COMMIT` ou `ROLLBACK` la supprime avant le retour de la connexion au pool. Si
le contexte est absent ou vide, l’expression vaut `NULL` et la politique ne
retourne aucune ligne. Les écritures qui changeraient `company_id` sont
refusées par `WITH CHECK`.

Le endpoint public de login ne possède pas encore de JWT. Il abaisse néanmoins
la transaction au rôle applicatif, puis utilise le `company_id` du payload
avant la première lecture de `memberships`. La réponse d’échec reste générique.

## Rôles PostgreSQL

- `automation_app` : rôle `NOLOGIN`, sans `BYPASSRLS`, utilisé par toutes les
  transactions applicatives. Ses privilèges sont volontairement limités.
- `automation_migrator` : rôle technique `NOLOGIN`, propriétaire des tables et
  autorisé à contourner RLS pour les migrations et opérations administratives.

La migration ne contient aucun mot de passe. En production, un administrateur
doit créer deux identités de connexion distinctes et leur attribuer un seul
rôle de groupe chacune, par exemple :

```sql
CREATE ROLE platform_api LOGIN NOINHERIT PASSWORD '<secret externe>';
GRANT automation_app TO platform_api;

CREATE ROLE platform_migration LOGIN NOINHERIT PASSWORD '<secret externe>';
GRANT automation_migrator TO platform_migration;
```

Les secrets doivent venir du gestionnaire de secrets de l’environnement. Le
compte de migration ne doit jamais être utilisé par le processus FastAPI. Le
compte qui applique initialement la migration doit pouvoir créer des rôles et
transférer la propriété des tables.

Après ce bootstrap initial, FastAPI doit se connecter avec `platform_api` ; le
code exécute ensuite `SET LOCAL ROLE automation_app`. Alembic doit se connecter
avec `platform_migration` et sélectionner explicitement son rôle de groupe, par
exemple avec l’option libpq `options=-c role=automation_migrator` encodée dans
son URL ou fournie par la configuration d’exécution.

## Pool de connexions

`SET LOCAL` est obligatoire : `SET` sans portée transactionnelle est interdit
car il pourrait conserver un tenant sur une connexion réutilisée. Un test avec
un pool d’une seule connexion vérifie que le même backend PostgreSQL sert deux
transactions successives et que la seconde, sans contexte, ne voit aucune
ligne.

## Limites et modèle de menace

- RLS protège contre les requêtes applicatives oubliant un filtre tenant. Il ne
  protège pas contre un compte PostgreSQL superutilisateur, `BYPASSRLS`, ou le
  rôle de migration compromis.
- `companies` et `users` ne portent actuellement pas de colonne `company_id` et
  ne sont donc pas couverts par cette politique. Leur accès doit rester limité
  aux requêtes prévues et être réévalué si leur modèle devient tenant-scoped.
- Le middleware JWT empêche un client de remplacer son tenant via
  `X-Company-ID`; RLS constitue une seconde barrière indépendante pour les
  tables tenant-scoped.
- La valeur transactionnelle est définie par le processus applicatif. Une
  compromission complète du runtime FastAPI peut demander un autre tenant ;
  les permissions minimales, l’audit et la séparation des rôles restent donc
  nécessaires.
- Les tâches asynchrones, scripts et workers doivent adopter la même ouverture
  de transaction et ne jamais utiliser le rôle de migration pour leur activité
  métier.
