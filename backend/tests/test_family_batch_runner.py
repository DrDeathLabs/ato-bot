from test_harness.batch_run_generic_families import _entry_is_clean, _proof_result


def test_proof_result_reports_residual_controls():
    result = {
        "proof": {
            "results": [
                {"control_id": "AC-1", "status": "partially_compliant"},
                {"control_id": "AC-2", "status": "compliant"},
            ]
        }
    }

    assert _proof_result(result) == {
        "controls": 2,
        "compliant": 1,
        "failing_control_ids": ["AC-1"],
        "clean": False,
    }
    assert not _entry_is_clean({"status": "complete", "result": result})


def test_proof_result_requires_nonempty_clean_results():
    assert not _proof_result({"proof": {"results": []}})["clean"]
    assert _entry_is_clean(
        {
            "status": "proof_clean",
            "proof_summary": {
                "controls": 1,
                "compliant": 1,
                "failing_control_ids": [],
                "clean": True,
            },
        }
    )
