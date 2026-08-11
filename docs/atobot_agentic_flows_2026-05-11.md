# ATO Bot Agentic Flows

Date: 2026-05-11

## 1. Purpose of This Document

This document explains the model-driven and agent-like workflows inside ATO Bot in plain English.

It is meant to answer:

- where the system uses LLMs or model-style reasoning
- what each AI flow is trying to accomplish
- what data each flow consumes
- what outputs it produces
- what remains deterministic code instead of AI
- where a human can review, challenge, or override results

This is not a marketing summary. It is an operational map of the AI behavior that exists in the codebase today.

## 2. What Counts as "Agentic" in ATO Bot

In this system, "agentic" does not always mean a free-form autonomous agent.

Most flows are one of three types:

1. Bounded model task
- the system gives a model one narrow job such as screening evidence, classifying a document, or drafting a note

2. Multi-step orchestration flow
- the system chains multiple model or logic steps together across a workflow such as assessment, closure, remediation, or synthetic package generation

3. Deterministic support flow around AI
- code validates, routes, retries, constrains, or scores model outputs without asking the model to make the final decision

ATO Bot is mostly built from type 1 and type 2 flows, with type 3 guardrails around them.

## 3. The Global Runtime Map

The central runtime router is [runtime.py](../backend/app/services/llm/runtime.py).

It maps internal purposes to provider/model routes.

### Runtime purposes currently defined

- `assessment_reasoning`
- `ai_assist_notes`
- `dissent_chat`
- `chat_general`
- `chat_workspace`
- `chat_control`
- `chat_remediation`
- `chat_evidence`
- `chat_vision`
- `chat_admin_explainer`
- `document_tagging`
- `procedure_categorization`
- `remediation_generation`
- `test_dataset_generation`
- `ingestion_screening`
- `ingestion_classification`

This is important because it means the system already thinks of AI usage as named product behaviors, not just random prompt calls.

## 4. Flow Inventory at a Glance

### Fully model-driven or hybrid-agentic flows

1. Ingestion screening
2. Ingestion classification
3. Full-document control tagging
4. Procedure auto-categorization
5. Assessment objective evaluation
6. Assessment challenge review
7. Assessment narrative generation
8. Retry engine reassessment
9. Assistant chat flows
10. Vision attachment summarization
11. AI note generation
12. Dissent collaboration chat
13. Closure interview flow
14. Closure analysis flow
15. Closure artifact generation and proof flow
16. Remediation guide generation
17. Remediation artifact generation
18. Synthetic test dataset generation
19. Human-style artifact generation
20. Optional security-posture guidance generation

### Adjacent orchestration flows that are important but not currently LLM-first

1. System knowledge extraction
2. SSP composition
3. Artifact validation
4. Calibration harness

Those last four matter because they shape or evaluate AI outputs even when they are not currently model-driven themselves.

## 5. Core Design Pattern Across Almost All Flows

Most important flows follow the same pattern:

1. gather scoped context
2. choose a runtime purpose
3. build a strict system prompt plus structured user prompt
4. call a model provider
5. parse or normalize the result
6. apply deterministic validation or fallback behavior
7. persist the result
8. expose it to a human workflow

That pattern is one of the strongest architectural properties in the platform.

## 6. Ingestion Screening Flow

### Entry points

- [pipeline.py](../backend/app/services/ingestion/pipeline.py)
- [llm_screener.py](../backend/app/services/ingestion/llm_screener.py)

### Runtime purpose

- `ingestion_screening`

### What it does

This is the first model-driven pass over parsed content.

The goal is not to decide compliance.
The goal is to decide whether each parsed line or cell is plausibly relevant to any NIST 800-53 control and should be promoted into deeper evidence processing.

### Inputs

- parsed text units
- line numbers
- page or sheet numbers
- section paths
- table and header context
- compact NIST family/control reference context

### Model output

For each item, the model returns:

- `relevance_score`
- `candidate_controls`
- `candidate_enhancements`
- `rationale`

### Human explanation

Think of this as a smart triage nurse for document text.
It does not diagnose the patient.
It decides which lines are important enough to send downstream.

### Guardrails

