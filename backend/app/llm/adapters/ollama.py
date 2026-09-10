"""Ollama local /api/chat adapter (D14)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.app.llm.adapters.base import ChatResponse


class OllamaAdapter:
    """POST {base_url}/api/chat (stream:false).

    Mappings: 200 -> ok; **503 model-loading -> unavailable (skip, never trip)**;
    connection refused -> unavailable; ``json_mode`` -> ``format: "json"``.
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
        url = f"{base_url.rstrip('/')}/api/chat"
        messages: list[dict[str, str]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            body["format"] = "json"
        started = time.monotonic()
        try:
            with httpx.Client(transport=self._transport, timeout=timeout) as client:
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
            data = resp.json()
            return ChatResponse(
                status="ok",
                content=(data.get("message") or {}).get("content") or "",
                model=data.get("model") or model,
                prompt_tokens=int(data.get("prompt_eval_count") or 0),
                completion_tokens=int(data.get("eval_count") or 0),
                latency_ms=latency_ms,
            )
        if resp.status_code == 503:
            return ChatResponse(
                status="unavailable",
                status_code=503,
                error_type="model_loading",
                latency_ms=latency_ms,
            )
        error_type = "http_error" if resp.status_code < 500 else "server_error"
        return ChatResponse(
            status="http_error",
            status_code=resp.status_code,
            error_type=error_type,
            latency_ms=latency_ms,
        )
