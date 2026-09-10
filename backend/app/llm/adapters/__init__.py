"""S4 — provider wire adapters (D14). No provider SDKs, only httpx."""

from __future__ import annotations

from backend.app.llm.adapters.base import ChatResponse, ProviderAdapter
from backend.app.llm.adapters.gemini import GeminiAdapter
from backend.app.llm.adapters.ollama import OllamaAdapter
from backend.app.llm.adapters.openai_compatible import OpenAICompatibleAdapter

__all__ = [
    "ChatResponse",
    "GeminiAdapter",
    "OllamaAdapter",
    "OpenAICompatibleAdapter",
    "ProviderAdapter",
]
