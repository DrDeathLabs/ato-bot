# Production Operations

This guide describes a controlled self-hosted deployment. ATO Bot remains a human-in-the-loop assessment system and should be deployed with an organization's existing authorization, privacy, records, and incident-response controls.

## Deployment Intent

Use immutable release tags, externalized secrets, persistent volumes, a reverse proxy with TLS, tested backups, and a monitored host. Do not use `latest` for a regulated or repeatable deployment.

## Required Secrets

Protect PostgreSQL and Redis passwords, `SECRET_KEY`, JWT configuration, provider credentials, and any TLS private key. Store secrets in a host secret manager or protected environment files. Rotate them on a defined schedule and after exposure. Never include them in screenshots, issue reports, logs, or Git.

## Network Exposure

Keep PostgreSQL and Redis bound to loopback or the private Compose network. Expose only the frontend through a reverse proxy. Restrict administrative routes with authentication and network controls. If the UI is bound to a LAN address, use firewall rules and TLS; do not treat a private IP as authentication.

## Reverse Proxy and TLS

Terminate TLS at a managed reverse proxy or hardened nginx. Forward the application host to the frontend port, preserve WebSocket/SSE behavior used by assessment progress, set upload size/timeouts appropriate to evidence, and send security headers. Verify `/api` requests and long-running assessment streams through the proxy.

## Database and Redis

PostgreSQL stores projects, users, evidence metadata, findings, assessment state, governance records, and report metadata. Redis supports coordination and job state. Do not edit assessment records directly. Run migrations through the one-shot `migrate` service. Monitor disk, connection limits, queue depth, failed jobs, and long-running transactions.

## Model Provider

Configure provider credentials and model names in `backend/.env`. The provider must be reachable from backend and worker containers. Keep model, prompt, retrieval, and policy changes outside active assessments; create a new controlled run after material changes. Record provider/model context with assessment outputs.

## Storage and Monitoring

Back up PostgreSQL, `backend/uploads`, and `backend/outputs` together. Monitor service health, migration status, worker failures, ingestion failures, storage capacity, authentication lockouts, and export errors. Treat uploaded evidence and generated reports as sensitive system data.

## Operational Checklist

```powershell
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d
docker compose ps
docker compose logs --tail=100 migrate backend worker frontend
```

Validate login, project isolation, a synthetic upload, a small assessment, an export, and backup health after deployment. See [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md), [UPGRADING.md](UPGRADING.md), and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
