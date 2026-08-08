"""Provider-agnostic embedding helpers for ingestion and retrieval."""
from __future__ import annotations

from app.services.ingestion.ollama_embedder import embed_texts as ollama_embed_texts
from app.services.ingestion.voyage_embedder import VOYAGE_MODEL_DIMS, embed_texts as voyage_embed_texts


def canonical_model_name(provider: str, model: str) -> str:
    return f"{provider.strip().lower()}:{model.strip()}"


def infer_provider_from_model_name(model_name: str | None) -> str | None:
    if not model_name:
        return None
    lowered = model_name.strip().lower()
    if lowered.startswith("voyage:"):
        return "voyage"
    if lowered.startswith("ollama:"):
        return "ollama"
    if lowered.startswith("voyage-") or lowered in {name.lower() for name in VOYAGE_MODEL_DIMS}:
        return "voyage"
    return "ollama"


def accepted_model_names(provider: str, model: str) -> list[str]:
    normalized_provider = provider.strip().lower()
    names = [canonical_model_name(normalized_provider, model)]
    if normalized_provider == "voyage":
        names.append(model)
    return names


async def embed_texts_for_provider(
    *,
    provider: str,
    texts: list[str],
    model: str,
    base_url: str,
    timeout_secs: int,
    api_key: str = "",
    extra_headers: dict[str, str] | None = None,
    rate_limit_backoff_secs: int = 15,
) -> list[list[float] | None]:
    normalized_provider = provider.strip().lower()
    if normalized_provider == "ollama":
        return await ollama_embed_texts(
            texts=texts,
            model=model,
            base_url=base_url,
            timeout_secs=timeout_secs,
            api_key=api_key,
            extra_headers=extra_headers,
        )
    return await voyage_embed_texts(
        texts=texts,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_secs=timeout_secs,
        input_type="document",
        rate_limit_backoff_secs=rate_limit_backoff_secs,
    )
