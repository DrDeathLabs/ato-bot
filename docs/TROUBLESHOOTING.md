# Troubleshooting

Start with `docker compose ps` and `docker compose logs --tail=200 <service>`. Do not delete volumes or reset the database while investigating.

## Login and Account Lockout

Check backend health, frontend proxy logs, account active status, password, and lockout state. Stop repeated attempts after the configured threshold. An administrator should reset the account. If the page reports a stale session, sign out, clear site storage for the ATO Bot origin, close old tabs, and sign in again.

## Frontend or Backend Resolution

If the UI loads but API calls fail after a backend recreation, inspect the frontend nginx configuration and Docker DNS path. Recreate only ATO Bot services, not other Compose projects. Confirm `docker compose exec frontend getent hosts backend` where the image provides the command, then verify `/api/auth/login` through the frontend URL. The frontend proxy is intended to re-resolve the backend dynamically.

## Unhealthy Backend or Worker

Inspect migration completion, PostgreSQL/Redis health, backend `/health`, model provider connectivity, disk permissions, and recent traceback logs. A worker cannot process assessments if Redis is unhealthy or the provider is unreachable. Fix the root service before retrying jobs.

## Queued, Paused, or Failed Assessment

Confirm the plan is approved, the evidence scope is ready, and the worker is running. For a failed run, inspect the failed-control list and retry only after the underlying provider/storage issue is fixed. Resume a paused run rather than creating a second uncontrolled run. If progress is stale, capture the assessment ID and logs before restarting a service.

## Ingestion Failures

Check file type/size, parser logs, upload storage, worker health, and available disk. Review failed/degraded states, duplicate signals, classification confidence, and indexing/embedding status. Do not use degraded fallback output as final assessment evidence until it is corrected and reviewed.

## GHCR Pull Failures

Run `docker login ghcr.io`, verify the package/tag, check network access, and use the exact GHCR override. A private package requires a token with package read permission. Pin the tag again after a successful pull.

## Reports and Exports

Confirm the assessment is in the state required by the output, the worker completed generation, storage is writable, and the browser download was not blocked. Compare report counts to the workspace before distribution. A schema-valid OSCAL file is not proof that missing assessment activities occurred.

## Model Provider Failures

Verify the provider URL from inside the backend/worker network, credentials, model name, context window, timeout, and rate limits. Check runtime configuration and prompt version. Do not change provider settings in the middle of a controlled assessment without documenting the change and starting a new run.
