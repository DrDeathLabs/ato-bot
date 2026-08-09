"""Ollama-compatible embedding generation for evidence units and queries."""
from __future__ import annotations

import logging

import httpx

from app.services.ingestion.http_retry import post_json_with_retry

logger = logging.getLogger(__name__)

TARGET_DIM = 1024


class OllamaEmbeddingError(RuntimeError):
    """Raised when the Ollama embedding API call fails for a batch."""


def _normalize_to_target(vec: list[float], target: int = TARGET_DIM) -> list[float]:
    if len(vec) == target:
        return vec
    if len(vec) > target:
        return vec[:target]
    return vec + [0.0] * (target - len(vec))


async def embed_texts(
    texts: list[str],
    model: str,
    base_url: str,
    timeout_secs: int = 30,
    api_key: str = "",
    extra_headers: dict[str, str] | None = None,
) -> list[list[float] | None]:
    if not texts:
        return []

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "input": texts,
    }

    try:
        resp = await post_json_with_retry(
            f"{base_url.rstrip('/')}/api/embed",
            headers=headers,
            payload=payload,
            timeout_secs=timeout_secs,
        )
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Ollama embed HTTP error: %s %s", exc.response.status_code, exc.response.reason_phrase)
        raise OllamaEmbeddingError(
            f"Ollama embed HTTP error: {exc.response.status_code} {exc.response.reason_phrase}"
        ) from exc
    except Exception as exc:
        logger.error("Ollama embed call failed: %s", type(exc).__name__)
        raise OllamaEmbeddingError(f"Ollama embed call failed: {type(exc).__name__}") from exc

    embeddings = data.get("embeddings") or []
    results: list[list[float] | None] = [None] * len(texts)
    for idx, vec in enumerate(embeddings[: len(texts)]):
        if vec is None:
            continue
        results[idx] = _normalize_to_target([float(v) for v in vec])
    return results


async def test_connection(
    model: str,
    base_url: str,
    api_key: str = "",
    extra_headers: dict[str, str] | None = None,
) -> dict:
    try:
        vectors = await embed_texts(
            texts=["connectivity test"],
            model=model,
            base_url=base_url,
            timeout_secs=20,
            api_key=api_key,
            extra_headers=extra_headers,
        )
    except OllamaEmbeddingError as exc:
        return {"ok": False, "error": str(exc), "model": model, "base_url": base_url}
    if vectors and vectors[0] is not None:
        return {
            "ok": True,
            "error": None,
            "model": model,
            "base_url": base_url,
            "dimensions": len(vectors[0]),
        }
    return {"ok": False, "error": "Embedding returned null", "model": model, "base_url": base_url}
