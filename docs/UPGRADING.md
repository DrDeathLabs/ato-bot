# Upgrading ATO Bot

1. Back up PostgreSQL, uploaded files, and generated outputs.
2. Record the current application version and Alembic revision.
3. Pull or check out the immutable target release tag.
4. Review `CHANGELOG.md`, `.env.example`, and `backend/.env.example` for required configuration changes.
5. Run `docker compose build`.
6. Run `docker compose run --rm migrate` and require a zero exit code.
7. Start the stack with `docker compose up -d`.
8. Verify health, login, project isolation, document access, assessment state, and exports.
9. Recreate only the backend and verify the frontend continues to reach `/api` through Docker DNS.

Never run a production upgrade without a tested restore procedure. Alembic downgrade operations may remove governance data and are not a substitute for restoring a verified backup.
