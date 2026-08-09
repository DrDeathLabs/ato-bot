from types import SimpleNamespace

from app.services.assessment_engine import _is_carry_forward_compatible
from app.services.assessment_pipeline import (
    _unready_project_documents,
    evidence_scope_fingerprint,
    is_assessment_ready_ingestion,
    is_legacy_unverified_ingestion,
)


def _assessment(**overrides):
    values = {
        "policy_id": 2,
        "policy_version": 4,
        "llm_provider": "ollama",
        "llm_model": "model-a",
        "context_strategy": "rag",
        "skip_stage3": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _plan(fingerprint):
    return SimpleNamespace(scope_json={"fingerprint": fingerprint})


def test_scope_fingerprint_is_order_independent_but_version_sensitive():
    first = [
        {"document_id": 1, "file_hash": "aaa", "ingestion_run_id": 10},
        {"document_id": 2, "file_hash": "bbb", "ingestion_run_id": 20},
    ]
    assert evidence_scope_fingerprint(first) == evidence_scope_fingerprint(list(reversed(first)))

    changed_run = [dict(first[0]), {**first[1], "ingestion_run_id": 21}]
    assert evidence_scope_fingerprint(first) != evidence_scope_fingerprint(changed_run)


def test_only_transition_marker_is_treated_as_legacy_unverified():
    assert is_legacy_unverified_ingestion(["legacy_fallback_detected"])
    assert not is_legacy_unverified_ingestion(["screening_fallback"])
    assert not is_legacy_unverified_ingestion(["legacy_fallback_detected", "screening_fallback"])
    assert not is_legacy_unverified_ingestion([])


def test_legacy_unverified_ingestion_cannot_enter_a_new_frozen_scope():
    passed = SimpleNamespace(
        status="complete",
        quality_status="passed",
        readiness_eligible=True,
        fallback_stages=[],
    )
    legacy = SimpleNamespace(
        status="complete",
        quality_status="degraded",
        readiness_eligible=False,
        fallback_stages=["legacy_fallback_detected"],
    )

    assert is_assessment_ready_ingestion(passed)
    assert not is_assessment_ready_ingestion(legacy)


def test_pending_processing_failed_and_missing_runs_block_scope_readiness():
    rows = [
        (SimpleNamespace(id=1, filename="ready.docx", parse_status="indexed", parse_error=None),
         SimpleNamespace(id=11, status="complete", error_stage=None, error_message=None)),
        (SimpleNamespace(id=2, filename="pending.docx", parse_status="pending", parse_error=None), None),
        (SimpleNamespace(id=3, filename="processing.docx", parse_status="processing", parse_error=None),
         SimpleNamespace(id=13, status="running", error_stage="screen", error_message=None)),
        (SimpleNamespace(id=4, filename="failed.docx", parse_status="failed", parse_error="parse failed"),
         SimpleNamespace(id=14, status="failed", error_stage="parse", error_message="parse failed")),
    ]

    unready = _unready_project_documents(rows)

    assert [item["document_id"] for item in unready] == [2, 3, 4]
    assert unready[0]["run_status"] is None
    assert unready[1]["error_stage"] == "screen"
    assert unready[2]["error_message"] == "parse failed"


def test_carry_forward_requires_identical_scope_policy_and_runtime():
    fingerprint = evidence_scope_fingerprint(
        [{"document_id": 1, "file_hash": "aaa", "ingestion_run_id": 10}]
    )
    current = _assessment()
    previous = _assessment()
    assert _is_carry_forward_compatible(current, _plan(fingerprint), previous, _plan(fingerprint))

    assert not _is_carry_forward_compatible(
        current,
        _plan(fingerprint),
        _assessment(policy_version=3),
        _plan(fingerprint),
    )
    assert not _is_carry_forward_compatible(
        current,
        _plan(fingerprint),
        previous,
        _plan("different-scope"),
    )
