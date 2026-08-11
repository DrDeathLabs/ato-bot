# ATO Bot Documentation

ATO Bot is a human-in-the-loop NIST SP 800-53 assessment platform. These docs describe the supported product boundary, how to operate it, and where human assessment authority remains mandatory.

## New Users

- [README](../README.md) - product purpose, installation choices, limits, and repository map.
- [Installation](INSTALLATION.md) - GHCR, source-build, configuration, and first health check.
- [User Guide](USER_GUIDE.md) - role-based walkthrough from first login through outputs.

## Assessors and Reviewers

- [Assessment Operations](ASSESSMENT_OPERATIONS.md) - how to use ATO Bot inside a qualified 800-53A assessment.
- [Assessment Workflow](ASSESSMENT_WORKFLOW.md) - plan, run, review, finalize, and reconcile.
- [Ingestion Guide](INGESTION_GUIDE.md) - evidence preparation and readiness.
- [Remediation and Outputs](REMEDIATION_AND_OUTPUTS.md) - closure guidance, artifacts, POA&M, and reports.

## System Owners and Control Owners

- [User Guide](USER_GUIDE.md) - project boundary, FISMA System Owner, libraries, review, and next actions.
- [Remediation and Outputs](REMEDIATION_AND_OUTPUTS.md) - gap closure and control-owner deliverables.
- [Limitations](LIMITATIONS.md) - what ATO Bot cannot establish on its own.

## Administrators

- [Administration](ADMINISTRATION.md) - users, roles, ownership, policy, prompts, runtime, and audit.
- [Production](PRODUCTION.md) - network, secrets, models, storage, monitoring, and operations.
- [Feature Status](FEATURE_STATUS.md) - supported, beta, experimental, deprecated, and disabled states.

## Operators

- [Installation](INSTALLATION.md)
- [Production](PRODUCTION.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Backup and Restore](BACKUP_AND_RESTORE.md)
- [Upgrading](UPGRADING.md)
- [Installation Audit](INSTALLATION_AUDIT_2026-08-11.md)

## Developers

- [Development](DEVELOPMENT.md) - repository layout, local workflow, generated data, and secrets.
- [Testing](TESTING.md) - backend, frontend, Playwright, migrations, scans, and release checks.
- [Architecture](ARCHITECTURE.md) - runtime components, data model, and trust boundaries.

## Security and Release Reviewers

- [Threat Model](THREAT_MODEL.md)
- [Open Source Readiness](OPEN_SOURCE_READINESS.md)
- [Open Source Change Review](OPEN_SOURCE_CHANGE_REVIEW_2026-08-08.md)
- [Live E2E Assessor Test](ATO_BOT_LIVE_E2E_ASSESSOR_TEST_2026-08-08.md)
- [Limitations](LIMITATIONS.md)
- [Experimental Capabilities](EXPERIMENTAL_CAPABILITIES.md)

## Technical References

- [Technical White Paper](ATO_Bot_Technical_White_Paper_2026-07-06.docx)
- [Agentic Flows](atobot_agentic_flows_2026-05-11.md)
- [Ingestion and Pre-Assessment Flow](atobot_ingestion_and_pre_assessment_flow_2026-03-24.md)
- [Assessment Policy System](assessment_policy_system_spec.md)
- [Adjudication Engine Specification](adjudication_engine_spec.md)
- [Deployment](DEPLOYMENT.md)
- [Verified E2E Workflows](E2E_VERIFIED_WORKFLOWS.md)

## Route and Capability Map

| Route or surface | Audience | Capability status | Primary documentation |
| --- | --- | --- | --- |
| `/login` | Everyone | Supported | [User Guide](USER_GUIDE.md) |
| `/projects` | Assessors, owners | Supported | [User Guide](USER_GUIDE.md) |
| `/projects/:id` | Assessors, owners | Supported | [User Guide](USER_GUIDE.md) |
| `/projects/:id/assessments/:assessmentId` | Assessors, reviewers | Supported | [Assessment Operations](ASSESSMENT_OPERATIONS.md) |
| `/common-controls` | Admins, assessors | Supported | [Administration](ADMINISTRATION.md) |
| `/enterprise-policies` | Admins, assessors | Supported | [Administration](ADMINISTRATION.md) |
| `/enterprise-procedures` | Admins, assessors | Supported | [Administration](ADMINISTRATION.md) |
| `/control-catalog` | Assessors, reviewers | Supported | [Assessment Workflow](ASSESSMENT_WORKFLOW.md) |
| `/assessment-policy` | Admins, assessment leads | Supported | [Administration](ADMINISTRATION.md) |
| `/projects/:id/ssp-workbench` | Assessors, system owners | Supported with review | [User Guide](USER_GUIDE.md) |
| `/projects/:id/architecture-tools` | Assessors, system owners | Beta | [Feature Status](FEATURE_STATUS.md) |
| `/projects/:id/calibration` | Developers, model reviewers | Beta | [Testing](TESTING.md) |
| `/projects/:id/test-dataset` | Developers, model reviewers | Beta | [Testing](TESTING.md) |
| `/users` | Administrators | Supported | [Administration](ADMINISTRATION.md) |
| `/admin/dashboard` | Security administrators | Supported | [Administration](ADMINISTRATION.md) |
| `/admin/prompts` | Runtime administrators | Supported with change control | [Administration](ADMINISTRATION.md) |
| `/admin/ai-runtime` | Runtime administrators | Supported with change control | [Production](PRODUCTION.md) |
| `/projects/:id/audit-log` | Reviewers, admins | Supported | [Administration](ADMINISTRATION.md) |
| `/security/audit-log` | Security administrators | Supported | [Administration](ADMINISTRATION.md) |
| `/projects/:id/integrations` | Operators | Experimental, disabled by default | [Experimental Capabilities](EXPERIMENTAL_CAPABILITIES.md) |
| `/projects/:id/cato-dashboard` | Operators | Experimental, disabled by default | [Experimental Capabilities](EXPERIMENTAL_CAPABILITIES.md) |
| `/dashboard` | Legacy users | Deprecated redirect | [Feature Status](FEATURE_STATUS.md) |
| `/admin/ingestion-config` | Legacy users | Deprecated redirect | [Feature Status](FEATURE_STATUS.md) |

## Documentation Boundary

The docs intentionally do not claim autonomous authorization, automatic interviews, automatic technical testing, or production-ready cATO. In supported workflows, operational observability means application health, job state, audit activity, configuration changes, and processing status. It does not mean continuous authorization telemetry. Date-stamped handoffs, presentations, and historical reviews remain available as references but are not the primary operator path.