- strict JSON response shape
- explicit score thresholds
- heuristic fallback if the LLM call fails
- intentionally inclusive behavior so weak-but-plausible evidence is not dropped too early

### Why it matters

This is the first point where ATO Bot moves beyond keyword search and starts using semantic judgment.

## 7. Ingestion Classification Flow

### Entry points

- [pipeline.py](../backend/app/services/ingestion/pipeline.py)
- [classifier.py](../backend/app/services/ingestion/classifier.py)

### Runtime purpose

- `ingestion_classification`

### What it does

After relevant lines are expanded into evidence units, the model classifies those units so later workflows understand what kind of evidence they are looking at.

### Inputs

- expanded evidence excerpt
- candidate controls from the screening stage
- section and document context

### Model output

- likely control IDs
- likely enhancement IDs
- `artifact_type`
- `evidence_strength`
- `evidence_language_type`
- explanation
- confidence

### Human explanation

This is the system deciding whether a piece of evidence looks like policy, procedure, technical implementation, test evidence, management documentation, or something else.

### Why it matters

This metadata influences:

- retrieval behavior
- assessment weighting
- later package viability and system knowledge interpretations

## 8. Full-Document Control Tagging Flow

### Entry point

- [control_tagger.py](../backend/app/services/control_tagger.py)

### Runtime purpose

- `document_tagging`

### What it does

This is a second, larger-scale semantic tagging flow.
Instead of judging one line at a time, the model reads the document as a whole and decides which controls the document substantively supports.

### Phases

1. Full document analysis
- classify document type and intent
- identify which baseline controls the document supports
- return key excerpts and confidence

2. Chunk-level mapping
- match the returned excerpts back to stored chunks
- write control tags onto those chunks

### Why it is different from ingestion screening

Ingestion screening is local and permissive.
Control tagging is holistic and semantic.

For example:

- a firewall ruleset can satisfy `SC-7` without saying `SC-7`
- an HR onboarding procedure can support `AC-2` without saying `NIST`

### Guardrails

- only NIST 800-53 Rev 5 control IDs are allowed
- model outputs are validated against the project baseline
- low-confidence or invalid tags are discarded
- large documents are processed in sections when needed

### Human explanation

This is the system asking, "What is this document really about from a controls perspective?"

## 9. Procedure Auto-Categorization Flow

### Entry point

- [procedure_categorizer.py](../backend/app/services/procedure_categorizer.py)

### Runtime purpose

- `procedure_categorization`

### What it does

When an enterprise procedure is uploaded, the model classifies it into one procedure library category.

### Inputs

- filename
- parsed early text
- section context

### Output

- one category such as:
  - `access_management`
  - `change_management`
  - `incident_management`
  - `backup_recovery`
  - `continuous_monitoring`
  - `system_authorization`

### Post-model behavior

- the matching library is found or auto-created
- the document is assigned there
- ingestion then runs

### Human explanation

This is an AI sorting clerk for the enterprise procedure library.

## 10. Assessment Flow: The Most Important Agentic Workflow

### Entry points

- [assessment_engine.py](../backend/app/services/assessment_engine.py)
- [assessment_pipeline.py](../backend/app/services/assessment_pipeline.py)
- [multistage_engine.py](../backend/app/services/multistage_engine.py)

### Runtime purpose

- `assessment_reasoning`

### What it does

This is the flagship AI workflow.
It turns indexed evidence into control-by-control assessment outcomes.

### Sub-flows inside assessment

#### 10.1 Criteria assembly

The system builds a persisted criteria package for each control:

- control statement
- guidance
- objectives
- metadata

This part is deterministic.

#### 10.2 Evidence preload and objective packet building

The system loads evidence candidates for the control and organizes them into curated objective-specific packets.

This part is mostly deterministic and retrieval-driven.

#### 10.3 Objective evaluation

This is the first major model call inside assessment.

The model receives:

- control ID and title
- one or more objectives
- system context
- selected evidence packets

The model returns per-objective judgments such as:

- met
- partial
- not met
- rationale
- supporting quote
- missing evidence / gap

#### 10.4 Code-based adjudication

This is the critical non-agentic guardrail.

The model does not directly set the final control status.
Code combines objective outputs, evidence quality, corroboration, and policy logic to determine the control result.

#### 10.5 Assessor challenge

