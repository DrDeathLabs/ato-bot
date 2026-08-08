# Contributing

## Development Setup

1. Copy `.env.example` to `.env` and `backend/.env.example` to `backend/.env`.
2. Replace placeholder secrets and configure a model provider.
3. Start the stack with `docker compose up --build -d`.
4. Create an administrator with `docker compose exec backend python seed_admin.py`.

## Required Checks

Run these before opening a pull request:

```powershell
docker compose config --quiet
docker compose exec -T backend python -m unittest discover -s tests -v
Set-Location frontend
npm ci
npm audit --audit-level=high
npm run build
```

Do not submit real evidence documents, generated assessment packages, runtime collector payloads, `.env` files, database dumps, or credentials.

## Change Expectations

- Preserve provenance and human-review boundaries for assessment behavior.
- Add tests for adjudication, evidence eligibility, authorization, and report semantics when those areas change.
- Treat model output as untrusted structured input and validate it before persistence or display.
- Document new feature maturity in `docs/FEATURE_STATUS.md`.
- Use Alembic for schema changes; do not add new runtime DDL to application startup.
- Keep experimental capabilities behind explicit feature flags.

## Developer Certificate of Origin

Contributions must include a `Signed-off-by` line certifying that the contributor
has the right to submit the change under the Apache-2.0 license. Create signed-off
commits with:

```powershell
git commit --signoff
```

The full Developer Certificate of Origin is available at
https://developercertificate.org/.

## Security

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).
