"""Voyage AI embedding generation for evidence units.

Stage 5 of the ingestion pipeline. Generates embeddings using the Voyage
API for each EvidenceUnit. Embeddings are stored separately from units
so they can be regenerated without losing classification metadata.

The Voyage API key is retrieved from the encrypted config store and is
NEVER logged or exposed. If no key is configured, this stage is skipped
and units are stored without embeddings.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)


class VoyageEmbeddingError(RuntimeError):
    """Raised when the Voyage embedding API call fails for a batch."""

    def __init__(self, message: str, retry_after_secs: int | None = None):
        super().__init__(message)
        self.retry_after_secs = retry_after_secs

# Voyage models and their output dimensions
VOYAGE_MODEL_DIMS = {
    "voyage-3":         1024,
    "voyage-3-large":   2048,
    "voyage-3-lite":    512,
    "voyage-finance-2": 1024,
    "voyage-law-2":     1024,
    "voyage-code-3":    1024,
}

# We store all embeddings in a Vector(1024) column.
# Models with dim != 1024 are truncated/padded to 1024.
TARGET_DIM = 1024


def _normalize_to_target(vec: list[float], target: int = TARGET_DIM) -> list[float]:
    """Truncate or zero-pad a vector to target dimension."""
    if len(vec) == target:
        return vec
    if len(vec) > target:
        return vec[:target]
    return vec + [0.0] * (target - len(vec))


def _parse_retry_after(header_value: str | None) -> int | None:
    if not header_value:
        return None
    try:
        seconds = int(header_value)
        return max(0, seconds)
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(header_value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        delta = (retry_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(delta))
    except (TypeError, ValueError, IndexError):
        return None


async def embed_texts(
    texts: list[str],
    api_key: str,
    model: str = "voyage-3",
    base_url: str = "https://api.voyageai.com/v1",
    timeout_secs: int = 30,
    input_type: str = "document",
    rate_limit_backoff_secs: int = 15,
) -> list[list[float] | None]:
    """Embed a batch of texts using the Voyage API.

    Returns a list of embedding vectors (same length as texts).
    Returns None for individual texts that failed.
    The API key is NEVER logged.
    """
    if not api_key or not texts:
        return [None] * len(texts)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": texts,
        "model": model,
        "input_type": input_type,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_secs) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        # Do NOT log the request headers (would expose API key)
        logger.error("Voyage API HTTP error: %s %s", e.response.status_code, e.response.reason_phrase)
        retry_after_secs = _parse_retry_after(e.response.headers.get("Retry-After"))
        if retry_after_secs is None and e.response.status_code == 429:
            retry_after_secs = max(0, rate_limit_backoff_secs)
        raise VoyageEmbeddingError(
            f"Voyage API HTTP error: {e.response.status_code} {e.response.reason_phrase}",
            retry_after_secs=retry_after_secs,
        ) from e
    except Exception as e:
        logger.error("Voyage API call failed: %s", type(e).__name__)
        raise VoyageEmbeddingError(f"Voyage API call failed: {type(e).__name__}") from e

    embeddings_data = data.get("data", [])
    results: list[list[float] | None] = [None] * len(texts)
    for item in embeddings_data:
        idx = item.get("index")
        vec = item.get("embedding")
        if idx is not None and vec is not None and isinstance(idx, int) and 0 <= idx < len(texts):
            results[idx] = _normalize_to_target(vec)

    return results


async def test_connection(api_key: str, model: str, base_url: str) -> dict:
    """Test Voyage API connectivity and authentication.

    Returns {"ok": bool, "error": str | None, "model": str}
    The API key is NEVER included in the return value or logged.
    """
    try:
        vecs = await embed_texts(
            texts=["connectivity test"],
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_secs=10,
        )
    except VoyageEmbeddingError as exc:
        return {"ok": False, "error": str(exc), "model": model}
    if vecs and vecs[0] is not None:
        return {"ok": True, "error": None, "model": model, "dimensions": len(vecs[0])}
    return {"ok": False, "error": "Embedding returned null — check API key and model name", "model": model}
