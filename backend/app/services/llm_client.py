"""Thin, injectable wrapper around the OpenAI SDK for structured generation.

First LLM integration in this codebase — no existing call/retry/schema-
validation precedent to copy (cover_letter.py's assemble_draft() is pure
string templating, zero model calls). This module is the seam every
generation call goes through, so it's built to be easily mockable in
tests (no real API calls anywhere in the test suite) and to enforce
02-architecture-overview.md §6's requirements directly: schema-constrained
output (JSON Schema strict mode, not free text), and "validation and
retry, not silent correction" — this module retries transient API errors
(network/timeout/rate-limit) itself, but a schema-valid-yet-unverified
response is the CALLER's retry to make (a corrective re-prompt with the
specific failure), not this module's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LlmCallError(Exception):
    """Transient/infra-level failure (network, timeout, rate limit, or a
    non-retryable API error) after exhausting retries."""


class LlmSchemaValidationError(Exception):
    """The response was not valid JSON, or the model refused to answer.
    Distinct from LlmCallError — this is a content problem, not a
    connectivity problem, and callers should treat it as a signal to
    retry with a corrective prompt, not to blindly resend the same call.
    """


@dataclass
class StructuredGenerationResult:
    data: dict
    prompt_tokens: int
    completion_tokens: int
    model: str


_TRANSIENT_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError)


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_request_timeout_seconds,
    )


def generate_structured(
    *,
    system_prompt: str,
    user_payload: str,
    json_schema: dict,
    schema_name: str,
    model: str | None = None,
    max_api_retries: int = 2,
    client: OpenAI | None = None,
) -> StructuredGenerationResult:
    """Call the chat completions API in JSON-schema strict mode.

    Message structure is a deliberate instruction/data split per
    10-security-plan.md §5: system_prompt is fixed template text only
    (never CV/job-post content); user_payload carries the untrusted,
    explicitly-framed data block. Callers (tailored_cv_generation.py) are
    responsible for building user_payload with that framing — this
    function doesn't inspect or modify either string.

    `client` is injectable so tests never construct a real OpenAI client
    (which would fail immediately without an API key) — pass a fake with
    a matching `.chat.completions.create` surface instead.
    """
    client = client or _get_client()
    model = model or settings.openai_model

    last_error: Exception | None = None
    response = None
    for attempt in range(max_api_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": True,
                    },
                },
            )
            break
        except _TRANSIENT_EXCEPTIONS as e:
            last_error = e
            logger.warning(
                "llm_transient_error", attempt=attempt, error=str(e), schema_name=schema_name,
            )
            continue
        except APIError as e:
            # Non-transient (bad request, auth, content policy, etc.) — no retry.
            raise LlmCallError(f"OpenAI API error: {e}") from e

    if response is None:
        raise LlmCallError(
            f"OpenAI API call failed after {max_api_retries + 1} attempts: {last_error}"
        )

    message = response.choices[0].message

    if message.refusal:
        raise LlmSchemaValidationError(f"Model refused to generate: {message.refusal}")

    if not message.content:
        raise LlmSchemaValidationError("Model returned empty content")

    try:
        data = json.loads(message.content)
    except json.JSONDecodeError as e:
        raise LlmSchemaValidationError(f"Response was not valid JSON: {e}") from e

    usage = response.usage
    return StructuredGenerationResult(
        data=data,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        model=response.model,
    )
