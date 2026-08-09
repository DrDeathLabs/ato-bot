# Testing

Run checks from the repository root unless a command changes directory explicitly.

## Backend

```powershell
backend/.venv/Scripts/python -m pytest -q backend/tests
backend/.venv/Scripts/python -m ruff check backend/app backend/tests
```

Add unit coverage for service logic, API integration coverage for route contracts, migration coverage for empty and upgraded databases, worker coverage for retry/recovery, and report-semantic coverage for exports.

## Frontend

```powershell
Set-Location frontend
npm ci
npm run lint
npm run build
npm audit --audit-level=high
```

## Playwright

The browser suite uses `http://127.0.0.1:3001` by default. Set `E2E_USERNAME`, `E2E_PASSWORD`, `E2E_PROJECT_ID`, and `E2E_ASSESSMENT_ID` only in the local environment when the selected scenarios need them.

```powershell
npm run e2e
npx playwright test e2e/core-workflow.spec.js e2e/system-owner.spec.js
```

Use synthetic projects and evidence. Do not point browser tests at a customer or shared production deployment.

## Compose, Migration, and Release Checks

```powershell
Set-Location ..
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml config --quiet
docker compose run --rm migrate
```

Release checks should include dependency scanning, secret scanning, license checks, container scanning, SBOM generation, image signature/provenance verification, `git diff --check`, and a clean install from the documented example configuration.

## Assessment Regression

For assessment-engine, prompt, retrieval, or policy changes, run controlled evidence through all expected families and compare objective/control IDs, rollups, citations, dissent, and report semantics. A focused family run is not a substitute for the full regression run.
