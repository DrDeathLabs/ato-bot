# ATO Bot Architecture

## Product Center

ATO Bot is an end-to-end evidence-to-assessment workbench for NIST SP 800-53. Ingestion is the preparation layer. The center of gravity is the assessment engine: criteria assembly, evidence routing, objective reasoning, deterministic adjudication, human review, remediation, and reporting.

## Runtime Components

- React and Vite frontend served by unprivileged nginx.
- FastAPI backend for authentication, project APIs, ingestion orchestration, assessment, review, remediation, and reports.
- Background worker for long-running ingestion, assessment, remediation, artifact, and dataset jobs.
- PostgreSQL for structured application state and pgvector semantic retrieval.
- Redis for coordination, caching, and job support.
- Local or mounted file storage for uploaded source material and generated outputs.
- Pluggable Ollama-compatible, Anthropic, and AWS Bedrock model runtimes.

## Assessment Data Flow

```text
source documents
  -> parsed records
  -> screened and expanded evidence
  -> classified evidence units and embeddings
  -> criteria package and evidence packet
  -> objective determinations
  -> code-governed control status
  -> challenge and human review
  -> remediation and reports
```

## Trust Boundaries

The model is allowed to interpret bounded context and return structured analysis. It is not the sole authority for control status, finalization, or authorization. Deterministic code applies policy rules and rollups. Humans provide required assessment activities, challenge results, overrides, approvals, and risk decisions.

## Core Persistence

Important business objects include users, projects, documents, parsed lines, evidence units, embeddings, assessments, criteria packages, evidence triage, objective reviews, objective determinations, control findings, challenges, rollups, policies, overrides, activities, remediation reports, POA&M records, assistant conversations, system knowledge, and export runs.

## Frontend Surfaces

Supported routes include Projects, Project Detail, Assessment View, Common Controls, Enterprise Policies, Enterprise Procedures, Control Catalog, Assessment Policy, SSP Workbench, Architecture and Tools, Project Audit Log, Users, Security Audit Log, Admin Security Dashboard, Prompt Manager, and AI Runtime.

The assessment workspace is intentionally separated into Overview, Findings, Evidence, Outputs, and Advanced contexts. Experimental integrations and continuous posture surfaces are feature-gated and disabled by default.

## Reliability Pattern

ATO Bot is staged rather than single-shot. Each major phase produces persisted state and provenance. This supports retries, review, repeatability analysis, and report reconciliation. A worker restart should resume durable jobs rather than silently changing scope or creating duplicate findings.

## Security Pattern

The application uses authenticated API routes, role and project access checks, audit logging, MFA support, rate limiting, non-root containers, read-only runtime filesystems where practical, pinned runtime dependencies, and Alembic-owned schema changes. The operational deployment still requires correct secret handling, network controls, backup procedures, and human governance.
