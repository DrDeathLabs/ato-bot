from app.services.ingestion.config_store import DEFAULTS


def test_ingestion_timeouts_support_full_package_processing() -> None:
    assert int(DEFAULTS["screening_timeout_secs"]) >= 180
    assert int(DEFAULTS["classify_timeout_secs"]) >= 180
    assert int(DEFAULTS["embed_timeout_secs"]) >= 120
