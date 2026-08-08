# Adjudication Engine Specification

Date: 2026-04-07
Status: Build-ready implementation spec
Scope: Replace the current flat objective tally model with an assessor-aligned adjudication model.

## Goal
Upgrade ATO Bot from:
- flat objective counting
- simple `yes / partial / no` thresholding

to:
- weighted objective adjudication
- evidence-quality-aware scoring
- critical failure handling
- contradiction penalties
- inheritance and compensating-control adjustments
- explicit manual-review triggers

This spec is focused only on the new implementation. It does not address patent strategy.

## Current State
The current control verdict logic in [multistage_engine.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/multistage_engine.py) uses:
- `yes = 1.0`
- `partial = 0.5`
- `no = 0.0`

Then:
- `score = (yes + 0.5 * partial) / total`
- any explicit `no` creates a `shall_failure`
- high scores without `shall_failure` can still be `compliant`

This is a good deterministic baseline, but it is flatter than how a human assessor reasons.

## Design Principles
1. The LLM remains an analysis component, not the final adjudicator.
2. Final control status remains code-determined.
3. Weights come from policy and calibration, not from model improvisation.
4. Stronger evidence should affect outcome more than weaker evidence.
5. Critical failures should be decisive where appropriate.
6. Contradictions should reduce confidence and often force review.
7. Inheritance and compensating controls must be first-class concepts.
8. Human review remains available and visible.

## High-Level Architecture

New flow:
1. Retrieve evidence packets for a control.
2. Classify and score evidence packets.
3. Run objective-level AI analysis.
4. Persist objective-level machine results.
5. Apply adjudication policy to each objective.
6. Roll up objective results into control-level adjudication.
7. Create findings and remediation from adjudicated results.
8. Expose richer control reasoning to UI and report layers.

## New Concepts

### 1. Adjudication Policy
A deterministic policy object that tells the engine how to weigh and interpret objective results.

Policy levels:
- global default policy
- baseline-specific policy
- control-family override
- control override
- objective override

Resolution order:
1. objective override
2. control override
3. control-family override
4. baseline-specific default
5. global default

### 2. Evidence Strength Model
Evidence packets receive a normalized quality classification and numeric multiplier.

### 3. Objective Adjudication Record
Each objective should carry:
- what the LLM said
- what evidence quality existed
- what policy weight applied
- what contradiction or inheritance modifiers applied
- what the effective objective score became

### 4. Control Adjudication Record
Each control should carry:
- weighted support score
- weighted deficiency score
- critical-failure count
- contradiction penalty
- inheritance and compensating adjustments
- final status
- confidence

## Data Model Changes

### A. New table: `adjudication_policy_entries`
Purpose:
- store explicit adjudication rules at baseline / control / objective granularity

Proposed fields:
- `id`
- `baseline_name`
- `control_id`
- `objective_id`
- `objective_type`
- `objective_weight` (`float`, default `1.0`)
- `critical_flag` (`bool`, default `false`)
- `minimum_evidence_strength` (`float`, default `0.5`)
- `negative_evidence_penalty` (`float`, default `0.25`)
- `contradiction_penalty` (`float`, default `0.20`)
- `inheritance_allowed` (`bool`, default `true`)
- `compensating_allowed` (`bool`, default `true`)
- `future_state_cap` (`float`, default `0.4`)
- `manual_review_threshold` (`float`, nullable)
- `notes`
- `version`
- `created_at`
- `updated_at`

### B. Extend `AssessmentEvidenceTriage`
Current model already includes:
- `source_type`
- `artifact_type`
- `evidence_strength`
- `evidence_language_type`
- `document_type`
- `document_intent`
- `relevance_score`

Add:
- `strength_score` (`float`, nullable)
- `authoritativeness_score` (`float`, nullable)
- `freshness_score` (`float`, nullable)
- `specificity_score` (`float`, nullable)
- `negative_evidence_flag` (`bool`, default `false`)
- `future_state_only_flag` (`bool`, default `false`)
- `contradiction_candidate_flag` (`bool`, default `false`)

Use:
- these fields are computed by deterministic code during evidence triage / normalization

### C. Extend `ObjectiveDetermination`
Current model:
- `status`
- `rationale`
- `supporting_citations`
- `contradictory_citations`
- `missing_evidence`
- `confidence_score`

Add:
- `base_result_score` (`float`, nullable)
- `objective_weight` (`float`, nullable)
- `critical_flag` (`bool`, default `false`)
- `effective_evidence_strength` (`float`, nullable)
- `negative_evidence_penalty` (`float`, nullable)
- `contradiction_score` (`float`, nullable)
- `inheritance_mode` (`String(32)`, nullable)
  - `local`
  - `inherited`
  - `shared`
  - `compensating`
