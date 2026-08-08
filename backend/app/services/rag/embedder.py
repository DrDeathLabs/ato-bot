"""Embedding provider for retrieval queries with provider-aware fallback."""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


async def embed_text_active(text: str) -> tuple[list[float], dict[str, str]]:
    """Embed one retrieval query using the configured active embedding provider."""
    from app.core.database import AsyncSessionLocal
    from app.services.ingestion.config_store import get_runtime_embedding_config
    from app.services.ingestion.embedding_provider import canonical_model_name, embed_texts_for_provider

    async with AsyncSessionLocal() as db:
        embed_config = await get_runtime_embedding_config(db)

    provider = embed_config["provider"]
    model = embed_config["model"]
    base_url = embed_config["base_url"]
    api_key = embed_config["api_key"]
    extra_headers = _parse_json_headers(embed_config["headers_json"])

    try:
        vectors = await embed_texts_for_provider(
            provider=provider,
            texts=[text],
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_secs=30,
            extra_headers=extra_headers,
        )
        if vectors and vectors[0] is not None:
            return vectors[0], {
                "provider": provider,
                "model": model,
                "canonical_model_name": canonical_model_name(provider, model),
            }
        raise RuntimeError(f"{provider} returned null embedding")
    except Exception as exc:
        logger.warning("%s embed failed (%s), falling back to local model", provider.capitalize(), exc)
        return await local_embed(text), {
            "provider": "local",
            "model": "all-mpnet-base-v2",
            "canonical_model_name": "local:all-mpnet-base-v2",
        }


async def embed_text_voyage(text: str) -> list[float]:
    """Legacy compatibility shim. Uses the active provider, not Voyage exclusively."""
    vector, _meta = await embed_text_active(text)
    return vector


async def embed_text(text: str, provider: str = "voyage") -> list[float]:
    return await embed_text_voyage(text)


async def embed_batch(texts: list[str], provider: str = "voyage") -> list[list[float]]:
    tasks = [embed_text_voyage(t) for t in texts]
    return await asyncio.gather(*tasks)


async def local_embed(text: str) -> list[float]:
    loop = asyncio.get_event_loop()
    model = _get_local_model()
    return await loop.run_in_executor(None, lambda: model.encode(text).tolist())


def _parse_json_headers(raw: str) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        import json

        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items()}
    except Exception:
        logger.warning("Invalid embedding_headers_json; ignoring custom headers")
    return None


@lru_cache(maxsize=1)
def _get_local_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-mpnet-base-v2")
