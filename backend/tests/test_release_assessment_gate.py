from scripts.verify_release_assessment import evaluate_release_metrics


def _metrics(**overrides):
    values = {
        "assessment_status": "complete",
        "finalization_status": "finalized",
        "actual_control_ids": {"AC-1", "AT-1"},
        "actual_objectives": {("AC-1", "AC-01a"), ("AT-1", "AT-01a")},
        "expected_control_ids": {"AC-1", "AT-1"},
        "expected_objectives": {("AC-1", "AC-01a"), ("AT-1", "AT-01a")},
        "frozen_documents": [
            {"document_id": 1, "ingestion_run_id": 10, "file_hash": "abc"}
        ],
        "healthy_run_ids": {10},
        "readiness": {"ready": True, "blockers": []},
    }
    values.update(overrides)
    return evaluate_release_metrics(**values)


def test_release_metrics_pass_only_when_every_gate_passes():
    result = _metrics()
    assert result["passed"]
    assert all(check["passed"] for check in result["checks"])


def test_release_metrics_reject_scope_and_governance_mismatch():
    result = _metrics(
        actual_control_ids={"AC-1"},
        healthy_run_ids=set(),
        readiness={"ready": False, "blockers": [{"code": "findings_unreviewed"}]},
    )
    failed = {check["name"] for check in result["checks"] if not check["passed"]}
    assert not result["passed"]
    assert failed == {
        "moderate_control_totality",
        "family_totality",
        "frozen_evidence_scope",
        "governance_ready",
    }
