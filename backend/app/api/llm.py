"""LLM utility endpoints — model discovery, health checks."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_viewer
from app.services.llm.runtime import get_runtime_model_map, resolve_llm_runtime
from app.services.llm.ollama_provider import OllamaProvider

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/ollama/models")
async def list_ollama_models(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    """Return Ollama models, including configured cloud models that /api/tags omits."""
    try:
        assessment_runtime = await resolve_llm_runtime(db, "assessment_reasoning")
        provider = OllamaProvider(
            model=assessment_runtime.model,
            base_url=assessment_runtime.base_url,
            reasoning_effort=assessment_runtime.reasoning_effort,
        )
        models = await provider.list_models()
        runtime_routes = await get_runtime_model_map(db)
        configured_models = [
            route.get("model")
            for route in runtime_routes.values()
            if route.get("provider") == "ollama" and route.get("model")
        ]
        all_models = list(dict.fromkeys([provider.model, *configured_models, *models]))
        return {
            "models": all_models,
            "base_url": provider.base_url,
            "default": provider.model,
            "assessment_default": assessment_runtime.model,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama: {e}")


@router.get("/runtime-map")
async def runtime_map(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_viewer),
) -> dict:
    assessment_runtime = await resolve_llm_runtime(db, "assessment_reasoning")
    return {
        "default_ollama_base_url": assessment_runtime.base_url,
        "routes": await get_runtime_model_map(db),
    }
