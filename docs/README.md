# ATO Bot Documentation

ATO Bot is a human-in-the-loop NIST SP 800-53 assessment workbench. The documentation is organized for three audiences:

- Operators and assessors who need to run an assessment.
- Administrators who need to configure users, models, policy, and deployment.
- Developers and reviewers who need the architecture, data flow, and release boundary.

## Start Here

1. [User Guide](USER_GUIDE.md) - day-to-day use from project creation through reporting.
2. [Assessment Workflow](ASSESSMENT_WORKFLOW.md) - how a full assessment is scoped, executed, reviewed, and finalized.
3. [Ingestion Guide](INGESTION_GUIDE.md) - how uploaded documents become assessment-ready evidence.
4. [Remediation and Outputs](REMEDIATION_AND_OUTPUTS.md) - how findings become closure guidance, artifacts, and reports.

## Technical References

- [Architecture](ARCHITECTURE.md) - current runtime components, data model, and trust boundaries.
- [Administration](ADMINISTRATION.md) - users, roles, system ownership, runtime, policy, and audit operations.
- [Deployment](DEPLOYMENT.md) - local Docker, GHCR images, upgrades, backups, and health checks.
- [Verified E2E Workflows](E2E_VERIFIED_WORKFLOWS.md) - what has been exercised in the live development stack and what requires additional release validation.
- [Feature Status](FEATURE_STATUS.md) - supported, beta, experimental, and deprecated capability status.
- [Limitations](LIMITATIONS.md) - the assessment boundary and known constraints.
- [Threat Model](THREAT_MODEL.md) - security assumptions and trust boundaries.
- [Upgrading](UPGRADING.md) - the short upgrade procedure.
- [Agentic Flows](atobot_agentic_flows_2026-05-11.md) - detailed model-driven workflow reference.
- [Ingestion and Pre-Assessment Flow](atobot_ingestion_and_pre_assessment_flow_2026-03-24.md) - exhaustive pipeline reference.
- [Assessment Policy System](assessment_policy_system_spec.md) - policy buckets, thresholds, overrides, and versioning.

## White Paper

The formatted technical white paper is the long-form system reference:

`ATO_Bot_Technical_White_Paper_2026-07-06.docx`

The release source includes this named white paper as an intentional documentation artifact. Other generated binary deliverables remain outside the normal source allowlist.

## Product Boundary

ATO Bot produces evidence analysis and draft control determinations. It does not replace a qualified assessor, perform every required interview or technical test, or make an authorization decision. Final findings must be reviewed, supported by appropriate assessment activities, and approved under the adopting organization's process.
