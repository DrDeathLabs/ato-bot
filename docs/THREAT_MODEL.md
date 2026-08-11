# Threat Model

## Protected Assets

- Uploaded assessment evidence and derived evidence units
- Credentials, refresh sessions, model-provider secrets, and MFA material
- Assessment plans, findings, dissent records, approvals, POA&M data, and reports
- Audit history and evidence provenance
- Generated artifacts awaiting review

## Trust Boundaries

- Browser to nginx/frontend
- nginx to FastAPI
- FastAPI and worker to PostgreSQL/Redis
- Application to external model providers
- Uploaded documents and generated model output entering trusted application state
- Experimental collectors/connectors entering the project boundary

## Principal Threats and Controls

| Threat | Primary controls |
| --- | --- |
| Credential theft or token replay | Short-lived typed JWTs, audience/issuer validation, refresh revocation, MFA support, rate limiting |
| Cross-project data access | Project-scoped RBAC dependencies and isolation tests |
| Malicious or misleading evidence | File validation, staged ingestion, provenance, contradiction handling, human review |
| Prompt injection/model manipulation | Narrow purpose routing, structured outputs, deterministic validation, persisted source citations, human authority |
| AI-generated evidence laundering | Draft quarantine, approval chain, explicit evidence-eligibility decision |
| Assessment tampering | Frozen plan scope, immutable approval snapshots, audit events, finalization blockers |
| Dependency/container compromise | Dependency audits, CodeQL, secret scanning, Trivy, SBOM, signed immutable release images |
| Stale backend resolution | Docker DNS re-resolution in the ATO Bot nginx container |

## Residual Risks

- Model providers may retain or process submitted evidence according to their own service terms. Operators must select and configure providers appropriate to data sensitivity.
- A privileged database or host administrator can alter data outside application controls. Production deployments require infrastructure audit, backup, and access controls.
- Experimental connector and optional security-posture paths have not completed the same maturity gate as core assessment functions and remain disabled by default. They must not be interpreted as continuous authorization monitoring.
