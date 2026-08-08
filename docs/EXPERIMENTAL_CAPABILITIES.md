# Experimental Capability Inventory

This is the disposition ledger for capabilities that are not part of ATO Bot's supported open-source core. The code is preserved during maturity work. Nothing in this document authorizes deletion.

Runtime maturity and enablement are published by `GET /api/meta/features`. The backend registry is authoritative; a disabled backend capability cannot be exposed by a frontend build option.

## Disposition Rules

- `supported`: documented, tested, and included in normal product claims.
- `beta`: usable evaluation capability with known maturity or test gaps.
- `experimental`: disabled by default and excluded from standard claims and navigation.
- `deprecated`: retained compatibility path with a supported replacement.
- `unreachable`: source exists but no application route or supported entry point reaches it.

Final decisions are deferred until the P0/P1 cleanup is complete. Each item will then be marked `retain`, `promote`, `remove-before-publication`, or `defer-removal`.

## Experimental: External Integration Connectors

| Attribute | Inventory |
| --- | --- |
| Runtime key | `external_integrations` |
| Enablement | `ENABLE_EXPERIMENTAL_CATO=true`; disabled by default |
| UI route | `/projects/:id/integrations` |
| API root | `/api/projects/{project_id}/integrations` |
| API operations | catalog, accounts, runs, posture, ATO Bot security posture, create/test/sync/delete account |
| Services | `app/services/integrations.py`, `app/services/ato_bot_security.py` |
| Tables | `integration_accounts`, `integration_runs`, `telemetry_snapshots`, `control_telemetry_posture`, `drift_records` |
| Dependencies | Project access/RBAC, worker execution, connector credentials, telemetry models |
| Known gaps | Several connectors support dry-run/scaffold behavior rather than complete provider APIs; provider-specific authentication, pagination, failure semantics, and test coverage are incomplete. |
| Removal impact | Removes connector configuration and imported posture history. Security telemetry not sourced through integrations can remain. |

## Experimental: Continuous Telemetry and Drift

| Attribute | Inventory |
| --- | --- |
| Runtime key | `continuous_telemetry` |
| Enablement | Shares `ENABLE_EXPERIMENTAL_CATO`; disabled by default |
| UI surface | cATO dashboard tactical posture panels |
| API root | `/api/projects/{project_id}/security` and integration posture APIs |
| Services | `app/services/security_telemetry.py`, `app/services/ato_bot_security.py`, collector ingestion services |
| Tables | `security_collectors`, `security_collector_nonces`, `security_assets`, `security_scans`, `security_findings`, `security_recommendations`, `security_build_snapshots`, `security_runtime_snapshots`, `security_tracked_settings`, `security_setting_history`, `security_change_events` |
| Dependencies | Signed collector payloads, Docker/runtime inspection, integration data, project access controls |
| Known gaps | Monitoring coverage and source semantics vary by deployment. The present surface cannot support a general continuous-authorization claim. Collector and container-security paths need independent threat modeling and broader tests. |
| Removal impact | Removes continuous posture, drift, collector, and tactical security views. Core evidence ingestion and point-in-time assessment remain. |

## Experimental: cATO Dashboard

| Attribute | Inventory |
| --- | --- |
| Runtime key | `cato_dashboard` |
| Enablement | Shares `ENABLE_EXPERIMENTAL_CATO`; disabled by default |
| UI route | `/projects/:id/cato-dashboard` |
| Frontend | `frontend/src/pages/CatoDashboardPage.jsx` |
| APIs | Aggregates integration and `/security` endpoints listed above |
| Known gaps | The page is a large experimental aggregation over incomplete connector and telemetry semantics. It is not evidence of continuous authorization or an authorization decision. |
| Removal impact | Removes the dashboard only; underlying experimental services and data require separate disposition. |

## Beta: Calibration and Synthetic Datasets

| Attribute | Inventory |
| --- | --- |
| Runtime keys | `calibration_harness`, part of `human_artifact_generation` |
| UI routes | `/projects/:id/calibration`, `/projects/:id/test-dataset` |
| API roots | `/api/projects/{project_id}/calibration`, `/api/projects/{project_id}/test-dataset` |
| Services | `app/services/calibration_harness.py`, package and human-artifact generators |
| Tables | `calibration_suites`, `calibration_cases`, `calibration_runs`, `calibration_case_results`, `test_dataset_jobs`, artifact-validation tables |
| Known gaps | Calibration data is not populated by default and release regression gates are not yet enforced. Synthetic artifacts must never be confused with operational evidence. |
| Removal impact | Removes evaluation and test-package generation, not production assessment execution. |

## Beta: System Knowledge and Architecture Inventory

| Attribute | Inventory |
| --- | --- |
| Runtime key | `system_knowledge` |
| UI route | `/projects/:id/architecture-tools` |
| API root | `/api/projects/{project_id}/system-knowledge` |
| Services | `app/services/system_knowledge.py` and provider-responsibility services |
| Tables | `system_knowledge_runs`, `system_knowledge_assertions`, `tool_inventory`, provider-responsibility records |
| Known gaps | Extracted assertions require human confirmation and should not become assessment facts merely because a model proposed them. |
| Removal impact | Removes inferred architecture/tool inventory and inheritance suggestions. Evidence assessment remains. |

## Beta: Cyber Assistant and Human-Style Artifacts

| Attribute | Inventory |
| --- | --- |
| Runtime keys | `cyber_assistant`, `human_artifact_generation` |
| UI surfaces | Assistant drawer, selected-control review, remediation artifact actions |
| APIs | Assistant, AI-assist, closure, remediation, and artifact routes |
| Services | Purpose-routed LLM runtime, closure/remediation services, `human_artifact_generator.py` |
| Tables | Assistant conversations/messages/attachments, generated documents, artifact approvals |
| Known gaps | Generated content requires an enforceable draft/approval/evidence-eligibility state machine and broader prompt/model regression coverage. |
| Removal impact | Removes conversational help and generated drafts but not deterministic findings or manual remediation records. |

## Deprecated Compatibility Paths

| Capability | Replacement | Current behavior |
| --- | --- | --- |
| `/dashboard` | `/projects` | Redirect only |
| `/admin/ingestion-config` | `/admin/ai-runtime` | Redirect only |
| Legacy chunks/tags | Evidence units and classifications | Data compatibility path remains |
| Legacy local-storage tokens | Session-storage token handling | Migrated/cleared by client compatibility logic |

## Unreachable Frontend Components

These components have no route or import in the current application. They are preserved until final disposition review:

- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/pages/security/POAM.jsx`
- `frontend/src/pages/security/Scorecard.jsx`
- `frontend/src/pages/security/SecurityEvents.jsx`

Their existence does not make them product capabilities. The corresponding security API groups may still support the routed Security Ops dashboard and therefore require separate analysis before any removal.

## Unreachable Backend Implementations

These implementations are preserved for the final disposition review but are not called by the supported runtime:

- `app/services/test_dataset_generator.py::_generate_legacy_test_dataset` is the superseded synthetic-package generator. The later `generate_test_dataset` implementation is the active worker entry point. The legacy implementation must be compared for unique behavior before removal.

## Final Disposition Checklist

For every entry above, the publication review must record:

- final decision and owner;
- code, route, API, table, migration, dependency, documentation, and test impact;
- data-retention or export requirement;
- upgrade behavior for existing deployments;
- security review result;
- release version in which the decision takes effect.
