"""AWS Bedrock LLM provider (Claude on Bedrock)."""
from __future__ import annotations

import json

import boto3

from app.core.config import get_settings
from app.services.llm.base import (
    ASSESSMENT_SYSTEM_PROMPT,
    LLMFinding,
    LLMProvider,
    build_control_prompt,
)

settings = get_settings()


class BedrockProvider(LLMProvider):
    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or settings.bedrock_model_id
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )

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
        import asyncio
        user_prompt = build_control_prompt(
            control_id, control_title, control_statement,
            supplemental_guidance, chunks, system_context,
            assessment_objectives=assessment_objectives,
        )

        from app.services.prompt_manager import get_prompt
        system_prompt = await get_prompt("assessment_system", ASSESSMENT_SYSTEM_PROMPT)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.1,
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.invoke_model(
                    modelId=self.model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(request_body),
                ),
            )
            body = json.loads(response["body"].read())
            content = body["content"][0]["text"]
            return self._parse_response(content)
        except Exception as e:
            return LLMFinding.error(f"Bedrock error: {e}")

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Generic single-turn completion for non-assessment LLM calls."""
        import asyncio, json
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.1,
        }
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.invoke_model(
                    modelId=self.model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(request_body),
                ),
            )
            body = json.loads(response["body"].read())
            return body["content"][0]["text"]
        except Exception as e:
            raise RuntimeError(f"Bedrock complete() failed: {e}") from e

    async def embed(self, text: str) -> list[float]:
        from app.services.rag.embedder import local_embed
        return await local_embed(text)


def get_provider(
    provider_name: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> LLMProvider:
    """Factory function to get the right LLM provider.

    reasoning_effort applies to Ollama only: none | low | medium | high.
    'high' enables chain-of-thought (think:true) for supported models.
    """
    from app.services.llm.ollama_provider import OllamaProvider
    from app.services.llm.claude_provider import ClaudeProvider

    if provider_name == "ollama":
        return OllamaProvider(model=model, reasoning_effort=reasoning_effort)
    elif provider_name == "claude":
        return ClaudeProvider(model=model)
    elif provider_name == "bedrock":
        return BedrockProvider(model_id=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
