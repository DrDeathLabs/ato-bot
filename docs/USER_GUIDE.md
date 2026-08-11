# ATO Bot User Guide

This is the role-based product manual for assessors, reviewers, FISMA System Owners, control owners, administrators, and operators. ATO Bot supports a qualified assessment team; it does not make an authorization decision.

## 1. Core Concepts and Roles

| Concept | Meaning |
| --- | --- |
| Project | The system boundary containing profile data, libraries, assessments, findings, reports, and audit history. |
| System profile | Scope and environment facts used to interpret evidence and assessment planning. |
| FISMA System Owner | The accountable owner for the system being assessed; it is separate from a legacy technical project-owner field. |
| Evidence library | Project, common-control, enterprise-policy, and enterprise-procedure source records. |
| Assessment plan | The approved scope, methods, objects, depth, coverage, tailoring, runtime, and frozen evidence context for a run. |
| Finding | A persisted control-level determination with objective support, citations, gaps, confidence, and review state. |
| Review state | Draft, needs review, dissent, approved, or finalized governance state. |
| Remediation artifact | A generated draft or control-owner submission that is not eligible evidence until approved and explicitly marked eligible. |

Typical responsibilities are: the assessor performs and records assessment work; the reviewer challenges and approves; the FISMA System Owner accepts system-level risk and scope; control owners provide implementation evidence and closure material; administrators manage access and configuration; operators maintain services, storage, and model connectivity.

## 2. First Login and Navigation

**Owner:** all users. **Entry:** the application URL. **Inputs:** active credentials and assigned role. **Behavior:** login creates the application session and redirects to Projects; the left navigation exposes only permitted workspaces. **Expected result:** the user can see authorized projects without seeing another project's evidence. **Failure handling:** check service health, account status, lockout, and stale browser session; administrators should reset rather than repeatedly retry a locked account. **Downstream:** every later action is associated with the authenticated user and audit history.

Sign out from the left navigation. Treat the browser session as a session, not as a stored credential. Never paste passwords or API keys into documents, assistant prompts, or evidence.

## 3. Create a Project and System Boundary

**Owner:** assessor with the FISMA System Owner. **Entry:** Projects > New Project. **Inputs:** system name, description, system type, impact baseline, boundary characteristics, owner assignments, and inherited/common-control assumptions. **Behavior:** ATO Bot creates the project container and later uses the profile to scope evidence and assessment plans. **Expected result:** the project has an identifiable boundary and accountable owner. **Failure handling:** correct missing required fields; do not begin assessment work in a project whose owner or baseline is unknown. **Downstream:** documents, assessments, findings, outputs, and audit records are project-scoped.

Complete the System Profile on the project detail page. Record hosting, ownership, physical/wireless/mobile/removable-media/external-connection/public-access characteristics, impact, system purpose, and boundary notes. Assign the FISMA System Owner from the accountability section. The selected user should be active and have the system-owner role.

## 4. Libraries and Evidence Intake

**Owner:** control owners and assessors. **Entry:** project Documents area or shared library navigation. **Inputs:** current policies, procedures, plans, inventories, configuration exports, logs, assessment records, findings, POA&M material, and common-control or enterprise records. **Behavior:** upload stores the source file, associates it with the project/library, and starts the ingestion pipeline. **Expected result:** the file appears with a stable source record and processing state. **Failure handling:** check file type/size, storage permissions, worker health, and retry only failed items; do not treat an upload as usable evidence until readiness is reviewed. **Downstream:** the source can produce parsed content, evidence units, control tags, embeddings, and citations.

Use the correct library:

- **Project:** system-specific implementation evidence.
- **Common Controls:** provider evidence that can be inherited by multiple systems.
- **Enterprise Policies:** organization-wide policy evidence.
- **Enterprise Procedures:** organization-wide operating procedures.

## 5. Ingestion Readiness

**Owner:** assessor or ingestion operator. **Entry:** project Documents > pipeline/readiness details. **Inputs:** uploaded source, parser output, classification, extracted units, duplicate signals, and embedding status. **Behavior:** ATO Bot parses the file, screens relevance, expands context, classifies evidence, creates evidence units, tags controls, generates embeddings when configured, and retains provenance. **Expected result:** a source is indexed and usable for assessment with readable lineage to the original file. **Failure handling:** resolve failed or degraded stages, review low-confidence classification, remove duplicates, and rerun processing; a degraded fallback must not silently become assessment evidence. **Downstream:** only the reviewed, frozen evidence scope is available to a run.

