# ATO Bot Architecture Review

Date: 2026-05-11

## 1. Executive Summary

ATO Bot is a compliance evidence, assessment, and reporting platform built to help teams prepare, assess, and maintain ATO-ready security documentation and evidence against NIST SP 800-53 / 800-53A style requirements.

At a system level, the product combines:

- a React web application for analysts, assessors, and admins
- a FastAPI backend that owns business logic and API orchestration
- a PostgreSQL database with `pgvector` for structured storage and semantic retrieval
- a Redis-backed operational layer for worker coordination and runtime support
- a background worker that executes ingestion, assessment, remediation, and test-dataset jobs
- multiple AI-assisted pipelines for document ingestion, evidence classification, assessment adjudication, artifact generation, assistant workflows, and system knowledge extraction

The most important architectural idea in the current codebase is that ATO Bot is not a single-shot "upload docs and get a verdict" application. It is a staged evidence system:

1. documents are parsed into traceable source records
2. relevant content is screened and expanded into reusable evidence units
3. evidence is classified and embedded for retrieval
4. assessment criteria are assembled per control
5. objective-level reasoning is performed against curated evidence packets
6. final control status is determined by code, not only by the model
7. human review, override, remediation, reporting, and export remain first-class

That staged architecture is the core differentiator of the system.

## 2. Product Scope

From the codebase, ATO Bot currently spans these functional domains:

- project and assessment management
- project, enterprise, and common-control document libraries
- ingestion and indexing of `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.vsdx`, text, markdown, and image artifacts
- RAG-style evidence retrieval using semantic embeddings
- automated control assessment and adjudication
- human review, override, challenge, and activity logging
- closure and remediation workflows
- SSP composition and OSCAL export
- AI assistant conversations with contextual attachments
- system knowledge extraction from evidence
- integration and telemetry scaffolding for continuous ATO / cATO use cases
- internal security dashboarding for the product itself

This makes the system broader than a document generator. It is closer to a compliance operations platform with an AI-centered evidence graph.

## 3. Verified Technology Stack

### Frontend

The frontend is a React single-page application in [frontend/src/App.jsx](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/frontend/src/App.jsx) built with:

- React 18
- React Router
- TanStack React Query
- Axios
- Tailwind CSS
- Vite

Frontend routes show the main product surfaces:

- projects and project detail
- assessment view
- system profile
- architecture and tools
- integrations
- SSP workbench
- cATO dashboard
- common controls
- enterprise policies and procedures
- admin prompt management
- ingestion runtime configuration
- test dataset generation

### Backend

The backend is a FastAPI application in [backend/app/main.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/main.py) using:

- FastAPI
- SQLAlchemy asyncio
- Alembic
- `pgvector`
- Redis
- SlowAPI for rate limiting
- JWT auth and refresh sessions
- MFA support

The backend is split across:

- `api/` for route handlers
- `core/` for config, DB, security, RBAC, and rate limiting
- `models/` for ORM and schemas
- `services/` for ingestion, assessment, AI, reporting, telemetry, and orchestration

### Data and AI dependencies

Key backend dependencies from [backend/requirements.txt](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/requirements.txt):

- `python-docx`, `openpyxl`, `python-pptx`, `pymupdf`, `vsdx`, `pytesseract`, `Pillow`
- `anthropic`, `boto3`, `ollama`, `httpx`
- `sentence-transformers`, `tiktoken`
- `jsonschema`

### Deployment/runtime

The Docker Compose stack in [docker-compose.yml](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/docker-compose.yml) runs:

- `postgres` using `pgvector/pgvector:pg16`
- `redis`
- `backend`
- `worker`
- `frontend`

The backend entrypoint in [backend/start_backend.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/start_backend.py) waits for DB and Redis, applies Alembic migrations, then launches Uvicorn.

The worker entrypoint in [backend/start_worker.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/start_worker.py) waits for dependencies and launches the async job worker.

## 4. High-Level Architecture

### Runtime components

1. Browser client
- React SPA handles authentication, navigation, workbenches, document operations, and reporting UI.

2. API/application server
- FastAPI exposes project, document, assessment, AI assistant, SSP, telemetry, and admin APIs.

3. Background worker
- Pulls pending jobs from the database and processes ingestion, assessments, remediation reports, and test datasets.

4. Database
- PostgreSQL stores users, projects, documents, assessments, findings, evidence units, vector embeddings, policy state, assistant conversations, system knowledge, telemetry, and exports.

5. Vector store
- `pgvector` is used inside PostgreSQL for semantic search over evidence embeddings.

6. File storage
- Uploaded and generated artifacts are stored on disk in `backend/uploads` and `backend/outputs`.

