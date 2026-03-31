"""
app/services/ai_client.py
─────────────────────────
Claude API client supporting two backends:

  AI_BACKEND=anthropic  →  Direct Anthropic API  (uses ANTHROPIC_API_KEY)
  AI_BACKEND=bedrock    →  AWS Bedrock            (uses AWS_ACCESS_KEY_ID +
                                                   AWS_SECRET_ACCESS_KEY +
                                                   AWS_REGION)

The rest of the codebase is completely unaware of which backend is active.
All pipeline stages call claude_client.complete() and claude_client.complete_json()
exactly the same way regardless of backend.

Bedrock differences handled here:
  - Uses anthropic.AsyncAnthropicBedrock instead of AsyncAnthropic
  - Model IDs follow Bedrock's cross-region inference profile format
  - AWS credentials are passed directly (no boto3 session needed)
  - Bedrock raises the same anthropic.* exception types — retry logic unchanged
"""
from __future__ import annotations

from typing import Optional

import anthropic
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import AIProviderError


def _build_client() -> anthropic.AsyncAnthropic | anthropic.AsyncAnthropicBedrock:
    """
    Build the correct async Anthropic client based on AI_BACKEND setting.

    Called once at module load — the result is cached as `claude_client`.
    """
    if settings.using_bedrock:
        logger.info(
            f"AI backend: AWS Bedrock | region={settings.AWS_REGION} | "
            f"fast_model={settings.CLAUDE_FAST_MODEL}"
        )
        return anthropic.AsyncAnthropicBedrock(
            aws_access_key=settings.AWS_ACCESS_KEY_ID,
            aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
            aws_region=settings.AWS_REGION,
        )
    else:
        logger.info(
            f"AI backend: Anthropic direct | "
            f"fast_model={settings.CLAUDE_FAST_MODEL}"
        )
        return anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
        )


class ClaudeClient:
    """
    Unified async wrapper around the Anthropic SDK.

    Works identically whether the underlying client points at
    Anthropic's API or AWS Bedrock. All retry logic, token logging,
    and error normalisation live here.
    """

    def __init__(self) -> None:
        self._client = _build_client()
        self._backend = settings.AI_BACKEND

    @retry(
        retry=retry_if_exception_type(
            (anthropic.RateLimitError, anthropic.InternalServerError)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a single-turn completion to Claude (Anthropic or Bedrock).

        Args:
            prompt:      User message.
            system:      Optional system prompt.
            model:       Model ID. Defaults to CLAUDE_FAST_MODEL.
                         Must match the backend format:
                           anthropic → "claude-sonnet-4-6"
                           bedrock   → "us.anthropic.claude-sonnet-4-6-20251115-v1:0"
            max_tokens:  Override. Defaults to AI_MAX_TOKENS.
            temperature: Override. Defaults to AI_TEMPERATURE.

        Returns:
            Assistant text response as a string.

        Raises:
            AIProviderError: On unrecoverable API errors.
        """
        _model       = model       or settings.CLAUDE_FAST_MODEL
        _max_tokens  = max_tokens  or settings.AI_MAX_TOKENS
        _temperature = temperature if temperature is not None else settings.AI_TEMPERATURE

        kwargs: dict = {
            "model":      _model,
            "max_tokens": _max_tokens,
            "temperature": _temperature,
            "messages":   [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        try:
            logger.debug(
                f"Claude request | backend={self._backend} "
                f"model={_model} max_tokens={_max_tokens}"
            )
            response = await self._client.messages.create(**kwargs)

            usage = response.usage
            logger.info(
                f"Claude response | backend={self._backend} model={_model} "
                f"input_tokens={usage.input_tokens} "
                f"output_tokens={usage.output_tokens}"
            )

            return "\n".join(
                block.text
                for block in response.content
                if block.type == "text"
            )

        except anthropic.AuthenticationError as exc:
            if self._backend == "bedrock":
                logger.error(
                    "AWS Bedrock authentication failed. "
                    "Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
                )
                raise AIProviderError(
                    "AWS authentication failed. Verify your Access Key and Secret."
                ) from exc
            else:
                logger.error("Anthropic authentication failed — check ANTHROPIC_API_KEY")
                raise AIProviderError("Authentication failed with Claude API") from exc

        except anthropic.PermissionDeniedError as exc:
            # Bedrock: model not enabled in your AWS account / region
            logger.error(
                f"Permission denied on model {_model}. "
                "For Bedrock, ensure the model is enabled in your AWS console "
                "under Bedrock > Model Access."
            )
            raise AIProviderError(
                f"Access denied to model {_model}. "
                "Enable it in AWS Bedrock > Model Access."
            ) from exc

        except anthropic.BadRequestError as exc:
            logger.error(f"Claude bad request: {exc}")
            raise AIProviderError(f"Invalid request to Claude API: {exc}") from exc

        except (anthropic.RateLimitError, anthropic.InternalServerError):
            # Caught by tenacity for retry — re-raise after exhaustion
            raise

        except anthropic.APIError as exc:
            logger.error(f"Claude API error ({self._backend}): {exc}")
            raise AIProviderError(f"Claude API error: {exc}") from exc

    async def complete_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Completion that enforces JSON-only output.
        Appends a strict JSON instruction to the system prompt.

        Returns raw JSON string — caller is responsible for parsing.
        """
        json_instruction = (
            "You must respond with valid JSON only. "
            "Do not include markdown code fences, preamble, "
            "or any text outside the JSON object."
        )
        combined_system = (
            f"{system}\n\n{json_instruction}" if system else json_instruction
        )

        return await self.complete(
            prompt=prompt,
            system=combined_system,
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,  # Zero temperature for deterministic structured output
        )


# ── Module-level singleton ─────────────────────────────────────────────────
# Built once at import time — backend determined by AI_BACKEND env var.
claude_client = ClaudeClient()