- `compensating_control_present` (`bool`, default `false`)
- `effective_objective_score` (`float`, nullable)
- `manual_review_required` (`bool`, default `false`)
- `policy_snapshot` (`JSON`, nullable)

### D. Extend `ControlDetermination`
Current model:
- `status`
- `confidence_score`
- `objective_summary`
- `deficiency_summary`
- `evidence_summary`

Add:
- `weighted_support_score` (`float`, nullable)
- `weighted_gap_score` (`float`, nullable)
- `critical_failure_count` (`int`, default `0`)
- `partial_critical_count` (`int`, default `0`)
- `contradiction_penalty_total` (`float`, nullable)
- `inheritance_adjustment` (`float`, nullable)
- `compensating_adjustment` (`float`, nullable)
- `evidence_quality_index` (`float`, nullable)
- `manual_review_required` (`bool`, default `false`)
- `adjudication_summary` (`JSON`, nullable)

## Evidence Strength Model

### Canonical evidence categories
- `strong_technical`
- `strong_documentary`
- `medium`
- `weak`
- `negative`

### Default numeric values
- `strong_technical = 1.00`
- `strong_documentary = 0.85`
- `medium = 0.65`
- `weak = 0.35`
- `negative = -1.00`

### Intent modifiers
- `implements = 1.0`
- `plans = capped to policy.future_state_cap`
- `documents_gaps = negative evidence path`
- `evaluates = context-dependent, often mixed`

### Source weighting examples
- runtime config / command output / direct technical artifact -> high
- SSP with specific implementation detail -> medium-high
- policy only -> medium for policy objectives, low for technical objectives
- POA&M / audit finding / failed test -> strong negative

### Deterministic scoring formula
For each evidence packet:

`strength_score = base_category_score * intent_modifier * source_modifier * freshness_modifier`

Example deterministic factors:
- stale evidence older than threshold -> `0.8`
- undated evidence -> `0.75`
- direct runtime evidence -> `1.05`
- future-state-only evidence -> capped

## Objective Adjudication Logic

### Step 1: Convert LLM output to base result score
- `yes = 1.0`
- `partial = 0.5`
- `no = 0.0`

### Step 2: Apply objective weight
`weighted_base = base_result_score * objective_weight`

### Step 3: Apply evidence strength
`weighted_evidence = weighted_base * effective_evidence_strength`

### Step 4: Apply negative evidence penalty
If explicit negative evidence exists:
`after_negative = weighted_evidence - negative_evidence_penalty`

### Step 5: Apply contradiction penalty
If contradictory evidence exists:
`after_contradiction = after_negative - contradiction_score`

### Step 6: Apply inheritance / compensating adjustments
- inherited evidence may satisfy an objective when allowed
- compensating controls may partially offset a failure when allowed

### Step 7: Clamp result
`effective_objective_score = clamp(result, 0.0, objective_weight)`

### Step 8: Determine review state
Set `manual_review_required = true` if:
- contradiction exceeds threshold
- critical objective has only weak evidence
- inherited or compensating path is used without sufficient authoritative support
- no strong evidence exists but result is not `no`

## Control-Level Adjudication Logic

### Aggregate values
For each control compute:
- `total_possible_weight = sum(objective_weight)`
- `weighted_support_score = sum(effective_objective_score) / total_possible_weight`
- `weighted_gap_score = 1.0 - weighted_support_score`
- `critical_failure_count`
- `partial_critical_count`
- `contradiction_penalty_total`
- `evidence_quality_index`

### Proposed decision order

1. If no objective determinations exist:
- `status = not_reviewed`
- `confidence = 0.10`

2. If one or more critical objectives are explicit `no`:
- block `compliant`
- usually `non_compliant` unless inheritance/compensating policy explicitly permits downgrade to `partially_compliant`

3. If contradiction penalty exceeds threshold:
- force `manual_review_required = true`
- cap confidence
- do not allow `compliant` unless reviewer accepts

4. If weighted support score is high and evidence quality is above minimum and no decisive failure exists:
- `compliant`

5. If meaningful support exists but thresholds are not met:
- `partially_compliant`

6. If support is low or strong negative evidence dominates:
- `non_compliant`

### Proposed default thresholds
- `compliant_threshold = 0.85`
- `partial_threshold = 0.45`
- `critical_failure_blocks_compliant = true`
- `max_contradiction_for_compliant = 0.15`
- `minimum_evidence_quality_for_compliant = 0.65`

## Initial Objective Weight Defaults

These defaults are starting points, not permanent truth.

### Objective type defaults
- policy governance objective: `0.8`
- procedural objective: `1.0`
- technical enforcement objective: `1.3`
- monitoring / audit objective: `1.1`
- crypto / access / admin enforcement objective: `1.4`

