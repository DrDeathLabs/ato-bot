from types import SimpleNamespace

from app.api.ingestion_config import _prepare_document_reprocess


def test_reprocess_moves_terminal_document_to_durable_pending_queue() -> None:
    document = SimpleNamespace(parse_status="failed", parse_error="temporary timeout")

    assert _prepare_document_reprocess(document)
    assert document.parse_status == "pending"
    assert document.parse_error is None


def test_reprocess_does_not_duplicate_active_document_work() -> None:
    for status in ("pending", "processing", "indexing", "parsing"):
        document = SimpleNamespace(parse_status=status, parse_error=None)

        assert not _prepare_document_reprocess(document)
        assert document.parse_status == status
