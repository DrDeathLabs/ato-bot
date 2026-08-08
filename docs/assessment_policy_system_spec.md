# Assessment Policy System Specification

Date: 2026-04-07
Status: Build-ready system-level policy spec
Scope: Organization-level adjudication policy for assessor-aligned scoring

## Goal
Create a system-level assessment policy capability that:
- defines how ATO Bot adjudicates control evidence across the organization
- applies one consistent scoring method to all assessed systems
- supports bucket-based tuning rather than per-system scoring drift
- keeps project-specific differences in risk acceptance, inheritance, compensating controls, and applicability
- provides an impact-preview workflow before policy changes take effect

This spec is intentionally separate from project/system-specific risk decisions.

## Core Design Rule
Scoring logic is organizational.

Project-level or system-level differences should not usually change:
- objective weights
- contradiction penalties
- evidence thresholds
- what counts as decisive

Project-level or system-level differences should instead affect:
- risk acceptance
- applicability
- inheritance
- compensating controls
- reviewer conclusions

This preserves:
- consistency
- auditability
- defensibility

## Policy Model

### Top-level object
`AssessmentPolicy`

Purpose:
- represents the active org-wide adjudication configuration

Proposed fields:
- `id`
- `name`
- `version`
- `description`
- `status`
  - `draft`
  - `active`
  - `retired`
- `effective_at`
- `created_by`
- `created_at`
- `updated_at`
- `notes`
- `default_thresholds_json`
- `mapping_rules_json`

### Default thresholds
These are org-wide adjudication thresholds.

Proposed fields:
- `compliant_threshold`
- `partial_threshold`
- `minimum_evidence_quality_for_compliant`
- `max_contradiction_for_compliant`
- `critical_failure_blocks_compliant`
- `manual_review_contradiction_threshold`
- `manual_review_weak_evidence_threshold`
- `manual_review_inheritance_without_authority`
- `manual_review_compensating_without_authority`

Suggested defaults:
- `compliant_threshold = 0.85`
- `partial_threshold = 0.45`
- `minimum_evidence_quality_for_compliant = 0.65`
- `max_contradiction_for_compliant = 0.15`
- `critical_failure_blocks_compliant = true`
- `manual_review_contradiction_threshold = 0.20`
- `manual_review_weak_evidence_threshold = 0.45`
- `manual_review_inheritance_without_authority = true`
- `manual_review_compensating_without_authority = true`

## Bucket Model

### Second-level object
`AssessmentPolicyBucket`

Purpose:
- define the default adjudication behavior for a bucket of objectives or controls

Proposed fields:
- `id`
- `policy_id`
- `bucket_key`
- `label`
- `description`
- `sort_order`
- `objective_weight`
- `critical_by_default`
- `minimum_evidence_strength`
- `negative_evidence_penalty`
- `contradiction_penalty`
- `future_state_cap`
- `inheritance_allowed`
- `compensating_allowed`
- `confidence_cap_if_only_weak_evidence`
- `confidence_cap_if_compensating_only`
- `active`

### Recommended default buckets

#### 1. `policy_governance`
Use for:
- policy existence
- assignment of responsibility
- review cadence

Defaults:
- `objective_weight = 0.80`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.50`
- `negative_evidence_penalty = 0.20`
- `contradiction_penalty = 0.15`
- `future_state_cap = 0.40`
- `inheritance_allowed = true`
- `compensating_allowed = false`

#### 2. `procedure_execution`
Use for:
- operational procedures
- workflow execution evidence
- approval sequences

Defaults:
- `objective_weight = 1.00`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.55`
- `negative_evidence_penalty = 0.25`
- `contradiction_penalty = 0.20`
- `future_state_cap = 0.40`
- `inheritance_allowed = true`
- `compensating_allowed = true`

#### 3. `technical_enforcement`
Use for:
- runtime settings
- implemented safeguards
- direct system behavior

