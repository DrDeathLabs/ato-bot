# ATO Bot Ingestion, Assessment, And Review Flow

Date: March 24, 2026

This document explains what the running ATO Bot application is doing today from document upload through ingestion, assessment, reviewer challenge, and human review. It reflects the current code and live Docker deployment as of this revision.

## 1. Executive Summary

ATO Bot now uses two linked staged pipelines:

1. An ingestion pipeline that turns uploaded artifacts into traceable evidence objects.
2. An assessment pipeline that evaluates those evidence objects against NIST SP 800-53A-style criteria and persists structured determinations before writing the final finding narrative.

At a high level, the end-to-end process is:

1. Upload and store the file.
2. Parse it into canonical source records.
3. Use the reasoning model to screen parsed text units for possible control relevance.
4. Expand relevant units into contextual evidence objects.
5. Classify those evidence objects with the reasoning model.
6. Generate Voyage embeddings for retrieval.
7. Backfill legacy chunks and control tags for compatibility.
8. Build assessment criteria packages and an evidence pool for each control.
9. Triage evidence, evaluate objectives, calculate the control determination in code, run an assessor challenge pass, and then write the narrative.
10. Expose the results through the assessment workbench and rollup views for human review.

The most important current design point is that ATO Bot is still partly hybrid:

- Ingestion is evidence-unit first.
- Assessment now prefers the staged assessor pipeline built on those evidence units.
- Legacy `document_chunks` and `document_chunk_control_tags` still exist because some retrieval and compatibility paths still depend on them.

## 2. Where Documents Enter The System

Artifacts can enter through four main library scopes:

- Project document library
- Common control provider library
- Enterprise policy library
- Enterprise procedure library

The upload pattern is broadly the same in each scope:

- Validate extension and size.
- Compute a SHA-256 hash.
- Block duplicates within that library scope.
- Write the file to the server upload path.
- Create a `documents` row with a pending status.
- Launch a background ingestion run.

Supported families currently include:

- PDF
- Word
- Excel
- PowerPoint
- Visio
- Text and Markdown
- Images

## 3. High-Level Document Status Lifecycle

The visible status lifecycle is still:

- `pending`
- `processing`
- `indexed`
- `failed`

While a run is active, the latest `ingestion_runs` record tracks stage progress. The UI stage badge is driven from that run state and can show:

- `parse`
- `screen`
- `expand`
- `classify`
- `embed`

If all stages complete, the document becomes `indexed`. If a stage exhausts retries or throws a terminal error, the run fails and the document is marked `failed` with a stored error message.

## 4. Stage 1: Parsing

### Purpose

Parsing converts the raw uploaded file into the canonical source representation used by every later stage.

### What Gets Stored

The parse stage writes:

- one `parsed_documents` row for parser metadata and run linkage
- many `parsed_lines` rows for exact source-level text units

Each parsed line can carry:

- document id
- run id
- exact line number
- page or sheet number
- section path
- block id
- block type
- table id
- row index
- column index
- cell label
- content type
- raw extracted content

### Parser Behavior By File Type

#### PDF

- Uses PyMuPDF (`fitz`) for extraction.
- Falls back to OCR with Tesseract for text-poor pages.
- Builds rough paragraph-like blocks and preserves page numbers.

#### DOCX

- Uses `python-docx`.
- Walks paragraphs and tables in source order.
- Preserves headings, list items, paragraphs, and table rows.
- Preserves row and cell provenance with inherited header context.
- Treats the Word document as a logical page sequence rather than a true printed page map.

#### XLSX

- Uses `openpyxl`.
- Treats each sheet as a page-like unit.
- Preserves row and column coordinates and header inheritance.
- Builds combined row context such as `Header: Value` while still storing exact cell provenance.

#### PPTX

- Uses `python-pptx`.
- Treats each slide as a page.
- Extracts text-bearing shape content and title context when available.

#### Images

