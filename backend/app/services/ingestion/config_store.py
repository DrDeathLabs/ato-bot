"""Ingestion pipeline configuration store."""
from __future__ import annotations

import base64
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, str] = {
    "embedding_provider": "voyage",
    "embedding_model": "",
    "embedding_base_url": "",
    "embedding_api_key": "",
    "embedding_headers_json": "",
    "embedding_max_concurrency": "1",
    "voyage_api_key": "",
    "voyage_model": "voyage-3",
    "voyage_base_url": "https://api.voyageai.com/v1",
    "voyage_max_concurrency": "1",
    "voyage_rate_limit_backoff_secs": "15",
    "ollama_connection_mode": "local",
    "ollama_base_url": "",
    "ollama_api_key": "",
    "ollama_headers_json": "",
    "ollama_reasoning_model": "",
    "ollama_vision_model": "qwen3.5:cloud",
    "ollama_screening_model": "gpt-oss:20b-cloud",
    "ollama_classify_model": "gpt-oss:20b-cloud",
    "ollama_reasoning_effort": "medium",
    "active_corpus_key": "nist-sp-800-53-rev5-default",
    "screening_mode": "llm",
    "screening_threshold": "0.15",
    "screening_batch_size": "24",
    "screening_max_concurrency": "6",
    "screening_reasoning_effort": "low",
    "screening_timeout_secs": "90",
    "expand_window_lines": "10",
    "expand_max_tokens": "800",
    "classify_max_concurrency": "8",
    "classify_reasoning_effort": "low",
    "classify_batch_size": "5",
    "embed_batch_size": "20",
    "classify_timeout_secs": "120",
    "embed_timeout_secs": "30",
    "max_retries": "3",
    "retry_delay_secs": "5",
}

SECRET_KEYS = {"voyage_api_key", "ollama_api_key", "embedding_api_key"}

DESCRIPTIONS: dict[str, str] = {
    "embedding_provider": "Active embedding backend: voyage or ollama. Retrieval and ingestion embeddings should use the same provider.",
    "embedding_model": "Embedding model name for the active provider. Leave blank to use the provider-specific default.",
    "embedding_base_url": "Optional override base URL for the active embedding provider",
    "embedding_api_key": "Optional API key or bearer token for the active embedding provider (stored encrypted)",
    "embedding_headers_json": "Optional JSON object of extra HTTP headers for embedding-provider requests",
    "embedding_max_concurrency": "Maximum number of concurrent embedding requests allowed for the active provider",
    "voyage_api_key": "Voyage AI API key for generating embeddings (stored encrypted)",
    "voyage_model": "Voyage embedding model name (for example voyage-3 or voyage-3-lite)",
    "voyage_base_url": "Voyage AI API base URL",
    "voyage_max_concurrency": "Maximum number of concurrent Voyage embedding requests allowed across the app",
    "voyage_rate_limit_backoff_secs": "Fallback wait time in seconds before retrying Voyage 429 rate-limit responses when Retry-After is absent",
    "ollama_connection_mode": "How the admin UI should describe the Ollama endpoint: local, cloud, or custom",
    "ollama_base_url": "Ollama-compatible base URL for reasoning calls and connection tests",
    "ollama_api_key": "Optional API key or bearer token for hosted Ollama-compatible endpoints (stored encrypted)",
    "ollama_headers_json": "Optional JSON object of extra HTTP headers for Ollama requests",
    "ollama_reasoning_model": "Ollama model name for reasoning calls; blank falls back to the environment default",
    "ollama_vision_model": "Ollama vision-capable model for deriving context from uploaded screenshots and images in assistant chat",
    "ollama_screening_model": "Optional Ollama model override for ingestion screening; defaults to gpt-oss:20b-cloud",
    "ollama_classify_model": "Optional Ollama model override for ingestion classification; defaults to gpt-oss:20b-cloud",
    "ollama_reasoning_effort": "Reasoning depth for Ollama models: none, low, medium, or high",
    "active_corpus_key": "Active machine-readable NIST corpus key used during ingestion screening",
    "screening_mode": "Screening engine mode: llm uses the reasoning model, heuristic uses the legacy keyword screen",
    "screening_threshold": "Minimum relevance score (0.0-1.0) for line promotion into context expansion",
    "screening_batch_size": "Number of parsed text units to screen per reasoning-model batch",
    "screening_max_concurrency": "Maximum number of concurrent screening requests allowed across the app",
    "screening_reasoning_effort": "Reasoning depth for ingestion screening: none, low, medium, or high",
    "screening_timeout_secs": "Timeout in seconds for each screening-model batch call",
    "expand_window_lines": "Fallback max lines above and below the trigger line for expansion",
    "expand_max_tokens": "Maximum token count for an expanded evidence unit",
    "classify_max_concurrency": "Maximum number of concurrent classification requests allowed across the app",
    "classify_reasoning_effort": "Reasoning depth for ingestion classification: none, low, medium, or high",
    "classify_batch_size": "Number of evidence units to send in each classification request batch",
    "embed_batch_size": "Number of evidence units to embed per Voyage API call",
    "classify_timeout_secs": "Timeout in seconds for each classification call",
    "embed_timeout_secs": "Timeout in seconds for each Voyage embedding call",
    "max_retries": "Maximum retry attempts for failed provider calls",
    "retry_delay_secs": "Delay in seconds between retry attempts",
}


