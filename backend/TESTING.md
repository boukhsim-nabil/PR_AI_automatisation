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
