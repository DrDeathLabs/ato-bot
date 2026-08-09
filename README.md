# ATO Bot

ATO Bot is a human-in-the-loop NIST SP 800-53 assessment workbench. It ingests security documentation, creates traceable evidence units, evaluates assessment objectives, applies deterministic adjudication policy, supports assessor review and remediation, and produces report and OSCAL-oriented outputs.

## Important Scope

ATO Bot produces assessment evidence analysis and draft control determinations. It does **not** replace a qualified assessor, perform every NIST SP 800-53A interview or technical test, or make an authorization decision. Final findings require human validation, appropriate testing, and approval under the adopting organization's assessment process.

## Supported Core

- Project, system-profile, common-control, policy, and procedure workspaces
- Staged document ingestion with provenance, classification, evidence units, and embeddings
- Low, Moderate, and High NIST SP 800-53 Rev. 5 baseline support
- Objective-level evidence routing, model reasoning, contradiction review, and code-governed rollup
- Human finding review, notes, overrides, dissent handling, remediation guidance, and draft artifacts
- Word, Excel, JSON, SSP, SAR, POA&M, and OSCAL-oriented outputs
- RBAC, audit logging, MFA support, runtime configuration, and security posture views

Feature maturity and deprecation status are documented in [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md).
Known limitations and the security boundary are documented in [docs/LIMITATIONS.md](docs/LIMITATIONS.md) and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Documentation

Start with the [documentation index](docs/README.md) and [User Guide](docs/USER_GUIDE.md). The release documentation also includes the [Assessment Workflow](docs/ASSESSMENT_WORKFLOW.md), [Ingestion Guide](docs/INGESTION_GUIDE.md), [Remediation and Outputs](docs/REMEDIATION_AND_OUTPUTS.md), [Administration Guide](docs/ADMINISTRATION.md), [Deployment Guide](docs/DEPLOYMENT.md), [Architecture](docs/ARCHITECTURE.md), and [Verified E2E Workflows](docs/E2E_VERIFIED_WORKFLOWS.md).

## Quick Start

### Prerequisites

- Docker Desktop with Docker Compose
- At least one configured model provider: an Ollama-compatible endpoint, Anthropic, or AWS Bedrock
- Sufficient memory and storage for the selected model and document corpus

### Configure

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
```

Replace every `CHANGE_ME` value. Generate a strong application secret, for example:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

The public Compose configuration binds the UI to `127.0.0.1` by default. Change `FRONTEND_BIND_ADDRESS` only when remote access is intentional and protected by host firewall and network controls.

### Run

```powershell
docker compose up --build -d
docker compose exec backend python seed_admin.py
```

Open `http://127.0.0.1:3001` and sign in with the account created by the seed command.

## GitHub Container Registry

Release tags publish signed application images to GitHub Container Registry:

- `ghcr.io/drdeathlabs/ato-bot-backend:<tag>` — backend API, worker, and migration image
- `ghcr.io/drdeathlabs/ato-bot-frontend:<tag>` — frontend and nginx image

The database and Redis services remain separate dependencies. After a release is published, pull the application images with the GHCR Compose override:

```powershell
$env:ATOBOT_IMAGE_TAG = "latest"
docker login ghcr.io
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
```

Use a version tag such as `v1.0.0` instead of `latest` for a reproducible deployment. The GHCR workflow runs only for version tags and publishes SBOM, provenance, and a Cosign signature for each application image.

### Verify

```powershell
docker compose ps
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install --constraint backend/constraints.txt -r backend/requirements-dev.txt
backend/.venv/Scripts/python -m pytest -q backend/tests
Set-Location frontend
npm ci
npm audit --audit-level=high
npm run lint
npm run build
```

`backend/constraints.txt` is generated from the supported Linux build and pins runtime and development dependencies. Update it deliberately when dependencies change, then rerun both dependency audits and image builds.

## Architecture

- React and Vite frontend served by unprivileged nginx
- FastAPI web service and a separate background worker
- PostgreSQL with pgvector for application state and vector retrieval
- Redis for coordination, caching, and job state
- Pluggable Ollama-compatible, Anthropic, and AWS Bedrock model runtimes

Detailed architecture and assessment-flow documentation is under [`docs/`](docs/).
Database upgrades are owned by Alembic and are run by the one-shot `migrate` Compose service before the web service and worker start. See [docs/UPGRADING.md](docs/UPGRADING.md).

## Security

Never commit `.env`, uploaded evidence, generated reports, database exports, collector payloads, or model credentials. See [SECURITY.md](SECURITY.md) for vulnerability reporting and [CONTRIBUTING.md](CONTRIBUTING.md) for development checks.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). Use of NIST names and resources does not imply NIST endorsement.
