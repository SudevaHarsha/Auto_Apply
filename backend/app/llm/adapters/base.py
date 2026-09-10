"""Adapter protocol + result types (S4/D14).

Each adapter is a thin wire-level REST client over ``httpx`` — the only runtime
transport (provider SDKs are deliberately absent, D14). A provider call ALWAYS
returns a :class:`ChatResponse`; the router decides breaker/usage semantics, never
an adapter. ``json_mode`` / ``output_schema`` are strictly opt-in (D20); the
default path is byte-identical to the canonical contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

ResponseStatus = Literal["ok", "http_error", "unavailable", "timeout"]


@dataclass
class ChatResponse:
    status: ResponseStatus
    content: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    status_code: int | None = None
    retry_after: float | None = None
    error_type: str | None = None


class ProviderAdapter(Protocol):
    """Wire-level chat adapter. Never raises for remote outcomes."""

    def chat(
        self,
        *,
        prompt: str,
        system_message: str | None,
        model: str,
        base_url: str,
        api_key: str | None = None,
        json_mode: bool = False,
        output_schema: dict[str, Any] | None = None,
        timeout: float = 20.0,
    ) -> ChatResponse: ...
