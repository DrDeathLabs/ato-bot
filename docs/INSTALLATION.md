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
git checkout v0.1.0
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
```

Set strong values for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and `SECRET_KEY`. Do not leave `CHANGE_ME` or example API keys in either environment file. Configure a model provider before ingestion or assessment; login, project setup, and basic health checks do not make model calls.

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps --all
docker compose exec backend python seed_admin.py
```

The seed command prompts for the administrator password. It defaults to username `admin` and email `admin@atobot.local`; pass a different username and email as positional arguments when needed, for example `docker compose exec backend python seed_admin.py tutorial-admin tutorial-admin@atobot.local`.

The `migrate` service runs `alembic upgrade head` and must exit with code 0 before the backend and worker start. `docker compose ps --all` is intentional: the migration service is expected to be stopped after a successful run, while `postgres`, `redis`, `backend`, `worker`, and `frontend` remain running.

## GHCR Installation

The commands below use the public `v0.1.0` release and intentionally avoid `latest` for reproducibility. If you already cloned the repository, start at `Set-Location`.

```powershell
git clone https://github.com/DrDeathLabs/ato-bot.git
Set-Location ato-bot
git checkout v0.1.0
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
$env:ATOBOT_IMAGE_TAG = "v0.1.0"
# The packages are public; authenticate only if GHCR requests it or rate-limits anonymous pulls.
# docker login ghcr.io
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml build postgres
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull migrate backend worker frontend redis
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml ps --all
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml exec backend python seed_admin.py
```

PostgreSQL is intentionally built from the repository's pinned local image definition; the backend, migration, worker, and frontend images are pulled from GHCR.

Images:

- `ghcr.io/drdeathlabs/ato-bot-backend:v0.1.0`
- `ghcr.io/drdeathlabs/ato-bot-frontend:v0.1.0`

PostgreSQL and Redis remain local Compose dependencies. The release workflow publishes SBOM/provenance and signed application images when configured.

## Environment Configuration

Root `.env` controls Compose values such as project name, database/Redis passwords, frontend bind address, and experimental feature flags. `backend/.env` controls application, JWT, database, Redis, file storage, model runtime, assessment, lockout, and CORS values. Compose replaces the container database and Redis URLs with the internal service names; the `localhost` values in `backend/.env.example` are for non-Compose/local process use and are not used by the Compose services. Use the example files as the complete key list.

When Ollama runs on the host instead of in Docker Desktop, set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `backend/.env` so the backend and worker can reach it. On Linux, use a routable host address or add an explicit host-gateway mapping in a local Compose override. Anthropic and Bedrock credentials are read by the backend and worker containers from `backend/.env`.

The safe default is `FRONTEND_BIND_ADDRESS=127.0.0.1`. Bind to a LAN address only when host firewall rules, TLS/reverse proxy, authentication, and network trust are deliberate.

## Health Validation

```powershell
docker compose ps --all
Invoke-WebRequest http://127.0.0.1:3001/ -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker compose logs --tail=100 migrate backend worker frontend
```

Confirm `migrate` exited with code 0, PostgreSQL/Redis/backend/frontend are healthy, the worker is running, and the UI can log in. Test a small synthetic project before importing a large evidence corpus. A model provider is required before ingestion, evidence analysis, or assessment execution.

## Common Installation Failures

- **Compose rejects a variable:** copy the example files and replace every required `CHANGE_ME` value.
- **Migration does not complete:** inspect `docker compose logs migrate`; fix database connectivity or the migration revision before starting the API.
- **Frontend opens but login fails:** inspect backend health/logs, confirm the proxy URL, clear stale browser storage, and check account lockout.
- **Worker stays unhealthy:** verify Redis, model provider reachability, disk permissions, and backend health.
- **Model calls fail:** configure a provider reachable from the backend/worker container, not only from the host browser.
- **GHCR pull denied:** authenticate to GHCR and confirm the package visibility/tag. Public packages normally pull anonymously.