7. Model/runtime providers
- Ollama-compatible reasoning runtime
- Anthropic Claude provider
- AWS Bedrock provider
- Voyage-style embedding path is reflected in the ingestion/assessment docs and service layout

### Architectural pattern

The system is best described as:

- a web application
- backed by a staged evidence-processing pipeline
- with deterministic adjudication around model outputs
- plus human review surfaces
- plus export and operational telemetry layers

It is not a pure agent product and not a pure document store.

## 5. Primary Business Objects

The ORM in [backend/app/models/orm.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/models/orm.py) shows the core data model.

### Identity and access

- `User`
- `RefreshToken`
- `AuditLog`

### Project and evidence domain

- `Project`
- `Document`
- `DocumentChunk`
- `DocumentChunkControlTag`
- `PolicyLibrary`
- `ProcedureLibrary`
- `CommonControlProvider`
- `ProjectCommonProvider`

### Assessment domain

- `Assessment`
- `ControlFinding`
- `AssessmentCriteriaPackage`
- `AssessmentEvidenceTriage`
- `ObjectiveEvidenceReview`
- `ObjectiveDetermination`
- `ControlDetermination`
- `AssessmentChallenge`
- `AssessmentRollup`
- `ControlOverride`
- `ControlActivityLog`

### Policy and governance

- `AssessmentPolicy`
- `AssessmentPolicyBucket`

### Remediation and reporting

- `RemediationReport`
- `POAM`
- `OscalExportRun`

### Assistant and AI collaboration

- `AssistantConversation`
- `AssistantContextAttachment`
- `AssistantMessage`

### System knowledge and architecture inference

- `SystemKnowledgeRun`
- `SystemKnowledgeAssertion`
- `ToolInventory`
- `ProjectProviderResponsibility`
- `ArtifactValidationRun`
- `ArtifactValidationResult`
- `PackageViabilityRun`

### Integrations and telemetry

- `IntegrationAccount`
- `IntegrationRun`
- `TelemetrySnapshot`
- `ControlTelemetryPosture`
- `DriftRecord`
- `SecurityCollector`
- `SecurityAsset`
- `SecurityScan`
- `SecurityFinding`
- `SecurityRecommendation`
- `SecurityBuildSnapshot`
- `SecurityRuntimeSnapshot`
- `VerificationCheck`
- `VerificationResult`
- `SecurityTrackedSetting`
- `SecuritySettingHistory`
- `SecurityChangeEvent`

### Ingestion pipeline v2

- `IngestionRun`
- `ParsedDocumentRecord`
- `ParsedLine`
- `ScreeningResult`
- `EvidenceUnit`
- `EvidenceClassification`
- `EvidenceEmbedding`

## 6. End-to-End User Workflows

### 6.1 Project setup and evidence onboarding

The user creates a project, uploads documents, links common control providers, and can also benefit from enterprise policy/procedure libraries that are already in scope.

Relevant APIs:

- [projects.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/projects.py)
- [documents.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/documents.py)
- [common_controls.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/common_controls.py)
- [enterprise_policies.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/enterprise_policies.py)
- [enterprise_procedures.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/enterprise_procedures.py)

### 6.2 Ingestion and evidence indexing

The ingestion pipeline converts raw files into structured evidence with provenance, classification, and embeddings.

The current repo's own ingestion spec in [atobot_ingestion_and_pre_assessment_flow_2026-03-24.md](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/docs/atobot_ingestion_and_pre_assessment_flow_2026-03-24.md) describes this well and matches the service layout.

Stages:

1. parse raw file into canonical source records
2. screen parsed units for control relevance
3. expand relevant units into larger evidence excerpts
4. classify evidence excerpts
5. generate embeddings
6. backfill legacy chunk/tag compatibility structures

Relevant service areas:

- `services/parsers/*`
- `services/ingestion/*`
- `services/rag/*`

### 6.3 Assessment execution

Assessment flow is implemented through:

- [assessments.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/assessments.py)
- [assessment_engine.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/assessment_engine.py)
- [assessment_pipeline.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/assessment_pipeline.py)
- [multistage_engine.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/multistage_engine.py)

Current model:

1. build criteria package for a control
2. preload evidence candidates
3. triage evidence into supporting, partial, contradictory, and irrelevant roles
4. run objective-level LLM analysis
5. compute control-level status in code
6. run an assessor challenge pass
7. generate the narrative
8. persist rollups and expose review surfaces

The important design decision is that the LLM is an analysis component, but final determination remains code-driven.

### 6.4 Human review and adjudication

The product includes explicit review surfaces:

