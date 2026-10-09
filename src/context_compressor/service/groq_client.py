from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class GroqConfigurationError(RuntimeError):
    pass


class GroqRequestError(RuntimeError):
    pass


@dataclass(slots=True)
class GenerationResult:
    answer: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None


def get_groq_model() -> str:
    return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)


async def generate_answer(query: str, context: str) -> GenerationResult:
    """Generate a grounded answer with Groq's OpenAI-compatible chat API."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GroqConfigurationError(
            "GROQ_API_KEY is not configured. Add it to the project .env file and restart the API."
        )

    model = get_groq_model()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Answer the user's question using only the supplied context. "
                    "If the context does not contain the answer, say that the context "
                    "does not provide enough information. Do not invent facts."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context or '[No context was retained.]'}\n\nQuestion:\n{query}",
            },
        ],
        "temperature": 0,
        "max_completion_tokens": 1024,
    }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException as exc:
        logger.warning("Groq request timed out")
        raise GroqRequestError("Groq request timed out. Try again or reduce the input context.") from exc
    except httpx.RequestError as exc:
        logger.warning("Could not connect to the Groq API: %s", type(exc).__name__)
        raise GroqRequestError("Could not connect to the Groq API. Check the network and try again.") from exc

    latency_ms = (time.perf_counter() - start) * 1000.0
    if not response.is_success:
        message = "Groq API rejected the request."
        try:
            detail = response.json().get("error", {}).get("message")
            if isinstance(detail, str) and detail:
                message = detail[:500]
        except (ValueError, AttributeError, TypeError):
            pass
        logger.warning("Groq API returned HTTP %s", response.status_code)
        raise GroqRequestError(f"Groq API error (HTTP {response.status_code}): {message}")

    try:
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
        usage = result.get("usage") or {}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.exception("Groq API returned an invalid chat completion response")
        raise GroqRequestError("Groq API returned an invalid response.") from exc

    if not isinstance(answer, str) or not answer.strip():
        raise GroqRequestError("Groq API returned an empty answer.")

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    return GenerationResult(
        answer=answer.strip(),
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
        completion_tokens=completion_tokens if isinstance(completion_tokens, int) else None,
    )
