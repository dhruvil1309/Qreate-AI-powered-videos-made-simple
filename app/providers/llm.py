"""Model-agnostic LLM router.

`chat_json()` tries each configured provider in order (LLM_ORDER) and returns
parsed JSON from the first one that answers. If a provider errors, times out
or returns invalid JSON, the next one is tried. If none are available the
caller gets LLMUnavailable and falls back to its offline strategy.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from .. import config

log = logging.getLogger("qreate.llm")


class LLMUnavailable(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _gemini(system: str, user: str, temperature: float) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent"
    )
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": temperature},
    }
    r = httpx.post(
        url,
        params={"key": config.GEMINI_API_KEY},
        json=body,
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai_compatible(base: str, key: str, model: str, system: str, user: str, temperature: float) -> str:
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(system: str, user: str, temperature: float) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": 4000,
            "temperature": temperature,
            "system": system + "\nRespond with a single JSON object only. No prose, no code fences.",
            "messages": [{"role": "user", "content": user}],
        },
        timeout=config.HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


def _call(provider: str, system: str, user: str, temperature: float) -> str:
    if provider == "gemini":
        return _gemini(system, user, temperature)
    if provider == "groq":
        return _openai_compatible(
            "https://api.groq.com/openai/v1", config.GROQ_API_KEY, config.GROQ_MODEL, system, user, temperature
        )
    if provider == "openai":
        return _openai_compatible(
            "https://api.openai.com/v1", config.OPENAI_API_KEY, config.OPENAI_MODEL, system, user, temperature
        )
    if provider == "anthropic":
        return _anthropic(system, user, temperature)
    raise ValueError(f"Unknown provider {provider}")


def chat_json(system: str, user: str, temperature: float = 0.8) -> tuple[dict, str]:
    """Return (parsed_json, provider_name). Raises LLMUnavailable if all fail."""
    providers = config.llm_providers_available()
    if not providers:
        raise LLMUnavailable("No LLM API key configured (or OFFLINE_MODE=1).")
    errors = []
    for p in providers:
        for attempt in range(2):  # one retry per provider, e.g. for malformed JSON
            try:
                raw = _call(p, system, user, temperature)
                return _extract_json(raw), p
            except httpx.HTTPStatusError as e:
                errors.append(f"{p}: HTTP {e.response.status_code}")
                break  # auth / rate-limit errors won't fix themselves on retry
            except Exception as e:  # noqa: BLE001 - we want the fallback chain to be robust
                errors.append(f"{p}: {type(e).__name__}: {e}")
        log.warning("LLM provider %s failed, trying next", p)
    raise LLMUnavailable("All LLM providers failed: " + " | ".join(errors))