- Uses Tesseract OCR by default.
- The parse goal is provenance capture, not compliance interpretation.

### Meaning

Parsing is the traceability stage. It is trying to preserve source fidelity and location context well enough that later evidence can always be traced back to the source artifact.

## 5. Stage 2: Model-Driven Screening

### Purpose

Stage 2 is now a reasoning-model screening pass, not a keyword-only gate.

The system evaluates every parsed atomic text unit for possible relevance to the active NIST SP 800-53 Rev. 5 corpus and stores a `screening_results` row for each unit.

### What Changed

This stage used to be primarily heuristic and keyword driven. It is now LLM driven by default:

- `screening_mode = llm`
- default `screening_batch_size = 24`
- default `screening_timeout_secs = 90`
- default `screening_threshold = 0.15`

Those values can be overridden by admin config. Where there is no stored override, the runtime uses the code defaults.

### What The Model Receives

The screener batches parsed units and gives the reasoning model compact structured context such as:

- raw line or cell text
- line number
- page or sheet
- section path
- table header and row context when applicable

For spreadsheets and tables, the screening packet uses combined row context so a cell is not judged in isolation.

### What Gets Stored

Each screening result can store:

- relevance score
- candidate control ids
- candidate enhancement ids
- rationale
- above-threshold flag

### What This Stage Is Doing

It is not making a final compliance determination. It is deciding whether a parsed unit is plausibly relevant enough to promote into context expansion.

### Active Corpus

The active live corpus is:

- corpus key: `nist-sp-800-53-rev5-default`
- version: `2026.03.24`

The corpus is now externalized and versioned, not hardcoded as the only source of truth in application logic.

## 6. Stage 3: Context Expansion And Duplicate Collapse

### Purpose

The application does not treat an isolated triggering line as final evidence. It expands promoted units into evidence excerpts that are large enough to be interpretable, traceable, and reusable.

### Expansion Order

The current expansion logic prefers:

1. Same logical parser block
2. Same table row with inherited header context
3. Same section block
4. Nearby fallback line window
5. Trigger line alone as the last resort

### What Gets Stored

Each promoted evidence unit is written to `evidence_units` with:

- triggering line id
- all included source line ids
- expanded content
- page numbers
- section path
- table coordinates
- token count

### Duplicate Collapse

Stage 3 now collapses duplicate expansions within the same document run when multiple trigger lines lead to the same effective evidence block.

Important meaning:

- unique evidence is preserved
- duplicate trigger representations of the same source block are removed
- corroborating evidence from separate documents is still preserved

This keeps recall high while reducing unnecessary classification and embedding work downstream.

## 7. Stage 4: Evidence Classification

### Purpose

Each expanded evidence unit is classified by the configured Ollama-compatible reasoning model.

### Runtime Configuration

The current live configuration includes:

- `ollama_reasoning_model = gpt-oss:120b-cloud`
- `ollama_reasoning_effort = high`

The admin configuration surface now supports:

- local Ollama-compatible base URLs
- hosted or cloud Ollama-compatible base URLs
- optional API key or auth header support

If no admin override is stored for the base URL, runtime falls back to the environment configuration.

### What The Classifier Receives

The classifier sends the model:

- the expanded evidence excerpt
- candidate controls from screening as hints only
- section path when available
- deterministic temperature settings

### What The Model Returns

The application expects structured JSON including:

- likely control ids
- likely enhancement ids
- artifact type
- evidence strength
- evidence language type
- concise explanation
- confidence

### Artifact Type Categories

The current categories include:

- policy
- procedure
- implementation_statement
- technical_config
- operational
- test_evidence
- management
- diagram_narrative
- audit_artifact
- other

### Evidence Language Categories

- policy_language
- implementation_language
- procedural_language
- objective_evidence
- mixed

### Failure Behavior

Classification is designed to degrade rather than disappear. If the reasoning call fails, the pipeline can fall back to a minimal classification using the screening candidates and weaker default labels instead of discarding the whole document immediately.