After code calculates the verdict, the model gets a second chance to dissent.

This is a QA-style AI pass, not the authoritative verdict engine.

#### 10.6 Narrative generation

Once the result is locked, the model writes the narrative:

- implementation statement
- gaps
- evidence citation framing
- remediation framing

### Human explanation

The assessment flow is less like "ask one model if the control passes" and more like:

1. gather evidence
2. evaluate objectives
3. calculate a governed result
4. ask a second model pass to challenge it
5. generate a readable explanation

### Why this matters

This is the clearest example of ATO Bot using AI inside a controlled workflow rather than treating the model like the final assessor.

## 11. Retry Engine Flow

### Entry point

- [retry_engine.py](../backend/app/services/retry_engine.py)

### Runtime purpose

- `assessment_reasoning`

### What it does

If findings are left as `not_reviewed`, the system can retry those controls with a fresh assessment pass.

### Inputs

- failed findings
- project baseline controls
- rebuilt system context
- RAG or full-text evidence context

### Output

- updated control finding
- possibly new POA&M entry if the result becomes partial or non-compliant

### Human explanation

This is a second-pass rescue loop for controls that could not be assessed cleanly the first time.

## 12. Assistant Chat Flows

### Entry points

- [assistant.py](../backend/app/api/assistant.py)
- [assistant_service.py](../backend/app/services/assistant_service.py)

### Runtime purposes

- `chat_general`
- `chat_workspace`
- `chat_control`
- `chat_remediation`
- `chat_evidence`
- `chat_admin_explainer`

### What it does

This is the conversational assistant layer.

It is not one monolithic assistant.
It routes the conversation based on mode and attached context.

### Context model

Conversations can be attached to:

- a project
- an assessment
- a control
- a finding
- remediation context
- uploaded files
- admin/runtime context

### Flow

1. create conversation
2. attach app resources or uploaded files
3. build a context block from those attachments
4. choose the assistant route
5. send recent message history plus grounded context to the model
6. store the assistant response and runtime metadata

### Human explanation

This is a scoped, contextual cyber assistant rather than a generic chatbot.

### Important limitation

The assistant can explain and recommend, but it is not the source of truth for assessment status.

## 13. Vision Attachment Flow

### Entry point

- [assistant_service.py](../backend/app/services/assistant_service.py)

### Runtime purpose

- `chat_vision`

### What it does

When a user uploads a screenshot or image into the assistant, the system can derive a grounded visual summary for later conversation.

### Inputs

- image file path
- filename

### Output

- concise visible-content summary
- model name used for the vision pass

### Human explanation

This lets the assistant treat screenshots, dashboards, scan results, and configuration panels as conversational context.

## 14. AI Note Generation Flow

### Entry point

- [ai_assist.py](../backend/app/api/ai_assist.py)

### Runtime purpose

- `ai_assist_notes`

### What it does

This flow generates short professional prose for operational fields.

Supported note types include:

- control notes
- assessment notes
- applicability rationale
- satisfied rationale
- risk rationale
- manual status rationale

### Inputs

- finding context
- current and target status
- gaps
- implementation statement
- assessment stats

### Output

- short text only

### Human explanation

This is an analyst-writing assistant, not a decision engine.

## 15. Dissent Collaboration Chat

### Entry point

- [ai_assist.py](../backend/app/api/ai_assist.py)

### Runtime purpose

- `dissent_chat`

### What it does

If an assessment finding has an AI challenge note, the analyst can open a multi-turn conversation with that dissenting perspective.

### Inputs

- finding
- challenge note
- control statement
- objectives
- conversation history

### Output

- explanation of why the challenge was raised
- what evidence is still missing
- suggested remediation or improved rationale

### Human explanation

This is a collaborative "argue with the assessor" lane.
It does not change the verdict automatically.

## 16. Closure Workflow

### Entry points

- [closure.py](../backend/app/api/closure.py)
- [closure_service.py](../backend/app/services/closure_service.py)

### Runtime purposes used

- `chat_control` style interview/analysis behavior through model completion
- artifact generation through explicit closure prompts

### What it does

This is a multi-step control closure pipeline designed to move a weak control toward reassessment-ready evidence.

### Stages

#### 16.1 Interview generation

