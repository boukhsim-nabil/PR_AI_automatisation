# Tests backend

Les tests `unit` restent isolés dans SQLite. Les tests `integration` utilisent
uniquement le service PostgreSQL `postgres_test`, sur le port local `55432`.
Le garde-fou Pytest refuse toute autre base, tout autre utilisateur ou le port
de développement.

## Tests unitaires SQLite

Depuis la racine du dépôt :

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest -m unit
Set-Location ..
```

## Tests d’intégration PostgreSQL

Depuis la racine du dépôt :

```powershell
docker compose -f .\docker-compose.test.yml up -d --wait postgres_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://automation_test:automation_test_password@127.0.0.1:55432/automation_test"
$previousDatabaseUrl = $env:DATABASE_URL
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest -m integration
Set-Location ..
if ($null -eq $previousDatabaseUrl) {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
} else {
    $env:DATABASE_URL = $previousDatabaseUrl
}
Remove-Item Env:TEST_DATABASE_URL
docker compose -f .\docker-compose.test.yml down
```

## Execution depuis la racine du monorepo

La configuration Pytest reste dans `backend/pyproject.toml`. Depuis la racine,
la commande reproductible pour les tests unitaires est :

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -c .\backend\pyproject.toml .\backend\tests -m unit
```

Pour la suite complete, demarrer `postgres_test`, definir `TEST_DATABASE_URL`
comme ci-dessus, puis retirer `-m unit` de la commande.

## Version Python

L'environnement virtuel local actuel utilise Python 3.13.1. La CI utilise
Python 3.12 et le projet declare `Python >= 3.12`. Une standardisation future
sur Python 3.12 est recommandee pour garantir la parite locale/CI, sans recreer
le `.venv` dans cette tache.

## Suite complète

Le service de test doit être démarré avant la suite complète :

```powershell
docker compose -f .\docker-compose.test.yml up -d --wait postgres_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://automation_test:automation_test_password@127.0.0.1:55432/automation_test"
$previousDatabaseUrl = $env:DATABASE_URL
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Set-Location .\backend
.\.venv\Scripts\python.exe -m pytest
Set-Location ..
if ($null -eq $previousDatabaseUrl) {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
} else {
    $env:DATABASE_URL = $previousDatabaseUrl
}
Remove-Item Env:TEST_DATABASE_URL
docker compose -f .\docker-compose.test.yml down
```
