# Administration Guide

## Users and Roles

Administrators manage users, active status, passwords, MFA settings, and roles from the Users area. Use least privilege and create separate accounts for assessors, system owners, reviewers, and administrators where the operating model requires separation of duties.

The role names used by the application include system administrator, assessor, system owner, and reviewer-oriented permissions. Project access is enforced at the API boundary; UI visibility is not the security boundary.

## FISMA System Owner

The FISMA System Owner is the accountable owner for the system being assessed. Assign this role from the project creation form or the project detail accountability section. It is distinct from the legacy technical project owner field.

The selected system owner should be an active user with the system-owner role. Deactivating a user should not silently transfer accountability; reassign the project explicitly.

## Assessment Policy

Assessment Policy controls the deterministic rollup behavior used after objective evaluation. Review policy buckets, thresholds, weights, family overrides, control overrides, objective overrides, and policy version state before a release assessment.

Treat a policy change as an assessment-engine change. Record the active policy version in the assessment context and rerun calibration or regression evidence before relying on changed rollups.

## AI Runtime and Prompts

AI Runtime configuration controls provider, model, embedding, context strategy, and timeout/retry behavior. Prompt Manager controls the named prompt purposes used by ingestion, assessment, challenge, remediation, assistant, and artifact flows.

Do not change a production-like runtime or prompt in the middle of an assessment. Start a new run when model, prompt, policy, retrieval, or evidence scope changes materially.

## Feature Registry

`GET /api/meta/features` is the authoritative runtime feature registry. It reports supported, beta, experimental, deprecated, and disabled capabilities. The frontend should not advertise a feature that the registry disables.

Experimental connector and optional security-posture capabilities are disabled by default and are not part of the supported release claim. Operational observability in the supported product means application health, job state, audit activity, configuration changes, and processing status. See [FEATURE_STATUS.md](FEATURE_STATUS.md) and [EXPERIMENTAL_CAPABILITIES.md](EXPERIMENTAL_CAPABILITIES.md).

## Audit and Security Operations

Use project audit history and the security audit log to review authentication events, project actions, assessment actions, overrides, approvals, and export activity. Protect audit data as governance evidence. Do not edit database records directly to "fix" an assessment history.

## Operational Rules

- Keep secrets in `.env` files or a secret manager, never in Git.
- Back up PostgreSQL, uploads, and generated outputs before upgrades.
- Run Alembic migrations through the `migrate` service.
- Do not expose PostgreSQL or Redis broadly without a deliberate network and firewall design.
- Do not treat generated drafts, beta output, or synthetic data as production evidence.
