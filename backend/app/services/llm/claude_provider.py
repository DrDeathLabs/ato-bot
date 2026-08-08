"""Claude (Anthropic) LLM provider."""
from __future__ import annotations

import anthropic

from app.core.config import get_settings
from app.services.llm.base import (
    ASSESSMENT_SYSTEM_PROMPT,
    LLMFinding,
    LLMProvider,
    build_control_prompt,
)

settings = get_settings()


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or settings.claude_model
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)

    async def assess_control(
        self,
        control_id: str,
        control_title: str,
        control_statement: str,
        supplemental_guidance: str,
        chunks: list[str | dict],
        system_context: str = "",
        assessment_objectives: list[str] | None = None,
    ) -> LLMFinding:
        user_prompt = build_control_prompt(
            control_id, control_title, control_statement,
            supplemental_guidance, chunks, system_context,
            assessment_objectives=assessment_objectives,
        )
        try:
            from app.services.prompt_manager import get_prompt
            system_prompt = await get_prompt("assessment_system", ASSESSMENT_SYSTEM_PROMPT)
            message = await self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.1,
            )
            content = message.content[0].text
            return self._parse_response(content)
        except anthropic.APIError as e:
            return LLMFinding.error(f"Claude API error: {e}")
        except Exception as e:
            return LLMFinding.error(f"Claude error: {e}")

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Generic single-turn completion for non-assessment LLM calls."""
        try:
            message = await self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.1,
            )
            return message.content[0].text
        except Exception as e:
            raise RuntimeError(f"Claude complete() failed: {e}") from e

    async def embed(self, text: str) -> list[float]:
        """Claude doesn't have a dedicated embeddings API — use sentence-transformers fallback."""
        from app.services.rag.embedder import local_embed
        return await local_embed(text)
