# Ingestion Guide

Ingestion prepares source material for assessment. It does not decide compliance. The pipeline preserves the original document, creates structured evidence objects, improves retrieval, and exposes readiness problems before assessment execution.

## Supported Library Scopes

- Project document library.
- Common-control provider library.
- Enterprise policy library.
- Enterprise procedure library.

The assessment scope can combine project evidence with linked common-control, enterprise policy, and enterprise procedure evidence.

## Supported File Families

The current parser paths support PDF, DOCX, XLSX, PPTX, Visio, text, Markdown, and image artifacts. Large or image-heavy documents may require more processing time and may use OCR.

## Pipeline Stages

### 1. Upload and deduplication

The application validates the file extension and size, computes a SHA-256 hash, checks for duplicates in the library scope, stores the source file, creates a document record, and starts an ingestion run.

### 2. Parsing

Parsers convert the source into canonical records. Parsed documents and parsed lines retain document ID, run ID, page or sheet, section path, block type, table coordinates, and source ordering. PDF parsing uses text extraction and OCR fallback for text-poor pages. DOCX, XLSX, PPTX, Visio, text, and image paths preserve the structure each parser can reliably identify.

### 3. Screening

The screening model reviews parsed content for likely security-control relevance. Screening is a routing decision, not a finding. It records relevance, rationale, candidate families or controls, document intent, and quality signals so the next stages can spend work on useful content.

### 4. Context expansion and duplicate collapse

Relevant lines are expanded into larger excerpts using nearby source context, section boundaries, tables, and related blocks. Duplicate or near-duplicate excerpts are collapsed while retaining source provenance. This gives assessment reasoning enough context to understand a procedure or policy rather than a single isolated sentence.

### 5. Evidence classification

The classifier assigns product-facing evidence attributes such as artifact type, document type, document intent, evidence language, implementation state, and candidate control relationships. The output is structured and stored. If the model or provider fails, the run records the failure or degraded state rather than silently presenting fallback text as strong evidence.

### 6. Evidence-unit creation

Expanded and classified excerpts become reusable evidence units. Each unit points back to the source document and parsed location. Evidence units are the preferred assessment input because they preserve provenance, allow control routing, and can be reviewed independently of the original file.

### 7. Embeddings and retrieval support

Where configured, evidence units are embedded and stored in PostgreSQL with pgvector. Embeddings support semantic retrieval during assessment and assistant workflows. Retry and rate-limit handling is bounded; provider failure must remain visible in the ingestion run.

### 8. Compatibility backfill

Legacy document chunks and control tags remain available for compatibility with older retrieval and reporting paths. The supported path is evidence-unit-first. Compatibility data must not hide a failed or incomplete evidence-unit pipeline.

## Document Status

The normal visible lifecycle is:

- `pending` - accepted but not started;
- `processing` - one or more stages are active;
- `indexed` - the supported pipeline completed;
- `failed` - a terminal stage error or exhausted retry occurred.

Open the pipeline report when a document remains processing or failed. Reprocess only after identifying the failing stage or correcting the source/configuration problem.

## Readiness Checklist

Before using a document in an assessment, confirm:

- the document is in the intended library scope;
- the source file is current and not a duplicate;
- ingestion completed without degraded fallback;
- evidence units exist and have provenance;
- classification is plausible for the document;
- important pages, tables, and OCR sections were inspected;
- the evidence actually describes the current system rather than a plan or future state.

## Evidence Boundary

Ingestion can find and organize document evidence. It cannot prove that a technical mechanism operates, that personnel performed an interview, or that a test occurred. Those assessment activities must be recorded separately by qualified personnel.