## 8. Stage 5: Voyage Embeddings

### Purpose

Embeddings are generated only for expanded evidence units, not for raw lines.

### Live Runtime Configuration

The current live settings are:

- `voyage_model = voyage-4`
- `voyage_max_concurrency = 1`
- `voyage_rate_limit_backoff_secs = 30`
- `embed_batch_size = 5`

### What The Call Does

The pipeline sends evidence unit text to the Voyage embeddings endpoint and stores vectors in `evidence_embeddings`.

### Retry And Rate-Limit Behavior

Your current Voyage tier is constrained to:

- 10,000 TPM
- 3 RPM

Because of that, the application now:

- serializes Voyage work globally
- respects `Retry-After` when Voyage sends it
- uses configured fallback backoff when it does not
- retries incomplete or null-vector batches
- fails the run clearly if retries are exhausted

This makes the pipeline slower than an unconstrained provider, but much safer and more predictable.

## 9. Compatibility Layer: Legacy Chunks And Tags

After the new ingestion stages complete, the app still backfills:

- `document_chunks`
- `document_chunk_control_tags`

### Why This Still Exists

The platform is not yet fully migrated away from the legacy chunk/tag model. Some retrieval and compatibility paths still depend on these tables, so ingestion continues to backfill them.

### What Gets Backfilled

For each evidence unit:

- one legacy chunk is created
- the chunk is tagged with classified controls
- the chunk is tagged with enhancements where applicable
- document type and intent are backfilled for older assessment and explorer flows

## 10. What Exists After Ingestion

When a document is fully indexed, the system has three linked layers:

### Raw And Provenance Layer

- uploaded file on disk
- `documents`
- `parsed_documents`
- `parsed_lines`

### Derived Evidence Layer

- `screening_results`
- `evidence_units`
- `evidence_classifications`
- `evidence_embeddings`
- `ingestion_runs`

### Compatibility Layer

- `document_chunks`
- `document_chunk_control_tags`

That layered model is what gives the application both exact provenance and downstream assessment compatibility.

## 11. Assessment Scope Assembly

Before the application evaluates controls, it assembles the assessment scope.

The current scope includes:

- project documents for that project
- linked common control provider documents
- enterprise policy library documents
- enterprise procedure library documents

This means enterprise policies and procedures are automatically in scope for project assessments, even when there are few or no project uploads.

## 12. Assessment Pipeline Overview

The assessment engine now prefers a staged assessor pipeline when evidence-unit data is available.

The staged assessment flow is:

1. Build the criteria package for the control.
2. Preload the evidence-unit index for the assessment scope.
3. Select and triage evidence for the control.
4. Evaluate objectives in batches.
5. Calculate the determination in code.
6. Run an assessor challenge pass.
7. Write the final narrative or synthesize it if Stage 3 is skipped.
8. Build an assessment rollup for ATO support.

## 13. Stage A: Criteria Package

For each control, the pipeline persists an `assessment_criteria_packages` row containing:

- control family
- control title
- control statement
- supplemental guidance
- assessment objectives
- criteria metadata

This package is the structured assessment input. It keeps the later stages focused on evidence evaluation instead of rebuilding control context from scratch each time.

## 14. Stage B: Evidence Preload And Selection

### Evidence Source

The staged assessor pipeline now preloads evidence units from the latest complete ingestion runs, not just legacy chunks.

### Selection Behavior

Evidence selection is relevance scored and token bounded, but it now also prefers breadth across independent documents so one large artifact does not crowd out corroborating support from other artifacts.

The selector intentionally chooses across:

- supporting evidence
- partial evidence
- contradictory evidence
- limited irrelevant evidence for context

### Why This Matters

This change better mimics a human assessor using multiple artifacts instead of over-trusting a single strong excerpt.

## 15. Stage C: Evidence Triage

