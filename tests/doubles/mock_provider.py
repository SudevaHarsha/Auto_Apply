"""Deterministic provider-adapter double for T4 (D14).

Test-only. Physically unreachable from ``backend/app`` (guarded by
``test_no_test_double_reachable_from_app``). Implements the same chat protocol as
the real adapters and pops scripted :class:`ChatResponse` outcomes off a queue —
the router tests never touch real providers or the network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.llm.adapters.base import ChatResponse


class MockProviderAdapter:
    """Pops the next scripted response per call; records every call for assertions."""

    def __init__(
        self,
        name: str,
        scheduled: list[ChatResponse] | None = None,
        log: list[str] | None = None,
    ) -> None:
        self.name = name
        self.scheduled = list(scheduled or [])
        self.calls: list[dict[str, Any]] = []
        self._log = log

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
        if self._log is not None:
            self._log.append(self.name)
            self.calls.append(
                {
                    "prompt": prompt,
                    "system_message": system_message,
                    "model": model,
                    "base_url": base_url,
                    "api_key": api_key,
                    "json_mode": json_mode,
                    "output_schema": output_schema,
                }
            )
        if self.scheduled:
            return self.scheduled.pop(0)
        return ChatResponse(status="ok", content="unscripted ok", model=model, latency_ms=1)


def scripted_factory(
    scripts: dict[str, list[ChatResponse]],
) -> tuple[Callable[[str], MockProviderAdapter], dict[str, MockProviderAdapter], list[str]]:
    """Build an adapter factory; returns (factory, adapters, call-order log)."""
    adapters: dict[str, MockProviderAdapter] = {}
    log: list[str] = []

    def factory(name: str) -> MockProviderAdapter:
        if name not in adapters:
            adapters[name] = MockProviderAdapter(name, scripts.get(name, []), log)
        return adapters[name]

    return factory, adapters, log


def ok(
    content: str = "mock reply", *, model: str = "m-model", pt: int = 10, ct: int = 20, latency: int = 5
) -> ChatResponse:
    return ChatResponse(
        status="ok", content=content, model=model, prompt_tokens=pt, completion_tokens=ct, latency_ms=latency
    )


def http(status: int = 500, *, error_type: str | None = None, latency: int = 2) -> ChatResponse:
    mapped = error_type or ("rate_limited" if status == 429 else "server_error" if status >= 500 else "http_error")
    return ChatResponse(status="http_error", status_code=status, error_type=mapped, latency_ms=latency)


def rate_limited(retry_after: float | None = None, *, latency: int = 2) -> ChatResponse:
    return ChatResponse(
        status="http_error", status_code=429, retry_after=retry_after, error_type="rate_limited", latency_ms=latency
    )


def timeout(latency: int = 2) -> ChatResponse:
    return ChatResponse(status="timeout", error_type="timeout", latency_ms=latency)


def unavailable(error_type: str = "model_loading", *, latency: int = 2) -> ChatResponse:
    return ChatResponse(status="unavailable", status_code=503, error_type=error_type, latency_ms=latency)


def invalid_key(latency: int = 2) -> ChatResponse:
    return ChatResponse(status="http_error", status_code=401, error_type="invalid_key", latency_ms=latency)
