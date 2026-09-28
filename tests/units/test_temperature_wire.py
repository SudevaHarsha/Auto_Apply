"""S9 determinism: the temperature lever reaches the wire (tests/units).

The eval call sends ``temperature=0.3`` (determinism guard against provider
defaults ~1.0); every adapter must forward it into its request body and omit it
when unset so default behavior is byte-identical for callers that pass None.
"""

from __future__ import annotations

import json

import httpx

from backend.app.llm.adapters.gemini import GeminiAdapter
from backend.app.llm.adapters.ollama import OllamaAdapter
from backend.app.llm.adapters.openai_compatible import OpenAICompatibleAdapter


def _capture(cap: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


def test_openai_compatible_sends_temperature_when_set() -> None:
    cap: dict[str, object] = {}
    resp = OpenAICompatibleAdapter(transport=_capture(cap)).chat(
        prompt="hi",
        system_message=None,
        model="m",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
        temperature=0.3,
    )
    assert resp.status == "ok"
    assert json.loads(cap["body"])["temperature"] == 0.3


def test_openai_compatible_omits_temperature_when_unset() -> None:
    cap: dict[str, object] = {}
    OpenAICompatibleAdapter(transport=_capture(cap)).chat(
        prompt="hi",
        system_message=None,
        model="m",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
    )
    assert "temperature" not in json.loads(cap["body"])


def test_gemini_sends_temperature_in_generation_config() -> None:
    cap: dict[str, object] = {}
    GeminiAdapter(transport=_capture(cap)).chat(
        prompt="hi",
        system_message=None,
        model="m",
        base_url="https://generativelanguage.googleapis.com",
        api_key="k",
        json_mode=True,
        temperature=0.3,
    )
    generation = json.loads(cap["body"])["generationConfig"]
    assert generation["temperature"] == 0.3
    assert generation["responseMimeType"] == "application/json"


def test_gemini_omits_temperature_when_unset() -> None:
    cap: dict[str, object] = {}
    GeminiAdapter(transport=_capture(cap)).chat(
        prompt="hi",
        system_message=None,
        model="m",
        base_url="https://generativelanguage.googleapis.com",
        api_key="k",
        max_output_tokens=100,
    )
    generation = json.loads(cap["body"])["generationConfig"]
    assert "temperature" not in generation
    assert generation["maxOutputTokens"] == 100


def test_ollama_sends_temperature_when_set() -> None:
    cap: dict[str, object] = {}
    OllamaAdapter(transport=_capture(cap)).chat(
        prompt="hi",
        system_message=None,
        model="m",
        base_url="http://localhost:11434",
        api_key=None,
        temperature=0.3,
    )
    assert json.loads(cap["body"])["temperature"] == 0.3


def test_ollama_omits_temperature_when_unset() -> None:
    cap: dict[str, object] = {}
    OllamaAdapter(transport=_capture(cap)).chat(
        prompt="hi",
        system_message=None,
        model="m",
        base_url="http://localhost:11434",
        api_key=None,
    )
    assert "temperature" not in json.loads(cap["body"])
