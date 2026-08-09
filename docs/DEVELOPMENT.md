# Development

## Repository Layout

- `backend/app`: FastAPI routes, models, services, workers, and schemas.
- `backend/alembic`: versioned database migrations.
- `backend/tests`: unit and API tests.
- `frontend/src`: React routes, pages, components, and feature registry.
- `frontend/e2e`: Playwright browser workflows.
- `docs`: public operator, assessment, security, and technical docs.
- `docker` and Compose files: local and GHCR deployment support.

## Local Workflow

Use Docker Compose for PostgreSQL, Redis, backend, worker, and frontend integration. Use a backend virtual environment for fast tests and `npm ci` for deterministic frontend dependencies.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install --constraint backend/constraints.txt -r backend/requirements-dev.txt
Set-Location frontend
npm ci
```

Do not run application servers against a production database from a developer shell. Use a dedicated Compose project and synthetic data.

## Generated Files and Data

Uploaded evidence, generated reports, E2E outputs, database dumps, screenshots containing live data, and model responses belong in ignored local directories. Keep only synthetic, reviewed examples in `docs/assets`. Never commit `backend/.env`, root `.env`, provider keys, customer evidence, or host-specific paths.

## Change Discipline

Schema changes require Alembic migrations. Changes to prompts, retrieval, policy, model runtime, or assessment logic require focused tests and calibration/regression evidence. Changes to routes require a Playwright or API regression. Documentation must state the supported boundary and identify beta/experimental behavior.
