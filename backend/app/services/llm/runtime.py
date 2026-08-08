from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.ingestion.config_store import (
    get_runtime_embedding_config,
    get_runtime_ollama_config,
    get_value,
)
from app.services.llm.bedrock_provider import get_provider

settings = get_settings()


@dataclass
class ResolvedLLMRuntime:
    purpose: str
    provider: str
    model: str
    reasoning_effort: str | None = None
    base_url: str | None = None
    source: str = "default"


_PURPOSE_MODEL_KEYS: dict[str, tuple[str | None, str | None]] = {
    "assessment_reasoning": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "ai_assist_notes": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "dissent_chat": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "chat_general": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "chat_workspace": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "chat_control": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "chat_remediation": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "chat_evidence": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "chat_vision": ("ollama_vision_model", "ollama_reasoning_effort"),
    "chat_admin_explainer": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "document_tagging": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "procedure_categorization": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "remediation_generation": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "test_dataset_generation": ("ollama_reasoning_model", "ollama_reasoning_effort"),
    "ingestion_screening": ("ollama_screening_model", "screening_reasoning_effort"),
    "ingestion_classification": ("ollama_classify_model", "classify_reasoning_effort"),
}


async def resolve_llm_runtime(
    db: AsyncSession,
    purpose: str,
    provider_name: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> ResolvedLLMRuntime:
    resolved_provider = (provider_name or settings.default_llm_provider or "ollama").strip().lower()

    if resolved_provider == "ollama":
        model_key, effort_key = _PURPOSE_MODEL_KEYS.get(
            purpose,
            ("ollama_reasoning_model", "ollama_reasoning_effort"),
        )
        ollama_cfg = await get_runtime_ollama_config(db)
        resolved_model = (model or "").strip()
        resolved_effort = (reasoning_effort or "").strip().lower()

        if not resolved_model and model_key:
            resolved_model = (await get_value(db, model_key)).strip()
        if not resolved_effort and effort_key:
            resolved_effort = (await get_value(db, effort_key)).strip().lower()

        resolved_model = resolved_model or ollama_cfg["model"]
        resolved_effort = resolved_effort or ollama_cfg["reasoning_effort"]
        source = "db-config" if not provider_name else "explicit"
        return ResolvedLLMRuntime(
            purpose=purpose,
            provider="ollama",
            model=resolved_model,
            reasoning_effort=resolved_effort,
            base_url=ollama_cfg["base_url"],
            source=source,
        )

    if resolved_provider == "claude":
        return ResolvedLLMRuntime(
            purpose=purpose,
            provider="claude",
            model=(model or settings.claude_model).strip(),
            source="explicit" if provider_name or model else "settings",
        )

    if resolved_provider == "bedrock":
        return ResolvedLLMRuntime(
            purpose=purpose,
            provider="bedrock",
            model=(model or settings.bedrock_model_id).strip(),
            source="explicit" if provider_name or model else "settings",
        )

    raise ValueError(f"Unknown LLM provider: {resolved_provider}")


async def build_provider_for_purpose(
    db: AsyncSession,
    purpose: str,
    provider_name: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
):
    runtime = await resolve_llm_runtime(
        db=db,
        purpose=purpose,
        provider_name=provider_name,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    provider = get_provider(
        runtime.provider,
        model=runtime.model,
        reasoning_effort=runtime.reasoning_effort,
    )
    return provider, runtime


async def get_runtime_model_map(db: AsyncSession) -> dict[str, dict]:
    purposes = [
        "assessment_reasoning",
        "ai_assist_notes",
        "dissent_chat",
        "chat_general",
        "chat_workspace",
        "chat_control",
        "chat_remediation",
        "chat_evidence",
        "chat_vision",
        "chat_admin_explainer",
        "document_tagging",
        "procedure_categorization",
        "remediation_generation",
        "test_dataset_generation",
        "ingestion_screening",
        "ingestion_classification",
    ]

    result: dict[str, dict] = {}
    for purpose in purposes:
        runtime = await resolve_llm_runtime(db, purpose=purpose)
        result[purpose] = {
            "provider": runtime.provider,
            "model": runtime.model,
            "reasoning_effort": runtime.reasoning_effort,
            "base_url": runtime.base_url,
            "source": runtime.source,
        }

    embedding_cfg = await get_runtime_embedding_config(db)
    result["embeddings"] = {
        "provider": embedding_cfg["provider"],
        "model": embedding_cfg["model"],
        "reasoning_effort": None,
        "base_url": embedding_cfg["base_url"],
        "source": "db-config",
    }
    return result
