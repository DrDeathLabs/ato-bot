# Assessment Workflow

ATO Bot evaluates NIST SP 800-53 controls through a staged objective-level pipeline. The model analyzes evidence; deterministic policy code computes the control result; qualified humans review and approve the outcome.

## Assessment Lifecycle

1. Create the project and system profile.
2. Load and index evidence.
3. Create the assessment plan.
4. Approve scope, methods, objects, depth, and coverage.
5. Freeze the assessment evidence scope.
6. Execute all selected controls and objectives.
7. Review findings, evidence, gaps, and dissent.
8. Record Examine, Interview, and Test activity results.
9. Complete tailoring, inherited-control, compensating-control, and not-applicable decisions.
10. Create POA&M and risk records for action-needed findings.
11. Obtain assessor and independent-reviewer approvals.
12. Finalize and export the assessment.

## Scope and Criteria Assembly

The run assembles a criteria package per control. The package contains the family, control title and statement, supplemental guidance, objectives, criteria metadata, and applicable policy configuration. The assessment scope normally includes project documents, linked common-control documents, enterprise policies, and enterprise procedures.

The plan should be approved before the run starts. The approval gate exists to prevent a run from silently changing scope or execution assumptions after evidence and findings have been created.

## Evidence Assembly

The staged engine preloads the latest complete evidence-unit index for the frozen scope. Selection is relevance-scored and token-bounded, with breadth across independent documents. The evidence packet records supporting, partial, contradictory, and irrelevant triage roles, source types, artifact types, citations, and rationale.

Semantic retrieval through pgvector is used where embeddings are available. Compatibility retrieval for legacy chunks remains available while evidence units are the supported assessment path.

## Objective Reasoning

Objective evaluation receives:

- control and objective identifiers;
- objective text and assessment context;
- system context;
- the selected evidence packet;
- evidence roles and source provenance.

The model returns structured objective-level results such as `yes`, `partial`, or `no`, with rationale, evidence quotes, sources, and gap text. These results are persisted as objective determinations and remain inspectable in the assessment workspace.

## Deterministic Adjudication

The model does not directly determine the final control status. Code applies the active assessment policy, objective handling rules, thresholds, family overrides, control overrides, and critical-objective behavior. A failed SHALL objective blocks a compliant control result. Corroboration can affect confidence, but additional documents do not automatically change status.

This separation is the primary reliability boundary:

- The model interprets evidence.
- Policy code computes the control outcome.
- A reviewer challenges, accepts, documents, or overrides the result.

## Challenge and Dissent

After the code result is calculated, a challenge pass can identify inconsistent reasoning, weak support, or disputed objectives. The challenge result is persisted as concurrence or dissent with challenged objectives and a note. Dissent is a review queue, not an automatic override.

## Persistence

Assessment state includes criteria packages, evidence triage, objective reviews, objective determinations, control findings, citations, challenge metadata, rollups, notes, overrides, activities, and audit records. This allows a reviewer to move from a control result back to the evidence and the reasoning that produced it.

## Retry and Recovery

Failed controls can be retried without recreating the assessment. Retry behavior rebuilds context from the frozen evidence scope, records the retry, and invalidates stale review state when the finding content changes. Worker restart recovery is designed to leave durable job and assessment state rather than creating duplicate findings.

## Finalization Boundary

Finalization is a governed action, not an automatic consequence of a worker finishing. Unresolved human activities, dissent, tailoring decisions, required POA&M records, or approvals must remain visible and block finalization where the configured governance rules require it. Finalized records should be treated as immutable assessment history.

## Assessment Interpretation

ATO Bot supports a complete assessor workflow when qualified personnel provide the required interviews, technical tests, judgment, review, and approval. The default automated path is document-centered and should be described as assessment support until the human assessment record is complete.
