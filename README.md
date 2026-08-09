# ATO Bot

ATO Bot is a human-in-the-loop NIST SP 800-53 assessment platform. It takes a system owner and assessor from project setup and evidence preparation through objective evaluation, control review, remediation planning, and report production. Model-driven analysis is bounded by evidence provenance, assessment policy, deterministic rollup rules, and human review.

![ATO Bot assessment workspace](docs/assets/assessment-overview.png)

## What It Does

The supported workflow is:

1. Create a project and describe the system boundary.
2. Assign the FISMA System Owner and configure inherited/common controls.
3. Upload project, common-control, policy, and procedure evidence.
4. Review parsing, classification, evidence units, provenance, duplicates, and readiness.
5. Create and approve an assessment plan with scope, methods, objects, depth, and coverage.
6. Run objective-level evidence analysis and deterministic control adjudication.
7. Review findings, citations, contradictions, confidence, dissent, and assessment activities.
8. Use remediation guidance, POA&M workflow, generated drafts, and report exports.

ATO Bot is not an autonomous assessor, an authorization authority, or a substitute for required interviews and technical tests. A qualified assessor remains responsible for assessment judgment, evidence acceptance, approvals, risk decisions, and the final authorization package.

## Capability Status

Supported capabilities include project and system-profile management, evidence libraries, NIST SP 800-53 baseline assessment, objective reasoning, deterministic policy rollups, human review, remediation guidance, draft artifacts, audit logging, RBAC, and report/OSCAL-oriented outputs. Beta and experimental capabilities are explicitly tracked in [FEATURE_STATUS.md](docs/FEATURE_STATUS.md) and [EXPERIMENTAL_CAPABILITIES.md](docs/EXPERIMENTAL_CAPABILITIES.md). Known limitations are in [LIMITATIONS.md](docs/LIMITATIONS.md).

## Start Here

| Audience | Start with | Then read |
| --- | --- | --- |
| New user | [User Guide](docs/USER_GUIDE.md) | [Installation](docs/INSTALLATION.md) |
| Assessor or reviewer | [Assessment Operations](docs/ASSESSMENT_OPERATIONS.md) | [Assessment Workflow](docs/ASSESSMENT_WORKFLOW.md) |
| FISMA System Owner or control owner | [User Guide](docs/USER_GUIDE.md) | [Remediation and Outputs](docs/REMEDIATION_AND_OUTPUTS.md) |
| Administrator | [Administration](docs/ADMINISTRATION.md) | [Production](docs/PRODUCTION.md) |
| Operator | [Installation](docs/INSTALLATION.md) | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Developer | [Development](docs/DEVELOPMENT.md) | [Testing](docs/TESTING.md) |
| Security or release reviewer | [Threat Model](docs/THREAT_MODEL.md) | [Open Source Readiness](docs/OPEN_SOURCE_READINESS.md) |

The full audience map and route inventory are in [docs/README.md](docs/README.md).

## Install With GHCR

Prerequisites: Docker Desktop or Docker Engine with Compose v2, a PostgreSQL/Redis-capable host, persistent storage, and a configured model provider. Use a pinned release tag rather than `latest`:

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
# Set strong values for every CHANGE_ME entry and configure one model provider.
$env:ATOBOT_IMAGE_TAG = "v0.1.6"
docker login ghcr.io
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
docker compose ps
```

Open `http://127.0.0.1:3001`, then create an administrator using the documented seed or administrator workflow. See [Installation](docs/INSTALLATION.md) for environment details and health validation.

## Install From Source

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
docker compose up --build -d
docker compose exec backend python seed_admin.py
```

The one-shot `migrate` service runs Alembic before the API and worker start. Never expose PostgreSQL or Redis directly to an untrusted network. For TLS, reverse proxy, backups, monitoring, and upgrades, use [Production](docs/PRODUCTION.md).

## Developer Quick Start

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install --constraint backend/constraints.txt -r backend/requirements-dev.txt
Set-Location frontend
npm ci
npm run lint
npm run build
```

Run the service stack with Docker for the closest integration environment. Backend tests, frontend checks, migration checks, and Playwright workflows are described in [Testing](docs/TESTING.md).

## Project Structure

- `backend/`: FastAPI API, worker, migrations, services, tests, uploads, and generated outputs.
- `frontend/`: React/Vite application, routes, components, and Playwright tests.
- `docs/`: operator, assessor, architecture, security, and release documentation.
- `docker/`: database and deployment support files.
- `docker-compose.yml`: source-build deployment.
- `docker-compose.ghcr.yml`: pinned GHCR application-image override.

## Security Boundary

Uploaded evidence, generated artifacts, model prompts, database exports, `.env` files, and runtime credentials are deployment data, not source-controlled examples. Do not commit them. ATO Bot does not guarantee that generated text is correct, complete, current, or eligible evidence; every final determination must be reviewed under the adopting organization's governance process.

## License

Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE), [SECURITY.md](SECURITY.md), and [CONTRIBUTING.md](CONTRIBUTING.md). Use of NIST names and resources does not imply NIST endorsement.