The system produces 3 to 5 targeted questions to gather current-state facts from the user.

The model is told to ask about:

- what is actually implemented
- who owns it
- how it is verified
- what records exist
- where evidence lives

#### 16.2 Interview analysis

After the user answers, the model decides:

- is there enough information to proceed
- what artifacts should be created
- whether follow-up questions are needed

#### 16.3 Artifact generation

The model generates document JSON for closure artifacts based on:

- control gaps
- objective contracts
- interview answers
- project/system context

#### 16.4 Parse, save, index

The generated artifact is turned into a Word document, stored, parsed, and re-indexed into the evidence system.

#### 16.5 Prove/reassess

The system can then rerun the assessment pipeline for the specific control using the new artifact.

#### 16.6 Approval workflow

Closure artifacts can go through approval and completion tracking.

### Human explanation

This is the closest thing in the system to a guided AI closure agent.
It interviews, plans, writes, and then re-tests.

## 17. Remediation Guide Generation

### Entry point

- [remediation_service.py](../backend/app/services/remediation_service.py)

### Runtime purpose

- `remediation_generation`

### What it does

This flow turns assessment gaps into a practical remediation guide.

### Model output per gap

- action
- responsible role
- effort estimate
- success criteria
- template language

### Human explanation

This is the system saying, "Here is the work plan to close what the assessment found."

## 18. Remediation Artifact Generation

### Entry point

- [remediation_service.py](../backend/app/services/remediation_service.py)

### Runtime purpose

- `remediation_generation`

### What it does

This is a larger hybrid flow that creates reassessment-ready artifacts, not just text guidance.

### High-level sequence

1. read findings and objective gaps
2. plan one document type per control or bundle
3. generate structured content
4. enhance it into stronger evidence shape
5. save the generated documents
6. index them back into the platform

### Human explanation

This flow tries to produce the next package of evidence that would improve the next assessment run.

## 19. Synthetic Test Dataset Generation

### Entry point

- [test_dataset_generator.py](../backend/app/services/test_dataset_generator.py)

### Runtime purpose

- `test_dataset_generation`

### What it does

This flow generates a synthetic but structured ATO evidence package at the project level.

### Major sub-steps

1. extract context from existing project evidence
2. build a persona for the target system
3. plan target artifact bundles
4. generate one or more artifacts per control or grouped control set
5. validate and enhance generated documents
6. save and index them
7. optionally run artifact validation and system knowledge extraction against the result

### Human explanation

This is the platform creating a synthetic evidence corpus for testing or calibration.

### Why it matters

It is one of the strongest "self-improving platform" flows because it feeds the rest of the product:

- ingestion
- assessment
- validation
- knowledge extraction
- calibration

## 20. Human-Style Artifact Generation

### Entry point

- [human_artifact_generator.py](../backend/app/services/human_artifact_generator.py)

### Runtime purpose

- uses provider routing through `build_provider_for_purpose`

### What it does

This is a newer artifact generation path kept separate from the older closure path.

Its goal is to generate documents that read more like real human-authored operational artifacts and less like assessor-facing control closure text.

### Key characteristics

- plans a human-style artifact shape for the control
- uses project and system context
- lints outputs for forbidden assessor-oriented phrases
- can repair generated output if lint checks fail
- saves and re-indexes the resulting document

### Human explanation

This is the "write a believable artifact, not a robotic crosswalk" engine.

## 21. Optional Security-Posture Guidance Generation

### Entry point

- [security_telemetry.py](../backend/app/services/security_telemetry.py)

### Runtime purpose

- `chat_general`

### What it does

Most of this optional security-posture subsystem is deterministic.
When it is enabled, the system can ask the model to turn structured security findings into clearer operator-facing guidance. It is separate from the supported 800-53 assessment engine and is not a continuous-authorization capability.

### Inputs

- structured security finding contract
- severity
- observed facts
- expected state
- fix steps
- verification checks

### Output

- operator summary
- why-it-matters text
- fix steps text
- verification text

### Human explanation

This is a translator flow: from structured security facts into a cleaner remediation narrative. It should be described as optional security-posture guidance, not cATO telemetry.

## 22. System Knowledge Extraction

### Entry point