Defaults:
- `objective_weight = 1.30`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.70`
- `negative_evidence_penalty = 0.30`
- `contradiction_penalty = 0.25`
- `future_state_cap = 0.25`
- `inheritance_allowed = false`
- `compensating_allowed = true`

#### 4. `monitoring_audit`
Use for:
- logging
- alerting
- monitoring coverage
- review and response evidence

Defaults:
- `objective_weight = 1.10`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.65`
- `negative_evidence_penalty = 0.25`
- `contradiction_penalty = 0.25`
- `future_state_cap = 0.30`
- `inheritance_allowed = true`
- `compensating_allowed = true`

#### 5. `crypto_and_key_management`
Use for:
- encryption
- key management
- certificate handling

Defaults:
- `objective_weight = 1.40`
- `critical_by_default = true`
- `minimum_evidence_strength = 0.75`
- `negative_evidence_penalty = 0.35`
- `contradiction_penalty = 0.30`
- `future_state_cap = 0.20`
- `inheritance_allowed = true`
- `compensating_allowed = false`

#### 6. `identity_and_access_enforcement`
Use for:
- MFA
- privileged access
- access enforcement
- session protection

Defaults:
- `objective_weight = 1.40`
- `critical_by_default = true`
- `minimum_evidence_strength = 0.75`
- `negative_evidence_penalty = 0.35`
- `contradiction_penalty = 0.30`
- `future_state_cap = 0.20`
- `inheritance_allowed = true`
- `compensating_allowed = false`

#### 7. `vulnerability_and_flaw_remediation`
Use for:
- patching
- flaw remediation
- scanner coverage
- remediation timeliness

Defaults:
- `objective_weight = 1.15`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.65`
- `negative_evidence_penalty = 0.30`
- `contradiction_penalty = 0.25`
- `future_state_cap = 0.30`
- `inheritance_allowed = true`
- `compensating_allowed = true`

#### 8. `inherited_control_support`
Use for:
- inherited evidence paths
- common control provider support

Defaults:
- `objective_weight = 0.95`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.70`
- `negative_evidence_penalty = 0.25`
- `contradiction_penalty = 0.20`
- `future_state_cap = 0.20`
- `inheritance_allowed = true`
- `compensating_allowed = false`

#### 9. `compensating_control_support`
Use for:
- alternative safeguards
- non-primary but documented compensating mechanisms

