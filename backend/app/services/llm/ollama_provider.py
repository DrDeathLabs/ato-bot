"""Ollama LLM provider — primary provider for local models."""
from __future__ import annotations

import base64
import httpx
from ollama import AsyncClient

from app.core.config import get_settings
from app.services.llm.base import (
    ASSESSMENT_SYSTEM_PROMPT,
    LLMFinding,
    LLMProvider,
    build_control_prompt,
)

settings = get_settings()


def _encode_image_path(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _ollama_think_options(reasoning_effort: str) -> dict:
    """Map reasoning_effort to Ollama API extra params.

    For models like gpt-oss:120b-cloud, reasoning_effort is passed inside
    the options dict.  For models that use the think: bool flag (QwQ, etc.),
    we also set think accordingly.
    Returns a dict that can be merged into the chat/generate request body.
    """
    effort_map = {
        "none":   {"think": False, "options_extra": {"reasoning_effort": "none"}},
        "low":    {"think": False, "options_extra": {"reasoning_effort": "low"}},
        "medium": {"think": True,  "options_extra": {"reasoning_effort": "medium"}},
        "high":   {"think": True,  "options_extra": {"reasoning_effort": "high"}},
    }
    return effort_map.get(reasoning_effort, {"think": True, "options_extra": {"reasoning_effort": "high"}})


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        num_ctx: int | None = None,
        reasoning_effort: str | None = None,
    ):
        self.model = model or settings.ollama_model
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.num_ctx = num_ctx or settings.ollama_num_ctx
        self.reasoning_effort = reasoning_effort or settings.ollama_reasoning_effort

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
        from app.services.prompt_manager import get_prompt
        system_prompt = await get_prompt("assessment_system", ASSESSMENT_SYSTEM_PROMPT)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        think_params = _ollama_think_options(self.reasoning_effort)
        options = {
            "num_ctx": self.num_ctx,
            "temperature": 0.0,   # fully deterministic — same evidence → same result
            "seed": 42,           # fixed seed for reproducibility across runs
            **think_params.pop("options_extra", {}),
        }

        client = AsyncClient(host=self.base_url)

        for attempt in range(2):
            try:
                response = await client.chat(
                    model=self.model,
                    messages=messages,
                    options=options,
                    format="json",
                    **think_params,
                )
                content = response.message.content
                finding = self._parse_response(content)
                if finding.parse_failed and not finding.raw_response:
                    finding.raw_response = content
                if not finding.parse_failed:
                    return finding
                # On first parse failure, retry with a shorter prompt
                if attempt == 0:
                    messages = [
                        {"role": "system", "content": ASSESSMENT_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"Control {control_id}: {control_title}\n\n"
                                f"Evidence: {chr(10).join(c['content'] if isinstance(c, dict) else c for c in chunks[:3])[:2000]}\n\n"
                                "Return ONLY a JSON object: "
                                '{"status":"compliant"|"partially_compliant"|"non_compliant"|"not_applicable",'
                                '"implementation_statement":"<brief>","gaps":[],"evidence_citations":[],'
                                '"remediation_plan":"","confidence":0.5}'
                            ),
                        },
                    ]
                    continue
                return finding
            except Exception as e:
                if attempt == 0:
                    continue
                return LLMFinding.error(f"Ollama error: {e}")

        return LLMFinding.error("Ollama: no valid response after retries", raw="")

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Generic single-turn completion for non-assessment LLM calls."""
        client = AsyncClient(host=self.base_url)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        think_params = _ollama_think_options(self.reasoning_effort)
        options = {"num_ctx": self.num_ctx, "temperature": 0.1, **think_params.pop("options_extra", {})}
        try:
            response = await client.chat(
                model=self.model, messages=messages, options=options, **think_params
            )
            return response.message.content
        except Exception as e:
            raise RuntimeError(f"Ollama complete() failed: {e}") from e

    async def complete_multimodal(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[str],
    ) -> str:
        think_params = _ollama_think_options(self.reasoning_effort)
        options = {"num_ctx": self.num_ctx, "temperature": 0.1, **think_params.pop("options_extra", {})}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [_encode_image_path(path) for path in image_paths],
                },
            ],
            "options": options,
            **think_params,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as http:
                response = await http.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
                return (data.get("message") or {}).get("content", "")
        except Exception as e:
            raise RuntimeError(f"Ollama complete_multimodal() failed: {e}") from e

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using Ollama embedding model."""
        payload = {"model": settings.ollama_embedding_model, "prompt": text}
        async with httpx.AsyncClient(timeout=60.0) as http:
            response = await http.post(f"{self.base_url}/api/embeddings", json=payload)
            response.raise_for_status()
            return response.json()["embedding"]

    async def list_models(self) -> list[str]:
        """List available models from Ollama."""
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]
