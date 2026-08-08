"""Persistence helpers for machine-readable screening corpora."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ControlCorpusVersion
from app.services.ingestion.config_store import DEFAULTS, set_value

logger = logging.getLogger(__name__)

DEFAULT_CORPUS_KEY = DEFAULTS["active_corpus_key"]
DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "corpora" / "nist_sp_800_53_rev5_default.json"
)


def _fallback_corpus_payload() -> dict:
    from app.services.ingestion import corpus as legacy_corpus

    return {
        "corpus_key": DEFAULT_CORPUS_KEY,
        "display_name": "NIST SP 800-53 Rev. 5 Default",
        "version": "bundled-fallback",
        "description": "Bundled fallback corpus generated from the legacy screening dictionary",
        "family_keywords": legacy_corpus.FAMILY_KEYWORDS,
        "control_keywords": legacy_corpus.CONTROL_KEYWORDS,
    }


def load_corpus_payload(path: Path | None = None) -> dict:
    target = path or DEFAULT_CORPUS_PATH
    if target.exists():
        return json.loads(target.read_text(encoding="utf-8"))
    logger.warning("Bundled corpus file missing at %s; using fallback dictionary payload", target)
    return _fallback_corpus_payload()


async def ensure_default_corpus(db: AsyncSession) -> ControlCorpusVersion:
    existing = await db.execute(
        select(ControlCorpusVersion).where(ControlCorpusVersion.corpus_key == DEFAULT_CORPUS_KEY)
    )
    corpus = existing.scalar_one_or_none()
    if corpus:
        return corpus

    payload = load_corpus_payload()
    corpus = ControlCorpusVersion(
        corpus_key=payload.get("corpus_key", DEFAULT_CORPUS_KEY),
        display_name=payload.get("display_name", "NIST SP 800-53 Rev. 5 Default"),
        version=payload.get("version", "bundled"),
        description=payload.get("description"),
        corpus_json=payload,
        is_active=True,
    )
    db.add(corpus)
    await db.flush()
    return corpus


async def list_corpora(db: AsyncSession) -> list[ControlCorpusVersion]:
    await ensure_default_corpus(db)
    result = await db.execute(
        select(ControlCorpusVersion).order_by(ControlCorpusVersion.created_at.desc())
    )
    return result.scalars().all()


async def get_active_corpus(db: AsyncSession) -> ControlCorpusVersion:
    await ensure_default_corpus(db)
    result = await db.execute(
        select(ControlCorpusVersion).where(ControlCorpusVersion.is_active == True)  # noqa: E712
    )
    corpus = result.scalar_one_or_none()
    if corpus:
        return corpus

    result = await db.execute(
        select(ControlCorpusVersion).where(ControlCorpusVersion.corpus_key == DEFAULT_CORPUS_KEY)
    )
    corpus = result.scalar_one()
    corpus.is_active = True
    await db.flush()
    return corpus


async def activate_corpus(
    db: AsyncSession,
    corpus_key: str,
    changed_by_id: int | None = None,
) -> ControlCorpusVersion:
    await ensure_default_corpus(db)
    result = await db.execute(
        select(ControlCorpusVersion).where(ControlCorpusVersion.corpus_key == corpus_key)
    )
    corpus = result.scalar_one_or_none()
    if not corpus:
        raise ValueError(f"Unknown corpus: {corpus_key}")

    await db.execute(update(ControlCorpusVersion).values(is_active=False))
    corpus.is_active = True
    await db.flush()
    await set_value(db, "active_corpus_key", corpus.corpus_key, changed_by_id=changed_by_id)
    return corpus


async def upsert_corpus(
    db: AsyncSession,
    payload: dict,
    changed_by_id: int | None = None,
) -> ControlCorpusVersion:
    corpus_key = str(payload.get("corpus_key") or "").strip()
    if not corpus_key:
        raise ValueError("corpus_key is required")
    display_name = str(payload.get("display_name") or corpus_key).strip()
    version = str(payload.get("version") or "custom").strip()

    result = await db.execute(
        select(ControlCorpusVersion).where(ControlCorpusVersion.corpus_key == corpus_key)
    )
    corpus = result.scalar_one_or_none()
    if corpus is None:
        corpus = ControlCorpusVersion(
            corpus_key=corpus_key,
            display_name=display_name,
            version=version,
            description=payload.get("description"),
            corpus_json=payload,
            created_by=changed_by_id,
            is_active=False,
        )
        db.add(corpus)
    else:
        corpus.display_name = display_name
        corpus.version = version
        corpus.description = payload.get("description")
        corpus.corpus_json = payload

    await db.flush()
    return corpus