Defaults:
- `objective_weight = 0.90`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.75`
- `negative_evidence_penalty = 0.20`
- `contradiction_penalty = 0.20`
- `future_state_cap = 0.20`
- `inheritance_allowed = false`
- `compensating_allowed = true`
- `confidence_cap_if_compensating_only = 0.72`

#### 10. `negative_evidence`
Use for:
- explicit failed tests
- audit findings
- POA&M evidence showing unresolved gaps

Defaults:
- `objective_weight = 1.20`
- `critical_by_default = false`
- `minimum_evidence_strength = 0.60`
- `negative_evidence_penalty = 0.40`
- `contradiction_penalty = 0.30`
- `future_state_cap = 0.10`
- `inheritance_allowed = false`
- `compensating_allowed = false`

## Mapping Rules

### Principle
Objectives should be assigned to buckets automatically by deterministic rules, with rare explicit overrides.

### Mapping order
1. explicit objective override
2. explicit control override
3. control family rule
4. objective text rule
5. fallback default bucket

### Stored object
`mapping_rules_json` on `AssessmentPolicy`

### Rule examples

#### Rule group: by control family
- `IA*`, `AC*` with enforcement terms -> `identity_and_access_enforcement`
- `SC*` with crypto/key terms -> `crypto_and_key_management`
- `AU*`, `IR*`, `SI*` with monitoring terms -> `monitoring_audit`
- `RA*`, `SI*` with vulnerability/patch language -> `vulnerability_and_flaw_remediation`

#### Rule group: by objective text keywords
- contains `policy`, `review`, `approve`, `assign responsibility` -> `policy_governance`
- contains `procedure`, `workflow`, `process`, `documented step` -> `procedure_execution`
- contains `enforce`, `prevent`, `require`, `configure`, `restrict`, `block` -> `technical_enforcement`
- contains `log`, `alert`, `monitor`, `review records` -> `monitoring_audit`
- contains `encrypt`, `cryptographic`, `key`, `certificate` -> `crypto_and_key_management`
- contains `mfa`, `multi-factor`, `privileged`, `authenticate`, `session` -> `identity_and_access_enforcement`
- contains `patch`, `update`, `vulnerability`, `remediate flaw` -> `vulnerability_and_flaw_remediation`

#### Rule group: evidence posture
- explicitly inherited objective -> `inherited_control_support`
- explicitly compensating objective path -> `compensating_control_support`
- explicit negative assessment evidence present -> `negative_evidence`

### Initial mapping behavior
If multiple rules match:
- choose the highest-priority rule
- store the match reason in adjudication metadata

## Overrides

### Family overrides
`AssessmentPolicyFamilyOverride`

Purpose:
- tune whole control families without editing each control

Fields:
- `id`
- `policy_id`
- `control_family`
- `bucket_key_override`
- `objective_weight_override`
- `critical_override`
- `notes`

### Control overrides
`AssessmentPolicyControlOverride`

Purpose:
- rare explicit scoring override for a specific control

Fields:
- `id`
- `policy_id`
- `control_id`
- `bucket_key_override`
- `objective_weight_override`
- `critical_override`
- `notes`

### Objective overrides
`AssessmentPolicyObjectiveOverride`

Purpose:
- narrow override for individual objective behavior

Fields:
- `id`
- `policy_id`
- `control_id`
- `objective_id`
- `bucket_key_override`
- `objective_weight_override`
- `critical_override`
- `minimum_evidence_strength_override`
- `notes`

## What Does Not Belong in Policy

Do not put these in the scoring policy:
- accepted risk for a project
- temporary waivers
- system-specific compensating rationale
- applicability overrides for one system
- inherited provider chosen by one project

Those belong in project/system-specific assessment data.

## Project-Level Decision Objects

Keep these separate:

### `RiskAcceptance`
Purpose:
- records that a real deficiency is accepted for a period or under conditions

Fields:
- `project_id`
- `control_id`
- `objective_id` (optional)
- `finding_id` (optional)
- `accepted_by`
- `accepted_until`
- `rationale`
- `conditions`

### `ApplicabilityOverride`
Purpose:
- records that a control/objective is not applicable for that system

### `InheritanceRecord`
Purpose:
- records which provider or shared service supplies inherited support

### `CompensatingControlRecord`
Purpose:
- records the alternative safeguard and evidence path

Important:
- these affect adjudication results
- but they are not how the organization defines scoring logic

## Backend API Design

### Policy read routes
- `GET /api/assessment-policy/active`
- `GET /api/assessment-policy`
- `GET /api/assessment-policy/{policy_id}`

### Policy write routes
- `POST /api/assessment-policy`
- `PATCH /api/assessment-policy/{policy_id}`
- `POST /api/assessment-policy/{policy_id}/activate`
- `POST /api/assessment-policy/{policy_id}/clone`

### Bucket routes
- `GET /api/assessment-policy/{policy_id}/buckets`
- `PATCH /api/assessment-policy/{policy_id}/buckets/{bucket_key}`

### Override routes
- `GET /api/assessment-policy/{policy_id}/family-overrides`
- `POST /api/assessment-policy/{policy_id}/family-overrides`
- `PATCH /api/assessment-policy/{policy_id}/family-overrides/{override_id}`

- `GET /api/assessment-policy/{policy_id}/control-overrides`
- `POST /api/assessment-policy/{policy_id}/control-overrides`
- `PATCH /api/assessment-policy/{policy_id}/control-overrides/{override_id}`

- `GET /api/assessment-policy/{policy_id}/objective-overrides`
- `POST /api/assessment-policy/{policy_id}/objective-overrides`
- `PATCH /api/assessment-policy/{policy_id}/objective-overrides/{override_id}`

### Preview routes
- `POST /api/assessment-policy/{policy_id}/preview`
- `POST /api/assessment-policy/{policy_id}/preview/project/{project_id}`

Preview response should include:
- number of controls affected
- number of objectives affected
- status changes by control
- confidence changes
- controls newly requiring manual review

## UI Specification

### New system-level page
`Assessment Policy`

This should be a top-level admin/settings page, not a project page.

### Layout

#### Section 1: Policy summary
Show:
- active policy name
- version
- effective date
- created by
- threshold summary
- last updated

Actions:
- create draft
- clone active
- activate draft
- compare with active

#### Section 2: Bucket calibration table
One row per bucket.

Columns:
- bucket name
- description
- mapped objectives count
- objective weight
- critical by default
- minimum evidence strength
- negative evidence penalty
- contradiction penalty
- future-state cap
- inheritance allowed
- compensating allowed

Controls:
- sliders or numeric inputs for weights and penalties
- toggles for boolean rules

#### Section 3: Bucket visualization
Charts:
- weight bars by bucket
- number of objectives mapped to each bucket
- count of controls currently influenced by each bucket

Purpose:
- users should be able to see how the org is weighting control categories

#### Section 4: Impact preview
When a draft is edited, show:
- affected controls count
- affected objectives count
- current vs proposed status delta
- current vs proposed confidence delta
- newly triggered manual-review items

This is critical.
Users should not change scoring logic blindly.

#### Section 5: Family overrides
Grouped by family:
- AC
- IA
- AU
- SC
- SI
- etc.

Show:
- current bucket mapping
- current overrides
- rationale

#### Section 6: Control overrides
Searchable by control ID.
Should be rare.

#### Section 7: Objective overrides
Deepest override level.
Should be hidden by default behind an advanced toggle.

### UX principles
1. Bucket editing should be the default workflow.
2. Family overrides should be easy.
3. Control/objective overrides should be explicit and rare.
4. Preview must always show impact before activation.
5. Policy versions must be immutable once activated.

## Activation Model

### Draft policy
Editable

### Active policy
Read-only
Applied to new adjudication runs

### Historical policy versioning
Assessments should store which policy version was used.

Add to `Assessment`:
- `policy_id`
- `policy_version`

This is important for reproducibility.

## Initial Seeding

On first migration:
- create default active policy
- seed the ten buckets above
- set org-wide default thresholds
- create empty override tables

## Adjudication Engine Consumption

The new engine should:
1. resolve bucket for each objective
2. load effective policy values
3. compute weighted objective results
4. compute control-level adjudication
5. persist policy snapshot used during the run

Store on:
- `ObjectiveDetermination.policy_snapshot`
- `Assessment.policy_id`
- `Assessment.policy_version`

## Implementation Order

### Phase 1
- add policy tables
- add seeded default policy
- add assessment policy linkage on `Assessment`

### Phase 2
- add bucket resolver service
- add preview engine

### Phase 3
- add system-level `Assessment Policy` UI

### Phase 4
- wire adjudication engine to active policy

### Phase 5
- add override management and compare/activate flow

## MVP

If we want a smaller first release:
- one active policy
- bucket editing only
- no family/control/objective overrides yet
- preview by bucket impact only

That is enough to start calibrating the adjudication model without overbuilding.

## Recommendation

Build this first as:
- a system-level policy workspace
- bucket-based scoring and preview
- versioned active/draft policy model

Then add:
- family overrides
- control overrides
- deeper objective overrides

This will give ATO Bot a scoring model that is:
- consistent across systems
- easy to calibrate
- understandable to humans
- aligned to assessor judgment
