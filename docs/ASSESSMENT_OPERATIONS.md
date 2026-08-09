# Assessment Operations Guide

This guide explains how ATO Bot supports a qualified NIST SP 800-53A assessment. It is not a substitute for the organization's assessment plan, procedures, risk acceptance, or authorization decision.

## Plan Before Execution

The assessment lead and System Owner define the system boundary, baseline, tailoring, organization-defined parameters, inherited/common controls, compensating controls, methods, objects, depth, coverage, assessor roles, reviewer roles, evidence scope, and approval path. In ATO Bot this becomes an assessment plan. Approve it before execution; approval authorizes the run design, not the final result.

## Examine, Interview, and Test

Use **Examine** for documents, records, configurations, logs, and other objects; **Interview** for personnel responsible for design, operation, and oversight; and **Test** for technical and operational mechanisms. ATO Bot can organize source material, route evidence, and persist activity records. It does not conduct a real interview or technical test for the assessor. Record performer, date, object, procedure, result, notes, and supporting evidence for each activity.

## Evidence and Provenance

Evidence should identify source, owner, effective/review date, scope, implementation state, and record location. The ingestion pipeline creates parsed content, evidence units, classifications, tags, embeddings, and citations. Review duplicates, failures, degraded output, contradictions, and relevance before freezing the assessment evidence scope. A citation must resolve to a retained source record and excerpt.

## Objective Reasoning and Adjudication

The assessment worker assembles criteria, objective text, selected evidence, metadata, and activity context. Model output is a bounded recommendation containing support, contradiction, gaps, narrative, and confidence signals. Deterministic policy code applies objective handling, thresholds, weights, family/control overrides, and final rollup rules. The persisted finding includes the objective/control result, citations, gaps, challenge state, and review metadata.

## Contradictions and Dissent

Contradictory evidence, weak evidence, future-state claims, and challenge-model disagreement are review signals. A dissent does not silently change the primary result. The assessor or reviewer resolves the issue by accepting the original result, changing the result with a documented basis, or obtaining additional evidence/activity. Record the resolution and preserve the audit trail.

## Human Review and Approval

Every final finding must have appropriate human review. Reviewers inspect evidence, activity records, confidence, gaps, and remediation implications. Manual overrides require a reason and actor. Finalization should block on unresolved findings, dissents, required activities, tailoring decisions, POA&M requirements, or approvals. The System Owner and independent reviewer should be represented by distinct accounts when separation of duties is required.

## Tailoring and Special Control Decisions

Persist ODP values and rationale. Identify inherited/common controls and provider evidence. Record compensating controls, applicability, and N/A decisions with authority and evidence. Do not assume that a common-control label or inheritance claim proves implementation for the system under review.

## Remediation and POA&M

For partial or non-compliant controls, use the control-specific gap guidance to define action, owner, target date, milestones, evidence needed, and residual-risk treatment. Generated procedures or artifacts are drafts until reviewed and approved. POA&M records should be specific enough to track ownership, schedule, risk response, and closure evidence.

## Finalization and Reconciliation

Before finalization, reconcile the plan scope, activities, findings, citations, objective/control totals, rollups, dissents, approvals, POA&M, and exports. Compare UI totals with report and OSCAL-oriented outputs. A valid file schema is not sufficient if the content does not represent activities actually performed. Retain source evidence, provenance, audit events, and the final immutable snapshot.
