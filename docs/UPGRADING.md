# Upgrading ATO Bot

Use immutable release tags and a tested restore path. Do not upgrade an active assessment run without recording the impact and choosing a controlled boundary.

## Version-Pinned Upgrade

```powershell
$env:ATOBOT_IMAGE_TAG = "v0.1.6"
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml run --rm migrate
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
docker compose ps
```

For source builds, check out the release tag, review `CHANGELOG.md` and both environment examples, then run `docker compose build`, `docker compose run --rm migrate`, and `docker compose up -d`.

## Migration Behavior

Alembic owns schema changes. The one-shot `migrate` service must complete successfully before backend and worker startup. Record the old and new `alembic_version`, database backup path, image digests, and validation results.

## Post-Upgrade Validation

Check health, login/logout, role and project isolation, system-owner assignment, document access, ingestion readiness, assessment navigation, selected-control review, remediation guidance, and exports. Recreate only the backend and verify the frontend still routes API traffic correctly through Docker DNS. Run backend tests, frontend lint/build, and available Playwright smoke tests.

## Rollback Boundaries

If the new application image fails before a migration, restore the prior image tag. If a migration has changed the schema, do not blindly downgrade; restore the tested PostgreSQL backup and matching uploads/outputs or follow a documented forward-fix. Never use database edits as an ad hoc rollback for assessment governance data.