Readiness is a human checkpoint. Review the document count, indexed/processing/failed states, duplicate notices, unsupported content, source owner/date, scope, and whether the evidence actually describes present behavior rather than a future plan.

## 6. Plan, Tailor, and Approve an Assessment

**Owner:** assessment lead and reviewer; System Owner confirms scope. **Entry:** project detail > Start Assessment. **Inputs:** baseline, selected controls, tailoring/ODPs, inherited and compensating decisions, methods, objects, depth, coverage, evidence scope, runtime, model, and context strategy. **Behavior:** the plan records the intended assessment and freezes its evidence fingerprint when execution starts. **Expected result:** an approved plan exists before a run. **Failure handling:** correct scope or approval omissions; if policy, model, prompt, retrieval, or evidence scope changes, create a new plan/run. **Downstream:** criteria packages and objective tasks are constructed from the approved plan.

Use the NIST SP 800-53A methods **Examine**, **Interview**, and **Test**; define assessment objects, depth, coverage, and any organization-defined parameters. The approval checkbox is an intentional maturity gate introduced during the open-source readiness work. It means the plan is approved for execution, not that the final findings are approved.

## 7. Execute and Monitor the Assessment

**Owner:** assessor/operator. **Entry:** approved plan > Start. **Inputs:** frozen evidence scope, criteria package, model configuration, policy version, and worker capacity. **Behavior:** the worker assembles objective context, evaluates evidence, records narratives and citations, applies deterministic adjudication, and writes rollups. **Expected result:** queued, running, paused, complete, or failed state with persisted progress. **Failure handling:** pause when needed, resume the same scope, retry failed controls, and inspect worker/backend health before creating another run. **Downstream:** findings and review queues become available.

The run should not be treated as final because all controls have a machine result. Required interviews, technical tests, tailoring, dissent resolution, notes, approvals, and risk/POA&M decisions remain human work.

## 8. Assessment Workspace

**Owner:** assessor and reviewer. **Entry:** project assessment link. **Inputs:** run state and persisted findings. **Behavior:** the workspace separates context without losing the assessment route. **Expected result:** a reviewer can move through the run and return to the project or prior context without stale selected-control state. **Failure handling:** clear selection, return to Findings, or reload the assessment route; report a mismatch if counts differ between tabs. **Downstream:** selected control review and exports use the same persisted state.

- **Overview:** status, passed controls, blockers, review signals, next actions, notes, and evidence posture.
- **Findings / Flat:** one row per finding with search, family, determination, needs-review, dissent, changed, and other filters.
- **Findings / Family:** grouped review by NIST family.
- **Evidence:** selected-control citations, excerpts, provenance, gaps, and quality signals.
- **Outputs:** Word, Excel, JSON, SAR/SSP/POA&M-oriented and OSCAL-oriented output status.
- **Advanced:** objective coverage, policy mechanics, challenge/dissent detail, delta, and traceability.

## 9. Review Findings and a Selected Control

**Owner:** assessor; reviewer validates. **Entry:** Findings row, Overview attention tile, or passed-control pill. **Inputs:** control status, confidence, narrative, objective results, citations, gaps, dissent, notes, and activities. **Behavior:** a selected-control drawer presents summary, evidence, advanced detail, and remediation without requiring a separate page. **Expected result:** the reviewer can explain why the result was reached and what happens next. **Failure handling:** clear the selection, use the drawer close control, or return to flat Findings; investigate count mismatches such as a gap badge not matching listed gaps. **Downstream:** notes, activity results, challenge resolution, manual review, and remediation are recorded against the control.

Review the distinction between compliant, partial, non-compliant, N/A, needs review, and AI dissent. A dissent is a challenge signal, not an automatic status change. Confidence is a model/evidence quality signal, not assessor approval.

## 10. Record Examine, Interview, Test, and Review Actions

**Owner:** qualified assessor or reviewer. **Entry:** selected control > activity or review action. **Inputs:** activity method, objects, procedure, performer, date, result, notes, and supporting evidence. **Behavior:** the application persists the activity record and associates it with the control/objective. **Expected result:** the record says what was examined, whom/what was interviewed, or what was tested and what the assessor concluded. **Failure handling:** do not mark a required activity complete without a real result; correct the activity record or escalate missing evidence. **Downstream:** finalization and report reconciliation use the activity state.

## 11. How to Close a Gap