### Critical flag defaults
Mark `critical_flag = true` for objectives involving:
- privileged MFA
- access enforcement
- cryptographic enforcement
- audit log generation for sensitive/admin actions
- account lifecycle approvals for privileged access

## Inheritance and Compensating Controls

### Inheritance rules
An inherited objective may be treated as satisfied only if:
- policy allows inheritance
- authoritative inherited evidence exists
- evidence is sufficiently fresh
- the inherited source is identified

### Compensating rules
A compensating control may offset a gap only if:
- policy allows compensation
- compensating control is documented
- compensating control is mapped to the failed objective
- compensating evidence strength exceeds a minimum threshold

### Status impact
- inheritance can support `compliant` if all conditions are satisfied
- compensating controls usually support `partially_compliant` unless explicitly approved as full equivalence

## Contradiction Handling

### Contradiction examples
- policy says MFA enforced
- runtime or identity records show privileged user without MFA

### Rules
- runtime/direct technical evidence outranks generic policy evidence
- explicit negative findings outrank vague positive narrative
- contradiction increases review burden and decreases confidence

### Default contradiction penalty
- mild contradiction: `0.10`
- moderate contradiction: `0.20`
- strong contradiction: `0.35`

### Manual review trigger
Set `manual_review_required = true` if:
- contradiction >= `0.20`
- or contradiction involves a critical objective

## Confidence Model

Confidence should no longer be a simple fixed value from status alone.

### Suggested control confidence formula
Inputs:
- evidence quality index
- contradiction penalty
- objective coverage completeness
- percentage of strong evidence
- inheritance/compensating reliance

Proposed structure:

`confidence = base_status_confidence + evidence_bonus - contradiction_penalty - inheritance_penalty - weak_evidence_penalty`

Example base values:
- compliant: `0.78`
- partially_compliant: `0.58`
- non_compliant: `0.70`

Then adjust:
- strong evidence bonus up to `+0.12`
- contradiction penalty up to `-0.25`
- compensating-only cap at `0.72`

## Human Review Alignment

Human assessors should remain able to:
- review adjudication summaries
- see why an objective was weighted strongly
- see why a contradiction was penalized
- override or challenge the result

This means the UI and reports will eventually need to expose:
- policy weight
- critical flag
- effective evidence strength
- contradiction summary
- inheritance/compensating rationale

## Migration Plan

### Phase 1: Policy and data model foundation
Files likely affected:
- [orm.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/models/orm.py)
- Alembic migration files

Tasks:
- add adjudication policy table
- extend triage/objective/control models

### Phase 2: Evidence strength engine
Files likely affected:
- new service module, e.g. `backend/app/services/adjudication_policy.py`
- new service module, e.g. `backend/app/services/evidence_strength.py`

Tasks:
- map triage fields into numeric strength
- infer negative/future-state/contradiction candidate flags

### Phase 3: Objective adjudication
Files likely affected:
- [multistage_engine.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/multistage_engine.py)

Tasks:
- preserve current LLM output path
- enrich objective determinations with adjudication fields

### Phase 4: New control verdict engine
Files likely affected:
- [multistage_engine.py](/C:/Users/Ddeat/OneDrive/Documents/Claude/ATO_Bot/backend/app/services/multistage_engine.py)
- new service module, e.g. `backend/app/services/control_adjudication.py`

Tasks:
- replace `calculate_verdict(...)` with policy-driven adjudication
- preserve backward compatibility for reports if needed

### Phase 5: Findings and export integration
Files likely affected:
- finding generation path
- OSCAL exporters

Tasks:
- surface weighted reasoning in findings
- include contradiction / inheritance / critical info in reports

### Phase 6: UI and reviewer workflow
Tasks:
- show adjudication details in assessment UI
- expose manual review triggers
- support calibration/admin editing of policy

## Backward Compatibility

For initial rollout:
- keep existing `status` fields
- keep current exporters working
- keep old confidence fields populated
- add new adjudication fields alongside old ones

This allows migration without breaking the current reporting surface.

## Minimum Viable Upgrade

If we want the highest-value first tranche, implement only:
1. objective weights
2. critical flags
3. evidence strength weighting
4. contradiction penalty

That will already make the adjudication materially closer to a human assessor.

## Out of Scope for Initial Build
- ML-trained weighting from historical outcomes
- automatic learning of weights from reviewer overrides
- full probabilistic reasoning engine
- replacing human review entirely

## Recommendation
Start with a policy-driven deterministic adjudication engine, not a learned one.

This keeps the system:
- explainable
- reviewable
- easy to calibrate
- aligned with formal assessment practice