The pipeline persists `assessment_evidence_triage` rows for the selected evidence for each control.

Each triage row can record:

- evidence unit id
- document id
- source type
- artifact type
- evidence strength
- evidence language type
- document type
- document intent
- triage role
- relevance score
- citation label
- rationale

The triage role is currently one of:

- `supporting`
- `partial`
- `contradictory`
- `irrelevant`

This gives the assessment workbench a durable evidence packet instead of ephemeral prompt text.

## 16. Stage D: Objective Evaluation

### Purpose

The LLM evaluates assessment objectives, not final control status.

### Runtime Behavior

Objective evaluation is batched into smaller calls for performance and repeatability. Each batch sends:

- control id and title
- a list of objectives
- system context
- the selected evidence packet

The model returns per-objective JSON including:

- objective id
- `yes`, `partial`, or `no`
- evidence quote
- source
- gap text

### What Gets Stored

The system persists `objective_determinations` rows with:

- objective id
- objective text
- status
- rationale
- supporting citations
- contradictory citations
- missing evidence
- confidence score

## 17. Stage E: Code-Based Control Determination

After the objective results come back, code calculates the control determination.

### Important Rule

The control verdict is not delegated entirely to the LLM. Code remains authoritative.

The major rule is:

- any objective scored `no` is treated as a SHALL failure and blocks a compliant verdict

### What Gets Stored

The system persists `control_determinations` with:

- status
- confidence score
- objective summary
- deficiency summary
- evidence summary

### Corroboration Metadata

The determination now also stores structured corroboration information derived from the selected evidence:

- number of supporting units
- number of supporting documents
- number of distinct source types
- number of distinct artifact types
- corroboration strength
- example supporting documents

The current corroboration logic does not merge separate artifacts together. It is used to recognize when multiple independent artifacts reinforce the determination.

### Confidence Handling

Status does not change just because there are more artifacts. However, corroborated support can slightly increase confidence for `compliant` and `partially_compliant` determinations.

## 18. Stage F: Assessor Challenge

After the code verdict is calculated, the application runs a second-pass assessor challenge call.

### Purpose

This call is a QA and review pass. It exists to challenge the reasoning when the preliminary verdict appears inconsistent with the objective evidence.

### Important Constraint

The challenge model is not authoritative. It can attach a dissent note, but it does not silently override the code verdict.

### What Gets Stored

The pipeline persists `assessment_challenges` with:

- concur / dissent
- dissent note
- challenged objectives
- model name

This gives the human reviewer a structured dissent channel instead of silently changing results.

## 19. Stage G: Narrative Writing

Once the determination is fixed, the application writes the final narrative.

This stage produces:

- implementation statement
- gaps
- evidence citations
- remediation plan

If Stage 3 narrative generation is skipped, the application can synthesize a narrative from the structured objective results. That is faster, but less rich than the full narrative-writing pass.

## 20. Stage H: ATO Support Rollup

After findings are written, the application builds an `assessment_rollups` record for the assessment.

The rollup can summarize:

- counts by finding status
- challenged control counts
- source mix
- corroboration counts
- high-risk controls
- residual risk summary
- readiness classification

This is meant to support a human ATO decision, not replace one.

## 21. Retrieval Paths Used During Assessment

There are still two active retrieval styles in the system:

### A. Evidence-Unit First Retrieval

The staged assessment pipeline prefers preloaded `evidence_units` plus `evidence_classifications` and `evidence_embeddings`.

### B. Legacy Chunk Compatibility Retrieval

Legacy tagged chunks are still available and can be used as a compatibility path or fallback.

### C. Semantic Retrieval

When semantic search is needed, Voyage query embeddings are used against:

1. `evidence_embeddings` joined to `evidence_units`
2. legacy chunk embeddings when necessary

## 22. LLM Calls From Document Drop To Review

The application now uses different calls for clearly separated roles.

### Ingestion-Time Calls

#### A. LLM Screening

Purpose:

- evaluate parsed text units for possible relevance

Input:

- batched parsed units with provenance hints

Output:

- relevance score
- candidate controls
- candidate enhancements
- rationale

#### B. LLM Classification

Purpose:

- classify expanded evidence units

Input:

- one expanded evidence excerpt
- candidate control hints
- structure metadata

Output:

- classified metadata for retrieval and later assessment

#### C. Voyage Embedding

Purpose:

- embed evidence units for retrieval

Input:

- evidence unit text

Output:

- vector embeddings stored for later search

### Assessment-Time Calls

#### D. Objective Evaluation

Purpose:

- evaluate one batch of assessment objectives against the selected evidence

Output:

- per-objective `yes`, `partial`, or `no`
- evidence quote
- source
- gap

#### E. Challenge Review

Purpose:

- review the code-calculated verdict and raise a dissent when necessary

Output:

- concur or dissent
- dissent note
- challenged objectives

#### F. Narrative Writing

Purpose:

- write the implementation statement, gaps, citations, and remediation plan after the verdict already exists

Output:

- narrative and remediation package content

## 23. Assessment Workbench And Review Surfaces

The assessment UI now exposes the staged assessor data through a workbench for each control.

### Workbench Tabs

The workbench can show:

- criteria package
- control determination
- objective workbook
- evidence triage
- assessor challenge

### What The Reviewer Can See

The reviewer can now inspect:

- the control statement and objectives used for the evaluation
- the evidence selected for the control
- objective-level results
- the code-based determination
- the challenge note if the reviewer pass dissented
- corroboration breadth, including when multiple independent artifacts supported the control

## 24. Human Review And Analyst Actions

The application also supports a human review layer above the automated pipeline.

Current review features include:

- manual status override
- notes on individual findings
- risk acceptance workflow
- applicability and inheritance overrides
- retry of failed findings
- activity history on controls
- AI dissent discussion surfaces where challenge notes exist

These features exist so the automated assessment can be reviewed, corrected, and governed rather than blindly accepted.

## 25. Performance Notes

The system is doing materially more than the older parse-and-tag model:

- provenance-first parsing
- LLM screening of parsed units
- context expansion
- duplicate-collapse logic
- reasoning-based evidence classification
- Voyage embeddings
- legacy compatibility backfill
- staged objective evaluation
- challenge review

The major current performance factors are:

- Voyage rate limits are still the primary ingestion bottleneck
- objective evaluation is faster than before because it is batched
- assessment is faster than before because it preloads evidence-unit data once instead of rediscovering everything repeatedly
- corroboration-aware selection now prefers breadth across artifacts without increasing prompt size dramatically

## 26. Current Live Snapshot Summary

At the time this revision was prepared, the live stack behavior relevant to ingestion and assessment included:

- Active corpus: `nist-sp-800-53-rev5-default` version `2026.03.24`
- Screening mode default: `llm`
- Screening batch size default: `24`
- Screening timeout default: `90` seconds
- Screening threshold default: `0.15`
- Ollama reasoning model: `gpt-oss:120b-cloud`
- Ollama reasoning effort: `high`
- Voyage model: `voyage-4`
- Voyage max concurrency: `1`
- Voyage rate-limit fallback backoff: `30` seconds
- Voyage embed batch size: `5`
- Assessment path: staged assessor pipeline with persisted criteria, triage, objective determinations, control determinations, challenge records, and rollup support

## 27. Bottom Line

ATO Bot is no longer just parsing files and generating a single-shot compliance answer.

It is now doing staged evidence construction and staged assessment:

- provenance capture
- model-driven screening
- evidence expansion
- evidence classification
- semantic indexing
- criteria assembly
- evidence triage
- objective evaluation
- code-based determination
- assessor challenge
- narrative generation
- ATO support rollup
- human review and override

That separation of responsibilities is the clearest way to understand the current application from document drop through ingestion, assessment execution, and review.