**Owner:** control owner proposes; assessor validates. **Entry:** selected control > How to Close This Gap. **Inputs:** discovered gaps, deterministic closure guidance, remediation plan, evidence expectations, recommended artifact types, collection guidance, and success criteria. **Behavior:** the app presents a control-specific work plan rather than only a raw finding. **Expected result:** the control owner understands the action, owner, record to produce, and evidence needed for closure. **Failure handling:** replace generic collection guidance with the actual product, repository, role, cadence, and record location; do not accept a generic template as proof. **Downstream:** approved remediation artifacts and POA&M milestones can be linked to the control.

Use the guidance as a proposal. The assessor determines whether the new evidence proves current implementation and satisfies each applicable assessment objective.

## 12. Generated Artifacts and Evidence Eligibility

**Owner:** control owner drafts; reviewer approves. **Entry:** remediation or artifact action. **Inputs:** control gaps, approved context, requested artifact type, owner, dates, and content constraints. **Behavior:** the model may produce a draft document, plan, procedure, or evidence package. **Expected result:** the artifact is visibly marked draft until a human reviews and approves it. **Failure handling:** reject unsupported, inaccurate, future-state, or over-claiming content; never promote a generated document automatically. **Downstream:** only explicitly approved and eligible artifacts may be considered in a later assessment scope.

## 13. POA&M, Risk, Closure, and Reports

**Owner:** System Owner, control owner, assessor, and reviewer. **Entry:** Outputs or remediation workflow. **Inputs:** findings, owner, milestone, schedule, risk response, residual risk, acceptance decision, and closure evidence. **Behavior:** the app aggregates control action into remediation and report views. **Expected result:** a POA&M or closure record is specific enough to track ownership and acceptance. **Failure handling:** resolve missing ownership, dates, risk characterization, or evidence; reconcile report counts before distribution. **Downstream:** reports, exports, and finalization reflect the controlled state.

Available output families include Word, Excel, JSON, SAR-oriented, SSP-oriented, POA&M-oriented, and OSCAL-oriented packages depending on run state and enabled features. Schema-valid OSCAL does not prove that an interview or test occurred.

## 14. Administrator Workflows

- **Users and roles:** create or deactivate users, assign least-privilege roles, manage passwords/MFA, and keep assessor/reviewer separation where required.
- **System ownership:** assign the active FISMA System Owner explicitly; do not rely on an old project-owner field.
- **Assessment policy:** review buckets, thresholds, weights, overrides, and version before a controlled run.
- **AI Runtime:** configure provider, model, embeddings, context, timeout, and retry policy outside active runs.
- **Prompt Manager:** change named prompt purposes under change control and rerun calibration/regression when behavior changes.
- **Audit:** review security and project audit logs; do not edit assessment history directly in the database.
- **Features:** use `GET /api/meta/features` as the authority for supported, beta, experimental, deprecated, and disabled capabilities.

## 15. Frequently Asked Questions

**Can ATO Bot perform a full 800-53 assessment?** It can orchestrate and document a full control/objective assessment workflow when a qualified team supplies scope, evidence, interviews, tests, review, and approvals. It does not autonomously perform every assessment activity or authorize the system.

**Does a compliant machine result mean the control passed?** No. It is a draft determination until required evidence, activities, review, dissent resolution, and approvals are complete.

**Can a generated procedure be used as evidence?** Not automatically. It is a draft until reviewed and explicitly approved/eligible.

**What should I do when ingestion is degraded?** Stop using that source for final assessment purposes, fix or rerun ingestion, and record the readiness decision.

**What is the difference between a System Owner and control owner?** The FISMA System Owner is accountable for the system and authorization package; a control owner is responsible for implementing or providing evidence for one or more controls.

## 16. Unsupported or Human-Required Activities

ATO Bot does not replace assessor judgment, independently conduct interviews, automatically perform technical tests, establish organizational risk tolerance, accept residual risk, or make an authorization decision. External connectors and optional security-posture surfaces remain experimental or disabled by default. Operational observability in the supported product refers to application health, job state, audit activity, and processing status; it is not cATO telemetry. See [Limitations](LIMITATIONS.md) and [Experimental Capabilities](EXPERIMENTAL_CAPABILITIES.md).

## Screenshot Reference

The focused public screenshot set is in [assets/README.md](assets/README.md). It includes login, project/system profile, evidence readiness, assessment planning, Overview, Findings, selected-control review, remediation guidance, activities, and Outputs examples using synthetic E2E data.
