from types import SimpleNamespace

from app.services.assessment_engine import _is_carry_forward_compatible
from app.services.assessment_pipeline import evidence_scope_fingerprint


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