- [system_knowledge.py](../backend/app/services/system_knowledge.py)

### Is it currently agentic?

Not in the current implementation.

### What it does

It reads evidence text and uses deterministic pattern matching to infer:

- likely tools
- likely architecture assertions
- possible inheritance mappings

### Why include it here

Because it behaves like an AI-derived architecture inference feature from the user perspective, even though the current implementation is pattern-driven rather than LLM-driven.

### Human explanation

This is a machine inference layer, but not currently a model-driven one.

## 23. SSP Composition

### Entry point

- [ssp_composer.py](../backend/app/services/ssp_composer.py)

### Is it currently agentic?

Not currently.

### What it does

It turns project metadata plus system knowledge into structured SSP sections such as:

- system overview
- architecture and hosting
- security tooling
- roles and responsibilities
- evidence gaps and review notes

### Why include it

It is a major downstream consumer of AI-adjacent outputs even though the composition logic itself is deterministic.

## 24. Artifact Validation Flow

### Entry point

- [artifact_validation.py](../backend/app/services/artifact_validation.py)

### Is it currently agentic?

No.

### What it does

It scores generated document packages for:

- file integrity
- ingestion completion
- control mapping
- retrieval viability

### Why it matters

This is one of the main non-agentic quality gates used around generated evidence packages.

## 25. Calibration Harness

### Entry point

- [calibration_harness.py](../backend/app/services/calibration_harness.py)

### Is it currently agentic?

No, but it evaluates AI-driven outputs.

### What it does

It compares expected outcomes from a synthetic package run to actual assessment results and records:

- match rate
- drift types
- mismatch patterns
- performance snapshots

### Human explanation

This is the scorekeeping system for whether AI-generated evidence packages are actually helping.

## 26. Human Checkpoints Across the Whole System

The most important human checkpoints are:

- reviewable evidence triage in assessment
- challenge notes on verdicts
- finding overrides and notes
- closure interview answers
- artifact approval workflow
- confirmation/rejection of system knowledge assertions
- review of generated SSP text
- review of optional security-posture findings and recommendations

This matters because ATO Bot is not trying to remove the human assessor or ISSO. It is trying to accelerate and structure their workflow.

## 27. Where the System Is Most Agentic Today

If you had to rank the most agentic flows, the top ones are:

1. assessment pipeline
2. closure workflow
3. synthetic test dataset generation
4. assistant conversations
5. remediation artifact generation
6. human-style artifact generation

Those are the places where the system is clearly doing multi-step reasoning plus orchestration, not just one prompt and one answer.

## 28. Where the System Is Still Mostly Deterministic

The strongest deterministic layers are:

- adjudication and policy weighting around findings
- vector/indexing persistence
- artifact validation
- calibration
- SSP section composition
- system knowledge pattern extraction
- optional security-posture aggregation

This is a strength, not a weakness.
It means the system is using AI where interpretation helps, and code where control and reproducibility matter more.

## 29. Risks and Design Observations

### 29.1 Runtime purpose discipline is a major strength

The named runtime purposes in `runtime.py` make the AI surface understandable and governable.

### 29.2 Assessment is the cleanest flagship flow

It is the strongest example of AI under policy and code control.

### 29.3 Some flows overlap in document generation

There are multiple generation paths:

- closure generation
- remediation artifact generation
- test dataset generation
- human artifact generation

That offers flexibility, but it also means presentation and product strategy should explain which generation path is for which user/job.

### 29.4 Some inference layers are still transitional

System knowledge and the optional security-posture subsystem are strategically separate from the assessment core, and some parts remain scaffolding or deterministic-first implementations rather than deeply model-driven ones.

## 30. Plain-English Bottom Line

ATO Bot uses AI in many places, but not all in the same way.

The system is best understood as:

- an evidence-processing engine
- with multiple specialized AI workers inside it
- wrapped in deterministic adjudication, validation, and review workflows

The most mature agentic behaviors are:

- reading evidence
- classifying it
- evaluating control objectives
- challenging findings
- guiding remediation
- interviewing for closure
- generating new artifacts

The most important design fact is that ATO Bot does not let the model silently become the final authority.
It uses the model as an analyst, classifier, drafter, challenger, and explainer inside a governed compliance system.
