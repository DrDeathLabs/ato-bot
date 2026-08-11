# ATO Bot Installation Audit

**Audit date:** 2026-08-11  
**Verified platform:** Windows PowerShell with Docker Compose v5.1.1  
**Verified application release:** `v0.1.0` GHCR images  
**Scope:** Public installation instructions and the install-to-first-workspace path

## Plain-Language Result

The ATO Bot installation path works when the operator follows the corrected Compose sequence in [INSTALLATION.md](INSTALLATION.md). A fresh isolated run successfully pulled the public application images, built the required local PostgreSQL image, ran the Alembic migration service, started the backend, worker, Redis, and frontend, created an administrator, logged in, created a synthetic project, loaded the project workspace, and signed out.

The installation does **not** require a model provider for startup, login, or project creation. A reachable model provider is required before ingestion, evidence analysis, embeddings, or assessment execution.

## Canonical GHCR Procedure

Run these commands from PowerShell on a clean checkout. Replace the example secrets before starting the stack.

```powershell
git clone https://github.com/DrDeathLabs/ato-bot.git
Set-Location ato-bot
git checkout v0.1.0
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
$env:ATOBOT_IMAGE_TAG = "v0.1.0"
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml build postgres
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull migrate backend worker frontend redis
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml ps --all
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml exec backend python seed_admin.py
```

The seed command prompts for the password and does not require the password to appear in shell history. The default account is `admin` / `admin@atobot.local`; pass a different username and email as the first two positional arguments when needed.

For a source build, use the same clone and environment steps, then run:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps --all
docker compose exec backend python seed_admin.py
```

## Why Each Step Exists

| Step | Verified purpose |
| --- | --- |
| Clone and checkout | Uses the public repository and a reproducible release tag. |
| Copy environment examples | Creates the root Compose settings and backend application settings. |
| Replace `CHANGE_ME` values | Prevents startup with placeholder database, Redis, or JWT secrets. |
| `config --quiet` | Validates Compose interpolation before images are built or started. |
| Build `postgres` | PostgreSQL/pgvector is intentionally a local image; it is not published as an application image. |
| Pull `migrate`, `backend`, `worker`, `frontend`, and `redis` | Retrieves the application images and the pinned Redis dependency. |
| `up -d --no-build` | Starts the stack without accidentally rebuilding the pinned application images. |
| `ps --all` | Shows both running services and the expected stopped migration service. |
| `seed_admin.py` | Creates the initial `system_admin` account and prompts for its password. |

## Service Contract

The Compose project starts these services:

- `postgres`: PostgreSQL with pgvector, persistent named volume, health check.
- `redis`: password-protected Redis, persistent named volume, health check.
- `migrate`: one-shot backend image running `alembic upgrade head`; expected final state is exited with code 0.
- `backend`: FastAPI API on `127.0.0.1:8000`, health endpoint `/health`.
- `worker`: background ingestion, assessment, report, and artifact worker; expected state is running.
- `frontend`: unprivileged nginx UI on `127.0.0.1:3001`, proxying API traffic to `backend`.

The normal first health check is:

```powershell
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml ps --all
Invoke-WebRequest http://127.0.0.1:3001/ -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml logs --tail=100 migrate backend worker frontend
```

Expected results are HTTP 200 for the frontend and backend, healthy PostgreSQL/Redis/backend/frontend services, a running worker, and migration exit code 0.

## Model Provider Boundary

The Compose stack overrides database and Redis URLs to use the internal service names `postgres` and `redis`. The `localhost` values in `backend/.env.example` are not valid for reaching those sibling containers and are not used by the Compose overrides.

If Ollama runs on the Docker Desktop host, set this in `backend/.env`:

```text
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

On Linux, use a routable host address or a local Compose override with an explicit host-gateway mapping. Anthropic and Bedrock credentials must be available to both the backend and worker containers. A model provider is not needed to prove that installation, login, and project setup work.

## Evidence From the Fresh Isolated Run

The privacy-safe installation tutorial run recorded these results in `../tmp/installation_tutorial/verification_results.json`:

- source repository: `https://github.com/DrDeathLabs/ato-bot.git`
- release: `v0.1.0`
- Compose configuration: passed
- local PostgreSQL image build: passed
- GHCR image pull: passed
- Compose launch: passed
- migration exit code: `0`
- backend health: HTTP `200`, `{"status":"ok","app":"ATO Bot"}`
- frontend health: HTTP `200`
- synthetic administrator: created and used successfully
- synthetic project: `Tutorial Demo System`
- browser path: login, project creation, workspace load, logout passed
- non-tutorial containers changed: none
- existing ATO Bot stack ports and volumes changed: none

## Corrections Made During This Audit

- Added explicit clone and `v0.1.0` checkout steps to the primary installation paths.
- Added the required local PostgreSQL image build to GHCR installation instructions.
- Made GHCR pull service names explicit and kept startup on `--no-build`.
- Replaced vague administrator language with the exact interactive `seed_admin.py` command.
- Changed service validation to `docker compose ps --all` so the successful one-shot migration is visible.
- Added direct frontend and backend health checks.
- Clarified that model configuration is required for assessment work, not for basic startup.
- Documented Docker Desktop host reachability for Ollama.
- Clarified that public GHCR packages normally pull anonymously; authentication is only needed when GHCR requests it or rate-limits the client.
- Replaced the tutorial transcript's abbreviated `docker compose ...` lines with the canonical copy/pasteable command sequence. The video itself retains short command cards for visual readability.

## Release-Tag Documentation Drift

The public `v0.1.0` tag currently points to commit `783b2b18ef52fc0c4b7c77175940a54a7a85518d`, while the current `main` branch is `c78da269073ae37e18c45d16259727be22625d65`. The code and Compose files used by installation are unchanged between those commits; the difference is installation documentation. The `v0.1.0` tag's embedded README and installation page do not include the required local PostgreSQL build command.

This is a release-documentation issue, not a runtime failure: the isolated `v0.1.0` install passed when the corrected command sequence was used. Do not force-move an existing public release tag without an explicit release decision. The corrected current instructions are the source of truth on `main`; the release should be republished or otherwise documented before claiming that the tag's own embedded documentation is identical to `main`.

## Trust Boundary

This audit verifies installation and first-workspace operation. It does not claim that a model provider, evidence corpus, full assessment, or generated report is valid merely because the containers start. Before using ATO Bot for an assessment, configure the provider, test ingestion with synthetic evidence, confirm worker processing, and follow the human review and assessment governance procedures in [ASSESSMENT_OPERATIONS.md](ASSESSMENT_OPERATIONS.md).

