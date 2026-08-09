# Deployment Guide

ATO Bot is distributed as a Docker Compose application. The supported development deployment runs PostgreSQL with pgvector, Redis, a FastAPI backend, a background worker, a migration service, and an unprivileged nginx frontend.

## Local Build

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
docker compose up --build -d
docker compose exec backend python seed_admin.py
docker compose ps
```

Replace every `CHANGE_ME` value before starting the stack. The default frontend bind is `127.0.0.1:3001`.

## GitHub Container Registry

Release tags publish:

- `ghcr.io/drdeathlabs/ato-bot-backend:<tag>`
- `ghcr.io/drdeathlabs/ato-bot-frontend:<tag>`

The backend image is reused for the migration and worker services. PostgreSQL and Redis remain separate services.

```powershell
$env:ATOBOT_IMAGE_NAMESPACE = "drdeathlabs"
$env:ATOBOT_IMAGE_TAG = "v0.1.0"
docker login ghcr.io
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
```

Use immutable version tags for repeatable deployments. `latest` is convenient for evaluation but should not be used for a controlled assessment environment.

## Startup Order

The migration service must complete before the backend and worker start. Backend and frontend health checks should be green before a user begins a run. If the backend is recreated, the frontend nginx proxy must dynamically resolve the backend service through Docker DNS.

## Upgrade

1. Back up PostgreSQL, uploads, and outputs.
2. Record the current image tags and Alembic revision.
3. Pull the target immutable release tag.
4. Run `docker compose run --rm migrate` and require success.
5. Start the stack and verify health, login, project isolation, assessment state, and exports.
6. Verify backend-only recreation does not break frontend API routing.

Never treat a migration failure as a reason to start the backend anyway. Restore from a verified backup if an upgrade cannot complete safely.

## Health and Troubleshooting

```powershell
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 worker
docker compose logs --tail=200 frontend
```

Common symptoms:

- Login page loads but login fails: check backend health, auth account status, and nginx API routing.
- Documents remain processing: inspect worker logs and the ingestion run stage.
- Assessment is queued: check migration completion, worker health, Redis, and the assessment job record.
- Frontend is stale after backend recreation: recreate only the frontend if the deployment predates the dynamic Docker DNS proxy fix; current releases should resolve the backend dynamically.
