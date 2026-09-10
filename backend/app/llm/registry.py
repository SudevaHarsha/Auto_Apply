"""Provider registry (S4/D19) — the single capability gate.

Migration 027 lifted the 4-name CHECK from ``llm_providers``; *what may run* is now
defined here, in code. There is **no database table** — this module is the only
source of truth:

- ``add_provider`` validates ``name`` against it (unregistered -> ``VALIDATION_ERROR`` 422).
- ``route_llm_request`` treats a resolved-but-unregistered name as **unavailable** (skip, D15).
- S3's ``llm_chain`` settings validation is registry-membership based (D19).

New providers = one registry entry (+ an adapter only for non-OpenAI-compatible
protocols); no migration ever again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.app.llm.adapters.gemini import GeminiAdapter
from backend.app.llm.adapters.ollama import OllamaAdapter
from backend.app.llm.adapters.openai_compatible import OpenAICompatibleAdapter

if TYPE_CHECKING:
    from backend.app.llm.adapters.base import ProviderAdapter


@dataclass(frozen=True)
class ProviderSpec:
    adapter: type[ProviderAdapter]
    default_base_url: str
    default_model: str


REGISTRY: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(GeminiAdapter, "https://generativelanguage.googleapis.com", "gemini-2.0-flash"),
    "ollama": ProviderSpec(OllamaAdapter, "http://localhost:11434", "llama3"),
    "groq": ProviderSpec(OpenAICompatibleAdapter, "https://api.groq.com/openai/v1", "llama-3.1-70b-versatile"),
    "openrouter": ProviderSpec(OpenAICompatibleAdapter, "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
}


def is_registered(name: str) -> bool:
    return name in REGISTRY


def spec_for(name: str) -> ProviderSpec | None:
    return REGISTRY.get(name)


def registered_names() -> tuple[str, ...]:
    return tuple(REGISTRY)
