# Feature Status

This registry prevents experimental or compatibility behavior from being mistaken for supported product capability.

## Supported Core

- Authentication, RBAC, MFA, and audit logging
- Projects, system profiles, common controls, policy libraries, and procedure libraries
- Document ingestion, evidence-unit creation, classification, embeddings, and provenance
- Baseline assessment execution, objective determinations, deterministic rollups, and reviewer workflows
- Remediation guidance, closure workflows, draft artifact review, and assessment reports
- Control catalog, assessment policy, SSP workbench, and OSCAL-oriented exports

## Beta

- Cyber Assistant and attachment interpretation
- System knowledge extraction and architecture/tool inventory
- Calibration suites and synthetic test-dataset generation
- Human-style remediation artifact generation

Beta features are available for evaluation but require stronger automated tests and release-level calibration before production claims.

## Experimental and Disabled by Default

- cATO dashboard
- External integration accounts and connector synchronization
- Continuous telemetry and drift rollups derived from connector scaffolding

The current connector implementation includes dry-run behavior and explicitly does not implement every live provider API. The backend registry at `GET /api/meta/features` is authoritative. These routes and frontend navigation remain disabled unless `ENABLE_EXPERIMENTAL_CATO=true` is configured on the backend.

See `EXPERIMENTAL_CAPABILITIES.md` for the preservation and eventual disposition inventory. No experimental capability is part of the supported-feature claim.

## Deprecated Compatibility Paths

- `/dashboard` redirects to `/projects`; the projects workspace is the supported landing page.
- `/admin/ingestion-config` redirects to `/admin/ai-runtime`.
- Legacy ingestion chunk/tag structures remain only for compatibility while evidence units are the supported assessment path.
- Legacy token migration clears old `localStorage` tokens after moving an active session to `sessionStorage`.

## Removal Candidates After Git History Exists

The following source files have no route or import in the current frontend and should be removed in a dedicated, reversible change after the repository has commit history:

- `frontend/src/pages/security/POAM.jsx`
- `frontend/src/pages/security/Scorecard.jsx`
- `frontend/src/pages/security/SecurityEvents.jsx`
- `frontend/src/pages/Dashboard.jsx`

The security APIs remain in use by the supported Security Ops dashboard, so this candidate list applies only to the orphaned page components.
