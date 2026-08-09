# ATO Bot User Guide

This guide describes the supported operator path through ATO Bot. The product is designed for assessors, system owners, security analysts, and reviewers working together. It is not an autonomous authorization system.

## 1. Sign In

Open the configured ATO Bot URL and sign in with an active account. The application redirects authenticated users to the Projects workspace.

If login fails:

- Confirm the account is active and the password is correct.
- Check that the backend and frontend containers are healthy.
- Do not repeatedly retry a locked account; use the administrator password reset path.
- Verify the browser is using the current URL and not a stale cached tab.

Sign out from the left navigation when finished. Tokens are held in the browser session rather than treated as a permanent local credential.

## 2. Create a Project

1. Open **Projects**.
2. Select **New Project**.
3. Enter the system name, description, system type, and impact baseline.
4. Assign the **FISMA System Owner** when the accountable owner is known.
5. Create the project.

The project is the system boundary for documents, assessments, findings, notes, reports, and audit history. The legacy project owner and the explicit FISMA System Owner are separate accountability concepts; assign both when the operating model requires it.

## 3. Define the System Profile

Open the project detail page and complete the system profile before assessment execution. Capture the information that determines scope and interpretation, including system purpose, environment, impact level, applicable baseline, inherited controls, common-control providers, and organization-defined decisions.

The profile is not a replacement for an approved assessment plan. It provides the system context used by the plan and later assessment reasoning.

## 4. Load Evidence

Evidence can be uploaded into the project library or maintained in shared libraries:

- Project documents.
- Common-control provider documents.
- Enterprise policies.
- Enterprise procedures.

Upload current policies, procedures, plans, inventories, configuration exports, logs, assessment records, findings, POA&M material, and other artifacts that support the system boundary. Prefer evidence that identifies an owner, effective date, review date, system scope, implementation state, and source record.

After upload, the document moves through `pending`, `processing`, `indexed`, or `failed`. Open the pipeline details when you need to see the current stage. Do not use a failed or degraded ingestion result as assessment evidence until it has been reprocessed and reviewed.

## 5. Review Ingestion Readiness

The pipeline parses the file, screens content for relevance, expands context, classifies evidence, creates evidence units, generates embeddings where configured, and preserves source provenance. Review duplicate notices, failed stages, unsupported content, and low-confidence classifications before starting an assessment.

The document list and pipeline report are the operator's readiness checkpoint. A document being uploaded does not mean that it is assessment-ready.

## 6. Create and Approve an Assessment Plan

From the project detail page, create an assessment for the selected baseline and model/runtime configuration. Review the plan fields before execution:

- Scope and system boundary.
- Assessment methods: Examine, Interview, and Test.
- Assessment objects.
- Depth and coverage.
- Baseline, tailoring, inherited controls, and common-control assumptions.
- Runtime, model, context strategy, and execution mode.
- Evidence scope that will be frozen for the run.

The current release requires explicit plan approval before execution. Select the approval checkbox only after the scope and execution design have been reviewed. This gate was introduced during the open-source maturity work to prevent an unreviewed scope from becoming a purported final assessment.

## 7. Run the Assessment

Start the approved assessment from the project detail page. The worker builds criteria packages, loads the frozen evidence scope, routes evidence to controls and objectives, evaluates objectives, applies code-governed control adjudication, runs challenge review, writes narratives, and persists rollups.

Use the assessment status and progress indicators to distinguish queued, running, paused, complete, and failed states. If a run fails, use retry for failed controls rather than starting an unrelated duplicate run. A retry must preserve the assessment evidence scope and invalidate stale review state where content changes.

## 8. Review the Assessment Workspace

The assessment workspace is organized into five contexts:

- **Overview**: readiness, status, passed controls, blockers, review signals, and next actions.
- **Findings**: flat or family-organized control findings with filters.
- **Evidence**: citations, excerpts, evidence quality, gaps, and selected-control traceability.
- **Outputs**: reports, remediation documents, and export status.
- **Advanced**: policy mechanics, objective coverage, challenge detail, delta review, and internal traceability.

Use the assessment workspace tabs for navigation. Selecting a control opens control-specific review detail. Moving to another assessment context clears stale control context when the selected control is no longer relevant.

## 9. Review One Control

For each control requiring attention:

1. Read the determination and confidence.
2. Inspect the narrative and evidence citations.
3. Read the evidence and gaps section.
4. Review contradictory evidence and challenge/dissent state.
5. Use **How to Close This Gap** for closure recommendations.
6. Record reviewer notes or an assessment activity.
7. Apply a manual status override only when the assessor has a documented basis.

The control review surface separates model recommendation, code-governed status, evidence provenance, and human action. A model dissent is a review signal; it does not silently replace the primary determination.

## 10. Remediation and Closure

Use the remediation section for action-needed controls. It can show discovered gaps, recommended close actions, passing-evidence expectations, suggested artifact types, content guidance, collection guidance, and success criteria.

Generated artifacts are drafts. A control owner may review and revise them, but a generated document is not eligible assessment evidence until it is explicitly approved and marked eligible under the application's artifact workflow.

## 11. Reports and Exports

Use Outputs to generate and download available report formats. Depending on the configured capabilities, outputs include Word, Excel, JSON, SAR, SSP, POA&M, and OSCAL-oriented packages.

Before distributing a report:

- Confirm the assessment status and finalization state.
- Confirm unresolved findings, dissents, activities, tailoring decisions, and approvals are understood.
- Confirm report counts reconcile with the assessment workspace.
- Mark drafts and generated artifacts clearly.
- Retain the source evidence and provenance needed to reproduce the result.

## 12. What ATO Bot Does Not Do

ATO Bot does not replace qualified assessor judgment, perform every interview or technical test automatically, establish organizational risk tolerance, or make an authorization decision. It is strongest as a governed evidence-to-assessment and review workbench.
