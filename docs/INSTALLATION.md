# Installation

This guide installs the development or self-hosted ATO Bot stack. It assumes Docker Compose v2 and a host with persistent storage. For security-sensitive deployment, read [PRODUCTION.md](PRODUCTION.md) first.

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2.
- At least 8 GB RAM for a small test corpus; model requirements may be higher.
- Persistent disk for PostgreSQL, Redis, uploads, and generated outputs.
- One model provider: Ollama-compatible, Anthropic, or AWS Bedrock.
- PowerShell examples below can be translated to Bash.

## Source-Build Installation

```powershell
git clone https://github.com/DrDeathLabs/ato-bot.git
Set-Location ato-bot
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
```

Set strong values for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `SECRET_KEY`, and the selected provider. Do not leave `CHANGE_ME`, example API keys, or localhost model settings that do not match the deployment network.

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

The `migrate` service runs `alembic upgrade head` and must exit successfully before the backend and worker start. Create the first administrator using the supported seed/administrator procedure exposed by the image, then open `http://127.0.0.1:3001`.

## GHCR Installation

Use the version tag shown in the GitHub release. The examples below intentionally avoid `latest` for reproducibility.

```powershell
Set-Location ato-bot
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
$env:ATOBOT_IMAGE_TAG = "v0.1.6"
docker login ghcr.io
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
```

Images:

- `ghcr.io/drdeathlabs/ato-bot-backend:v0.1.6`
- `ghcr.io/drdeathlabs/ato-bot-frontend:v0.1.6`

PostgreSQL and Redis remain local Compose dependencies. The release workflow publishes SBOM/provenance and signed application images when configured.

## Environment Configuration

Root `.env` controls Compose values such as project name, database/Redis passwords, frontend bind address, and experimental feature flags. `backend/.env` controls application, JWT, database, Redis, file storage, model runtime, assessment, lockout, and CORS values. Use the example files as the complete key list.

The safe default is `FRONTEND_BIND_ADDRESS=127.0.0.1`. Bind to a LAN address only when host firewall rules, TLS/reverse proxy, authentication, and network trust are deliberate.

## Health Validation

```powershell
docker compose ps
Invoke-WebRequest http://127.0.0.1:3001/ -UseBasicParsing
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker compose logs --tail=100 migrate backend worker frontend
```

Confirm `migrate` exited with code 0, backend/worker/frontend are healthy, and the UI can log in. Test a small synthetic project before importing a large evidence corpus.

## Common Installation Failures

- **Compose rejects a variable:** copy the example files and replace every required `CHANGE_ME` value.
- **Migration does not complete:** inspect `docker compose logs migrate`; fix database connectivity or the migration revision before starting the API.
- **Frontend opens but login fails:** inspect backend health/logs, confirm the proxy URL, clear stale browser storage, and check account lockout.
- **Worker stays unhealthy:** verify Redis, model provider reachability, disk permissions, and backend health.
- **Model calls fail:** configure a provider reachable from the backend/worker container, not only from the host browser.
- **GHCR pull denied:** authenticate to GHCR and confirm the package visibility/tag.
