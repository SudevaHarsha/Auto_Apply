"""OpenAI-compatible chat-completions adapter (Groq + OpenRouter, D14)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.app.llm.adapters.base import ChatResponse
from backend.app.llm.schema_dialects import openai_compatible_schema

OUTPUT_SCHEMA_NAME = "structured_output"
_CHAT_COMPLETIONS = "/chat/completions"


def _endpoint_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(_CHAT_COMPLETIONS):
        return base
    return base + _CHAT_COMPLETIONS


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a numeric Retry-After (seconds); HTTP-date values fall back to None."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class OpenAICompatibleAdapter:
    """POST {base_url}/chat/completions with ``Authorization: Bearer <key>``.

    Maps: 200 -> ok (content + usage), 429 -> http_error with ``Retry-After``,
    401 -> invalid-key failure, 5xx -> server_error, timeout -> timeout, connection
    error -> unavailable.
    """

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def chat(
        self,
        *,
        prompt: str,
        system_message: str | None = None,
        model: str,
        base_url: str,
        api_key: str | None = None,
        json_mode: bool = False,
        output_schema: dict[str, Any] | None = None,
        timeout: float = 20.0,
    ) -> ChatResponse:
        url = _endpoint_url(base_url)
        messages: list[dict[str, str]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {"model": model, "messages": messages}
        if json_mode:
            if output_schema:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": OUTPUT_SCHEMA_NAME,
                        "strict": True,
                        "schema": openai_compatible_schema(output_schema),
                    },
                }
            else:
                body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        started = time.monotonic()
        try:
            with httpx.Client(transport=self._transport, timeout=timeout, headers=headers) as client:
                resp = client.post(url, json=body)
        except httpx.TimeoutException:
            return ChatResponse(
                status="timeout", error_type="timeout", latency_ms=int((time.monotonic() - started) * 1000)
            )
        except httpx.HTTPError:
            return ChatResponse(
                status="unavailable",
                error_type="connection",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code == 200:
            try:
                data = resp.json()
                content = None
                for choice in data.get("choices") or []:
                    content = (choice.get("message") or {}).get("content")
                    if content:
                        break
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
            except (TypeError, ValueError):
                return ChatResponse(
                    status="http_error",
                    status_code=resp.status_code,
                    error_type="unparseable_body",
                    latency_ms=latency_ms,
                )
            return ChatResponse(
                status="ok",
                content=content or "",
                model=data.get("model") or model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )
        if resp.status_code == 429:
            return ChatResponse(
                status="http_error",
                status_code=429,
                retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
                error_type="rate_limited",
                latency_ms=latency_ms,
            )
        error_type = (
            "invalid_key" if resp.status_code == 401 else "server_error" if resp.status_code >= 500 else "http_error"
        )
        return ChatResponse(
            status="http_error",
            status_code=resp.status_code,
            error_type=error_type,
            latency_ms=latency_ms,
        )
