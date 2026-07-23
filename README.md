# Plateforme d’Automatisation Intelligente

Monorepo composé de `backend` (FastAPI/PostgreSQL) et `frontend`
(Next.js/Playwright). La CI GitHub Actions exécute les mêmes contrôles que les
commandes PowerShell ci-dessous sur chaque pull request et chaque push sur
`main`.

## Installation

```powershell
Set-Location .\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Set-Location ..\frontend
npm.cmd ci
Set-Location ..
```

## Qualité backend

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m ruff format --check app tests alembic scripts
.\.venv\Scripts\python.exe -m ruff check app tests alembic scripts
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest -m unit
Set-Location ..
```

Pour appliquer automatiquement le formatage :

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m ruff format app tests alembic scripts
.\.venv\Scripts\python.exe -m ruff check --fix app tests alembic scripts
Set-Location ..
```

## Tests PostgreSQL et Alembic

```powershell
docker compose -f .\docker-compose.test.yml up -d --wait postgres_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://automation_test:automation_test_password@127.0.0.1:55432/automation_test"
$env:APP_ENV = "test"
$env:JWT_SECRET_KEY = "local-ci-only-jwt-key-0123456789abcdef"

Set-Location .\backend
$previousDatabaseUrl = $env:DATABASE_URL
$env:DATABASE_URL = $env:TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m alembic upgrade head
$env:DATABASE_URL = $previousDatabaseUrl
.\.venv\Scripts\python.exe -m pytest -m integration
$env:DATABASE_URL = $env:TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic check
$env:DATABASE_URL = $previousDatabaseUrl
Set-Location ..

Remove-Item Env:TEST_DATABASE_URL, Env:APP_ENV, Env:JWT_SECRET_KEY
docker compose -f .\docker-compose.test.yml down
```

## Qualité frontend

```powershell
Set-Location .\frontend
npm.cmd ci
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run test:components --if-present
npm.cmd run build
Set-Location ..
```

## E2E Playwright

Préparer la base synthétique et Redis :

```powershell
docker compose -f .\docker-compose.test.yml up -d --wait postgres_test
docker compose up -d redis
$env:DATABASE_URL = "postgresql+psycopg://automation_test:automation_test_password@127.0.0.1:55432/automation_test"
$env:APP_ENV = "test"
$env:JWT_SECRET_KEY = "local-e2e-only-jwt-key-0123456789abcdef"
$env:E2E_EMAIL = "e2e-user@example.com"
$env:E2E_PASSWORD = "Local-Only-E2E-Password-42!"
$env:E2E_VIEWER_EMAIL = "e2e-viewer@example.com"
$env:E2E_VIEWER_PASSWORD = "Local-Only-Viewer-Password-42!"
$env:DEFAULT_COMPANY_ID = "11111111-1111-4111-8111-111111111111"
$env:BACKEND_API_URL = "http://127.0.0.1:8000"

Set-Location .\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe .\scripts\seed_e2e.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dans un second terminal PowerShell, depuis la racine :

```powershell
$env:E2E_EMAIL = "e2e-user@example.com"
$env:E2E_PASSWORD = "Local-Only-E2E-Password-42!"
$env:E2E_VIEWER_EMAIL = "e2e-viewer@example.com"
$env:E2E_VIEWER_PASSWORD = "Local-Only-Viewer-Password-42!"
$env:DEFAULT_COMPANY_ID = "11111111-1111-4111-8111-111111111111"
$env:BACKEND_API_URL = "http://127.0.0.1:8000"
Set-Location .\frontend
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

## Politique de secrets

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\check_repository_secrets.py
```

Les fichiers `.env`, clés privées et formats de secrets courants sont refusés.
Seuls les fichiers `.env.example` avec valeurs factices peuvent être suivis.
Les rapports et traces Playwright sont publiés par la CI uniquement en cas
d’échec.
