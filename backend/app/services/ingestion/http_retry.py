"""Bounded retry support for ingestion model HTTP calls."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429} or exc.response.status_code >= 500
    return False


async def post_json_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_secs: int,
    attempts: int = 3,
) -> httpx.Response:
    """POST JSON and retry only transient transport or service failures."""
    max_attempts = max(1, attempts)
    async with httpx.AsyncClient(timeout=timeout_secs) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response
            except Exception as exc:
                if attempt >= max_attempts or not is_retryable_http_error(exc):
                    raise
                delay = min(2 ** (attempt - 1), 4)
                logger.warning(
                    "Transient ingestion HTTP failure (%s); retrying attempt %s/%s in %ss",
                    type(exc).__name__,
                    attempt + 1,
                    max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
    raise RuntimeError("Ingestion HTTP retry loop exited unexpectedly")
