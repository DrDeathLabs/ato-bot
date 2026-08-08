"""Public product metadata used to keep clients aligned with backend capability state."""
from fastapi import APIRouter

from app.core.config import get_settings
from app.core.features import feature_registry

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/features")
async def list_features() -> dict:
    settings = get_settings()
    features = feature_registry(settings)
    return {
        "schema_version": 1,
        "product": settings.app_name,
        "features": features,
        "enabled": {item["key"]: item["enabled"] for item in features},
    }
