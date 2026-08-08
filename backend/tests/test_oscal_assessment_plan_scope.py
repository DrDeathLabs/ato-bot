from app.services.reports.oscal_assessment_plan import _frozen_document_ids


def test_frozen_document_ids_use_approved_governed_scope():
    scope = {
        "documents": [
            {"document_id": 9, "ingestion_run_id": 90, "file_hash": "bbb"},
            {"document_id": 3, "ingestion_run_id": 30, "file_hash": "aaa"},
            {"document_id": 9, "ingestion_run_id": 90, "file_hash": "bbb"},
        ],
        "document_ids": [999],
    }

    assert _frozen_document_ids(scope) == [3, 9]


def test_frozen_document_ids_support_legacy_approved_plans():
    assert _frozen_document_ids({"document_ids": [8, 2, 8]}) == [2, 8]
    assert _frozen_document_ids(None) == []
