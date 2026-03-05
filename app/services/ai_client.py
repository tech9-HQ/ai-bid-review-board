"""
app/services/ai_client.py
──────────────────────────
Thin, reusable wrappers around OpenAI and Anthropic SDKs.

Both clients:
  - Accept a system prompt + user prompt
  - Return parsed dict (from JSON response)
  - Raise AIProviderError / AIResponseParseError on failure
  - Log token usage for cost tracking
"""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.exceptions import AIProviderError, AIResponseParseError


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` markdown fences."""
    return re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()


def _parse_json_response(raw: str, context: str) -> dict[str, Any]:
    """
    Attempt to parse LLM output as JSON.
    Raises AIResponseParseError with full raw output on failure.
    """
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(f"[{context}] JSON parse failed:\n{cleaned[:500]}")
        raise AIResponseParseError(
            f"AI returned invalid JSON during {context}.",
            detail=f"Parse error: {exc}. Raw (first 500 chars): {cleaned[:500]}",
        ) from exc


# ── OpenAI Client ─────────────────────────────────────────────────────────────

class OpenAIClient:
    def __init__(self) -> None:
        from openai import OpenAI, APIError, RateLimitError, APITimeoutError
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._APIError = APIError
        self._RateLimitError = RateLimitError
        self._APITimeoutError = APITimeoutError

    def chat(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: str = "openai",
    ) -> dict[str, Any]:
        """
        Call OpenAI chat completion and return parsed JSON dict.
        """
        _model = model or settings.OPENAI_AUDIT_MODEL
        _temp = temperature if temperature is not None else settings.AI_TEMPERATURE
        _max_tokens = max_tokens or settings.AI_MAX_TOKENS

        logger.info(f"[OpenAI] {context} | model={_model} | temp={_temp}")

        try:
            response = self._client.chat.completions.create(
                model=_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=_temp,
                max_tokens=_max_tokens,
                response_format={"type": "json_object"},  # Force JSON mode
            )
        except self._RateLimitError as exc:
            raise AIProviderError("OpenAI rate limit reached.", detail=str(exc)) from exc
        except self._APITimeoutError as exc:
            raise AIProviderError("OpenAI request timed out.", detail=str(exc)) from exc
        except self._APIError as exc:
            raise AIProviderError(f"OpenAI API error: {exc.message}", detail=str(exc)) from exc

        raw = response.choices[0].message.content or ""

        # Log token usage
        usage = response.usage
        if usage:
            logger.info(
                f"[OpenAI] {context} | "
                f"prompt_tokens={usage.prompt_tokens} | "
                f"completion_tokens={usage.completion_tokens} | "
                f"total={usage.total_tokens}"
            )

        return _parse_json_response(raw, context)

    def chat_text(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: str = "openai",
    ) -> str:
        """Call OpenAI and return raw text (no JSON parsing)."""
        _model = model or settings.OPENAI_AUDIT_MODEL
        _temp = temperature if temperature is not None else settings.AI_TEMPERATURE
        _max_tokens = max_tokens or settings.AI_MAX_TOKENS

        try:
            response = self._client.chat.completions.create(
                model=_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=_temp,
                max_tokens=_max_tokens,
            )
        except Exception as exc:
            raise AIProviderError(f"OpenAI error: {exc}", detail=str(exc)) from exc

        return response.choices[0].message.content or ""


# ── Anthropic (Claude) Client ─────────────────────────────────────────────────

class AnthropicClient:
    def __init__(self) -> None:
        if not settings.ANTHROPIC_API_KEY:
            # Deferred — client unusable until key is provided
            self._client = None
            self._anthropic = None
            return
        import anthropic
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._anthropic = anthropic

    def is_available(self) -> bool:
        return self._client is not None

    def chat(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context: str = "claude",
    ) -> dict[str, Any]:
        """
        Call Claude and return parsed JSON dict.
        """
        if not self.is_available():
            raise AIProviderError(
                "Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env to enable Stage 5 legal review.",
                detail="ANTHROPIC_API_KEY is missing or empty.",
            )
        _model = model or settings.CLAUDE_LEGAL_MODEL
        _temp = temperature if temperature is not None else settings.AI_TEMPERATURE
        _max_tokens = max_tokens or settings.AI_MAX_TOKENS

        logger.info(f"[Claude] {context} | model={_model} | temp={_temp}")

        try:
            response = self._client.messages.create(
                model=_model,
                max_tokens=_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=_temp,
            )
        except self._anthropic.RateLimitError as exc:
            raise AIProviderError("Anthropic rate limit reached.", detail=str(exc)) from exc
        except self._anthropic.APITimeoutError as exc:
            raise AIProviderError("Anthropic request timed out.", detail=str(exc)) from exc
        except self._anthropic.APIError as exc:
            raise AIProviderError(f"Anthropic API error: {exc}", detail=str(exc)) from exc

        raw = response.content[0].text if response.content else ""

        # Log token usage
        usage = response.usage
        logger.info(
            f"[Claude] {context} | "
            f"input_tokens={usage.input_tokens} | "
            f"output_tokens={usage.output_tokens}"
        )

        return _parse_json_response(raw, context)