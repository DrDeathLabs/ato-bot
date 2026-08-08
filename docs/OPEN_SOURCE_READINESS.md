# Open-Source Readiness

## Current Status

ATO Bot remains private and is **not approved for public release**. Apache-2.0 licensing, repository governance, dynamic feature status, hardened JWT validation, Alembic-owned schema changes, a one-shot migration service, frontend route splitting, and baseline CI/security workflows are now present.

Verified locally in the current cleanup branch:

- Moderate baseline: 324 unique controls and enhancements, 1,467 objectives, and all `EXAMINE`, `INTERVIEW`, and `TEST` method types preserved.
- Frontend production entry chunk: 384 KB; no generated chunk exceeds 500 KB.
- Frontend dependency audit: zero known vulnerabilities.
- Python production dependency audit: zero known vulnerabilities.
- Frontend lint: zero errors; legacy cleanup warnings remain.
- Backend unit and release-contract suite: 49 tests passed.
- Core browser E2E passed locally in an isolated stack: login, feature metadata, project create/delete, logout, and invalid-login behavior.
- Fresh migrations and governance downgrade/re-upgrade completed in disposable PostgreSQL/pgvector databases.
- A verified external backup of the current local database was restored and upgraded in an isolated stack without changing record totals: 356 assessments, 4,878 findings, and 52,895 objective determinations. The upgraded API started healthy and the release verifier correctly rejected a legacy 324-control/1,467-objective run that lacked the new governance records.
- Reproducible Python dependency constraints are consumed by Docker and CI.
- Existing local runtime data has not been migrated or modified.

## Closed P0/P1 Foundations

- Apache-2.0 `LICENSE`, `NOTICE`, DCO, Contributor Covenant, support and security policies.
- Explicit Git allowlist posture through `.gitignore`, `.dockerignore`, and staged-file review requirements.
- `PyJWT[crypto]` tokens with issuer, audience, subject, type, issued-at, identifier, expiry, and approved-algorithm validation.
- Alembic ownership of schema changes; application startup performs no DDL.
- Approved pre-run assessment plans with frozen evidence hashes and exact ingestion-run scope.
- Explicit assessment activities for NIST `EXAMINE`, `INTERVIEW`, and `TEST` methods.
- Human finding review, dissent resolution, tailoring decisions, POA&M completeness, dual approval, and finalization blockers.
- Generated-artifact quarantine and explicit evidence eligibility.
- Worker-only assessment execution and restart recovery.
- Durable failed-finding retries that preserve frozen evidence scope, policy adjudication, and review invalidation across restarts.
- Authoritative feature registry and a preserved experimental/unreachable capability inventory.

## Remaining Publication Blockers

1. Run the full 20-family, 324-control, 1,467-objective regression against the release candidate and meet documented stability tolerances.
   Validate the resulting governed assessment with `cd backend && python scripts/verify_release_assessment.py <assessment_id>`.
2. Add database-backed project-isolation and permission tests across every API group. A structural contract now prevents unapproved public routes and project routes without an access dependency, but it does not replace live cross-tenant tests.
3. Run the locally passing browser workflow in private GitHub Actions and resolve any environment-specific failures.
4. Validate semantic reconciliation across UI, database, SAR, POA&M, SSP, Word, Excel, JSON, and OSCAL exports using a finalized governed assessment.
5. Populate and approve calibration suites for every supported model/prompt/policy/retrieval combination.
6. Run CodeQL, dependency review, Gitleaks, Trivy, and SBOM workflows on the exact candidate commit.
7. Coordinate the live upgrade from the verified backup, rotate all deployment credentials, and verify login after backend-only recreation. Backup creation and isolated upgrade validation are complete; the live database has intentionally not been changed.
8. Resolve every item in `EXPERIMENTAL_CAPABILITIES.md` with a recorded retain/promote/remove/defer decision.
9. Review the exact staged file set for private evidence, reports, host identifiers, archives, and patent material.
10. Configure protected `main` branch checks in the private GitHub repository; this cannot be enforced by local files alone.

## Publication Gate

Public visibility is allowed only after every blocker above is evidenced on one immutable release commit and receives final human approval. A passing unit suite or successful build alone is not publication approval.
