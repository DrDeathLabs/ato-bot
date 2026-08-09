# Backup and Restore

Backups must preserve the database and file evidence together. A database-only restore can leave source records pointing to missing documents or generated outputs.

## Backup

Use a protected destination outside the repository. Example for a local Compose database:

```powershell
$stamp = Get-Date -Format yyyyMMdd-HHmmss
New-Item -ItemType Directory -Force "backup/$stamp" | Out-Null
docker compose exec -T postgres pg_dump -U atobot -d atobot -Fc > "backup/$stamp/atobot.dump"
Copy-Item backend/uploads "backup/$stamp/uploads" -Recurse
Copy-Item backend/outputs "backup/$stamp/outputs" -Recurse
docker compose exec -T postgres psql -U atobot -d atobot -c "select version_num from alembic_version;" > "backup/$stamp/migration.txt"
```

Protect backups as sensitive evidence. Apply retention, encryption, access control, and off-host replication appropriate to the system boundary. Test restores rather than assuming a successful dump is recoverable.

## Restore Order

1. Stop backend and worker while preserving volumes.
2. Restore PostgreSQL into an empty or verified target database.
3. Restore `backend/uploads` and `backend/outputs` with the expected ownership and permissions.
4. Restore the matching application release and environment configuration.
5. Run the documented migration check; do not skip migrations.
6. Start backend, worker, and frontend.

```powershell
docker compose up -d postgres redis
docker compose exec -T postgres pg_restore -U atobot -d atobot --clean --if-exists < backup/20260809-120000/atobot.dump
docker compose run --rm migrate
docker compose up -d backend worker frontend
```

The exact restore command depends on the target volume and dump type. Validate it in an isolated environment first.

## Validation After Restore

Confirm migration revision, user login, project count, system-owner assignments, document counts, source-file access, assessment findings, citations, generated reports, audit history, and export downloads. Open a representative selected control and verify that citations resolve to restored source records. Run a small synthetic assessment before declaring recovery complete.
