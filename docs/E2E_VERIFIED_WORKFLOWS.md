# Verified E2E Workflows

This document records the live development-stack browser checks used for the open-source release candidate. It is not a claim that every NIST assessment activity has been performed by automation.

## Environment

- Frontend: `http://127.0.0.1:3001`.
- Docker Compose services: frontend, backend, worker, PostgreSQL, Redis.
- Migration revision at the latest check: `a1b2c3d4e5f6`.
- Other Docker applications were not restarted or modified.

## Executable Browser Checks

The configured Playwright suite covers:

- valid login and redirect to Projects;
- feature metadata retrieval;
- project creation and deletion;
- optional FISMA System Owner creation and assignment;
- project detail accountability display;
- logout;
- invalid credentials staying on the login page.

The latest run passed 3 executable tests. The assessment-navigation scenario was skipped because no `E2E_PROJECT_ID` and `E2E_ASSESSMENT_ID` values were supplied for that run. When supplied, that scenario checks that leaving the Findings context clears stale selected-control state.

## Defect Found During E2E

The project create form serialized an empty optional system-owner select as an empty string. The backend correctly expects a nullable identifier. The frontend now serializes an unselected owner as `null`, and the browser test covers project creation without an owner.

The system-owner test also now sends authenticated cleanup for its temporary account. Disposable local E2E accounts are deactivated after verification. Existing named review projects are not modified by the browser tests.

## Required Release-Level E2E Still Outstanding

The following require a dedicated release run and should not be inferred from the browser smoke suite:

- full 20-family, 324-control, 1,467-objective assessment;
- pause, resume, retry, worker recovery, and backend-only recreation during a run;
- all required Examine, Interview, and Test activity records;
- complete review, dissent resolution, tailoring, POA&M, approvals, and finalization;
- semantic reconciliation across UI, database, reports, and OSCAL outputs;
- repeated controlled runs and calibration stability.

## Reproduce the Browser Suite

```powershell
Set-Location frontend
npm ci
npx playwright install --with-deps chromium
npm run e2e
```

Set `E2E_USERNAME`, `E2E_PASSWORD`, and optionally `E2E_BASE_URL`, `E2E_PROJECT_ID`, and `E2E_ASSESSMENT_ID` for a controlled environment.