- notes and resolution on findings
- override flows
- dissent review
- activity logs
- risk acceptance and POA&M paths
- retry mechanisms for failed controls

This is visible in the assessment UI and APIs and makes the system more auditable than a black-box AI scorer.

### 6.5 Closure and remediation

The product also includes targeted control closure and remediation workflows:

- [closure.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/closure.py)
- [remediation.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/remediation.py)

This allows the product to move from "identify gaps" into "generate or guide closing actions."

### 6.6 Reporting and export

Assessment outputs can be exported as:

- Excel
- Word
- PowerPoint
- JSON
- OSCAL assessment results
- OSCAL assessment plan
- OSCAL SSP
- OSCAL POA&M

Relevant APIs and services:

- [reports.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/reports.py)
- `services/reports/*`

### 6.7 System knowledge extraction

The architecture-and-tools workflow extracts structured system assertions and tool inventory from evidence.

Relevant APIs:

- [system_knowledge.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/system_knowledge.py)
- [system_profile.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/system_profile.py)

This is one of the clearest investor-facing features because it turns unstructured compliance evidence into a reviewable architecture model.

### 6.8 Continuous ATO / telemetry direction

The integration and cATO-oriented surfaces show a clear expansion path:

- connector catalog
- integration accounts
- sync runs
- posture rollups
- drift tracking
- verification checks
- app-native security posture

Relevant files:

- [integrations.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/integrations.py)
- [services/integrations.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/integrations.py)
- [services/ato_bot_security.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/ato_bot_security.py)

## 7. Ingestion and Retrieval Architecture

### Current ingestion model

The system now uses an evidence-unit-first ingestion model rather than a chunk-only model.

Core stages and tables:

1. `parsed_documents`
2. `parsed_lines`
3. `screening_results`
4. `evidence_units`
5. `evidence_classifications`
6. `evidence_embeddings`

Legacy compatibility:

- `document_chunks`
- `document_chunk_control_tags`

This hybrid design matters because it lets the product preserve old compatibility paths while shifting to a more explainable evidence pipeline.

### Retrieval architecture

The retriever can use:

- evidence-unit semantic retrieval
- classified evidence metadata
- legacy chunk retrieval when needed

Because embeddings live inside Postgres via `pgvector`, retrieval remains inside the core transactional store rather than relying on an external vector DB.

## 8. AI and LLM Runtime Architecture

### Supported provider model

The backend supports multiple providers through `services/llm/*`:

- Ollama-compatible provider
- Claude provider
- Bedrock provider

This is important strategically because it reduces vendor lock-in and allows local, hosted, or cloud-backed model choices.

### AI responsibilities are separated

The current codebase uses AI in multiple bounded roles:

1. screening parsed units for relevance
2. classifying evidence units
3. evaluating objectives against curated evidence
4. challenging control verdicts
5. writing assessment narratives
6. assisting analysts through the assistant UI
7. extracting system knowledge and architecture assertions
8. generating or composing compliance artifacts

This separation is stronger than a generic "chat with your documents" design because each model call has a defined job inside a governed workflow.

### Deterministic guardrails

A recurring architectural theme is that code wraps model output:

- policy thresholds exist outside model prompts
- final control verdicts are code-based
- evidence packet selection is deterministic and persisted
- challenge review is visible rather than silently rewriting results

That is exactly the sort of guardrail story investors and enterprise buyers will care about.

## 9. Background Processing Architecture

The background worker in [job_worker.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/job_worker.py) continuously claims pending work from the database.

Job lanes currently include:

- assessments
- remediation reports
- test dataset generation
- document ingestion

Key characteristics:

- status-driven claiming from DB rows
- `skip locked` selection to avoid double-processing
- restart recovery for interrupted work
- configurable concurrency per work type

This is a practical architecture for a product that mixes CPU work, document parsing, model calls, and export generation.

## 10. Security Architecture

### Application security controls in code

Visible controls include:

- JWT access and refresh tokens
- MFA support
- rate limiting
- RBAC
- audit middleware
- security headers middleware
- production config validation

Relevant files:

- [auth.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/api/auth.py)
- [security.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/core/security.py)
- [rbac.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/core/rbac.py)
- [security_headers.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/middleware/security_headers.py)
- [audit.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/middleware/audit.py)

### Infrastructure hardening

The compose file shows several good patterns:

- localhost binding for core services
- healthchecks
- read-only filesystems
- `cap_drop: ALL`
- `no-new-privileges`
- `tmpfs`

That said, the self-security service also reflects that hardening is still a work area, especially around container execution posture and production expectations.

### Internal self-security feature

One notable feature is that ATO Bot can evaluate aspects of its own security posture through the cATO and app-security layers.