def _get_fernet():
    from cryptography.fernet import Fernet
    from app.core.config import get_settings

    settings = get_settings()
    raw = hashlib.sha256(settings.secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_secret(value: str) -> bytes:
    return _get_fernet().encrypt(value.encode())


def decrypt_secret(data: bytes) -> str:
    return _get_fernet().decrypt(data).decode()


async def get_config(db: AsyncSession) -> dict[str, str]:
    """Return all config values with secrets masked."""
    from app.models.orm import IngestionConfig

    result = await db.execute(select(IngestionConfig))
    rows = {row.key: row for row in result.scalars().all()}
    output = dict(DEFAULTS)
    for key in DEFAULTS:
        row = rows.get(key)
        if not row:
            continue
        if row.is_secret:
            output[key] = "***" if row.value_encrypted else ""
        else:
            output[key] = row.value_text or DEFAULTS.get(key, "")
    return output


async def get_secret(db: AsyncSession, key: str) -> str:
    """Return a decrypted secret value or an empty string if unset."""
    from app.models.orm import IngestionConfig

    result = await db.execute(select(IngestionConfig).where(IngestionConfig.key == key))
    row = result.scalar_one_or_none()
    if row is None or not row.value_encrypted:
        return ""
    try:
        return decrypt_secret(row.value_encrypted)
    except Exception:
        logger.warning("Failed to decrypt secret config key: %s", key)
        return ""


async def get_value(db: AsyncSession, key: str) -> str:
    """Return a non-secret config value or the default."""
    from app.models.orm import IngestionConfig

    result = await db.execute(select(IngestionConfig).where(IngestionConfig.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key, "")
    if row.is_secret:
        return ""
    return row.value_text or DEFAULTS.get(key, "")


async def set_value(
    db: AsyncSession,
    key: str,
    value: str,
    changed_by_id: int | None = None,
) -> None:
    """Persist one config value and write an audit row."""
    from app.models.orm import IngestionConfig, IngestionConfigAudit

    is_secret = key in SECRET_KEYS
    result = await db.execute(select(IngestionConfig).where(IngestionConfig.key == key))
    row = result.scalar_one_or_none()

    if row is None:
        old_value = None
    elif is_secret:
        old_value = "<secret>" if row.value_encrypted else None
    else:
        old_value = row.value_text

    db.add(
        IngestionConfigAudit(
            config_key=key,
            old_value=old_value,
            new_value="<secret changed>" if is_secret else value,
            changed_by=changed_by_id,
        )
    )

    if row is None:
        row = IngestionConfig(
            key=key,
            is_secret=is_secret,
            description=DESCRIPTIONS.get(key),
            updated_by=changed_by_id,
        )
        db.add(row)

    if is_secret:
        row.value_encrypted = encrypt_secret(value) if value else None
        row.value_text = None
    else:
        row.value_text = value
        row.value_encrypted = None

    row.is_secret = is_secret
    row.updated_by = changed_by_id
    await db.flush()


async def get_screening_threshold(db: AsyncSession) -> float:
    value = await get_value(db, "screening_threshold")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(DEFAULTS["screening_threshold"])


async def get_int_value(db: AsyncSession, key: str) -> int:
    value = await get_value(db, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(DEFAULTS.get(key, "0"))


async def get_runtime_ollama_config(db: AsyncSession) -> dict[str, str]:
    """Return the resolved Ollama runtime config with env fallbacks."""
    from app.core.config import get_settings

    settings = get_settings()
    base_url = await get_value(db, "ollama_base_url")
    model = await get_value(db, "ollama_reasoning_model")
    reasoning_effort = await get_value(db, "ollama_reasoning_effort")
    return {
        "connection_mode": await get_value(db, "ollama_connection_mode") or DEFAULTS["ollama_connection_mode"],
        "base_url": base_url or settings.ollama_base_url,
        "model": model or settings.ollama_model,
        "reasoning_effort": reasoning_effort or settings.ollama_reasoning_effort,
        "api_key": await get_secret(db, "ollama_api_key"),
        "headers_json": await get_value(db, "ollama_headers_json"),
    }


async def get_runtime_embedding_config(db: AsyncSession) -> dict[str, str]:
    """Return the resolved embedding-provider config with provider-specific fallbacks."""
    provider = (await get_value(db, "embedding_provider") or DEFAULTS["embedding_provider"]).strip().lower()
    if provider == "ollama":
        ollama_cfg = await get_runtime_ollama_config(db)
        base_url = await get_value(db, "embedding_base_url")
        model = await get_value(db, "embedding_model")
        headers_json = await get_value(db, "embedding_headers_json")
        return {
            "provider": "ollama",
            "model": model or "qwen3-embedding:0.6b",
            "base_url": base_url or ollama_cfg["base_url"],
            "api_key": await get_secret(db, "embedding_api_key") or ollama_cfg["api_key"],
            "headers_json": headers_json or ollama_cfg["headers_json"],
            "max_concurrency": str(await get_int_value(db, "embedding_max_concurrency") or 1),
        }

    model = await get_value(db, "embedding_model")
    base_url = await get_value(db, "embedding_base_url")
    return {
        "provider": "voyage",
        "model": model or await get_value(db, "voyage_model") or DEFAULTS["voyage_model"],
        "base_url": base_url or await get_value(db, "voyage_base_url") or DEFAULTS["voyage_base_url"],
        "api_key": await get_secret(db, "embedding_api_key") or await get_secret(db, "voyage_api_key"),
        "headers_json": await get_value(db, "embedding_headers_json"),
        "max_concurrency": str(await get_int_value(db, "embedding_max_concurrency") or 1),
    }
