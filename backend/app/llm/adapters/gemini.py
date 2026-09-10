"""Gemini generativelanguage REST adapter (D14)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.app.llm.adapters.base import ChatResponse


class GeminiAdapter:
    """POST {base_url}/v1beta/models/{model}:generateContent.

    Key travels in an ``x-goog-api-key`` header (REST transport, no SDK).
    ``json_mode`` -> ``generationConfig.responseMimeType="application/json"``
    (+ optional ``responseSchema``). Maps 429 -> Retry-After, 401 -> invalid-key,
    404 -> model_not_found, 5xx -> server_error, timeout -> timeout, connection
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
        url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
        body: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if system_message:
            body["system_instruction"] = {"parts": [{"text": system_message}]}
        if json_mode:
            generation: dict[str, Any] = {"responseMimeType": "application/json"}
            if output_schema:
                generation["responseSchema"] = output_schema
            body["generationConfig"] = generation
        headers = {"x-goog-api-key": api_key} if api_key else {}
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
                for candidate in data.get("candidates") or []:
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        if part.get("text"):
                            content = part["text"]
                            break
                    if content:
                        break
                usage = data.get("usageMetadata") or {}
                prompt_tokens = int(usage.get("promptTokenCount") or 0)
                completion_tokens = int(usage.get("candidatesTokenCount") or 0)
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
            retry_after = None
            raw = resp.headers.get("Retry-After")
            if raw:
                try:
                    retry_after = max(0.0, float(raw))
                except ValueError:
                    retry_after = None
            return ChatResponse(
                status="http_error",
                status_code=429,
                retry_after=retry_after,
                error_type="rate_limited",
                latency_ms=latency_ms,
            )
        error_type = (
            "invalid_key"
            if resp.status_code == 401
            else "model_not_found"
            if resp.status_code == 404
            else "server_error"
            if resp.status_code >= 500
            else "http_error"
        )
        return ChatResponse(
            status="http_error",
            status_code=resp.status_code,
            error_type=error_type,
            latency_ms=latency_ms,
        )