This is a strong demo point because it shows the platform being used on itself.

## 11. Frontend Architecture and UX Surfaces

The frontend is organized into workbench-like pages rather than a minimal dashboard.

Most important user surfaces:

- `ProjectDetail`
- `AssessmentView`
- `SystemKnowledgePage`
- `IntegrationsPage`
- `CatoDashboardPage`
- `SspWorkbenchPage`
- `CommonControls`
- `EnterprisePolicies`
- `EnterpriseProcedures`
- admin runtime and prompt controls

What this means product-wise:

- users can move from evidence onboarding
- to assessment
- to system inference
- to remediation
- to export
- to live telemetry posture

inside one application.

## 12. Verified Strengths

### 12.1 Strong architectural separation of concerns

The codebase has clear separation between:

- ingestion
- retrieval
- assessment
- adjudication policy
- remediation
- assistant
- telemetry
- export

### 12.2 Better-than-average AI governance pattern

The system does not simply trust the model to make final compliance decisions. It persists evidence selection, objective results, challenge notes, and control determinations separately.

### 12.3 Real evidence provenance model

The move from raw documents to parsed lines to evidence units is one of the strongest technical choices in the platform.

### 12.4 Built-in path from point-in-time assessment to continuous posture

The integration and telemetry layers create a credible path from static artifact review to continuous ATO support.

### 12.5 Investor-friendly extensibility

The connector catalog and provider abstraction indicate a platform strategy rather than a one-off tool.

## 13. Verified Risks and Limitations

These are not reasons the product is weak, but they matter for positioning.

### 13.1 The platform is broad

This is a large surface area for a product at this stage:

- ingestion
- assessment
- closure
- telemetry
- assistant
- reporting
- SSP
- cATO

For investors, this should be framed as a platform opportunity, but for demos it means you should focus hard on the few strongest workflows.

### 13.2 Hybrid old/new ingestion model

The code still maintains legacy chunk/tag compatibility alongside the newer evidence-unit model. That is understandable, but it means the architecture is in transition.

### 13.3 Some cATO integrations are still scaffolding-oriented

The connector framework is real, but parts of the current UX and service language still describe dry-run or planned states. It should be presented as an expansion lane, not oversold as fully mature production telemetry coverage.

### 13.4 Large startup/lifespan responsibility in `main.py`

`main.py` currently performs significant schema bootstrapping and migration-like work in the application lifespan. That is operationally pragmatic, but over time it should likely be reduced and formalized into migrations/services.

### 13.5 Presentation risk

Because the product does many things, it would be easy to demo it as "complex" instead of "inevitable." The solution is narrative discipline in the presentation.

## 14. Recommended Positioning

The cleanest way to describe ATO Bot is:

> ATO Bot is an AI-assisted compliance operations platform that converts raw security artifacts into traceable evidence, performs assessor-aligned control evaluation, supports human review and remediation, and lays the foundation for continuous authorization posture.

That is stronger than calling it:

- a chatbot
- a document generator
- a policy tool
- a GRC dashboard

because the actual codebase spans all of those but is anchored by the evidence pipeline.

## 15. Recommended Architecture Narrative for Investors

Use this sequence:

1. ATO evidence is fragmented and expensive to review manually.
2. Most AI compliance tools stop at chat or document generation.
3. ATO Bot turns documents into structured evidence with provenance.
4. ATO Bot evaluates controls in stages and keeps the model inside a governed workflow.
5. Analysts can review, challenge, override, remediate, and export.
6. The same platform extends toward live telemetry and continuous ATO.

That sequence matches the repo better than a generic "AI for compliance" pitch.

## 16. Best Demo Surfaces in the Current App

If you only show a few screens, I would prioritize:

1. `Project Detail`
- shows evidence onboarding, processing state, assessments, and scope assembly

2. `Assessment View`
- best proof that the system is not a black box
- shows criteria, evidence triage, objective review, determination, and challenge

3. `Architecture & Tools`
- strong investor demo because it turns evidence into an inferred system model

4. `SSP Workbench`
- shows downstream document production and operational utility

5. `cATO Dashboard` or `Live Integrations`
- show as "where this platform is going next" and only if the data is clean enough

## 17. Bottom Line

ATO Bot already contains the architecture of a serious compliance platform:

- evidence ingestion with provenance
- semantic retrieval
- staged control assessment
- deterministic adjudication around AI
- human review and remediation
- reporting and OSCAL export
- system architecture inference
- early continuous authorization telemetry primitives

The strongest part of the platform is not any one LLM call. It is the staged evidence and adjudication architecture that puts those model calls inside a governed compliance workflow.
