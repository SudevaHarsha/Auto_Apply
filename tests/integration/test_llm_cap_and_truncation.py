"""4.3 — JD-aware output-token caps + truncation honesty (D1-D4, D2a/b/c).

Covers the finalized 4.3 design end-to-end:

* ``backend.app.llm.limits`` formula pins — ``cap = max(BASE=6000, calc)`` (the
  calculation only ever *raises* the base), responsibilities-driven ``echo_pool``,
  ``budget_expected = input + predicted output`` (the realistic per-step output,
  NOT the wire cap), and the exact input count (D2a).
* Adapter wire behavior — the computed cap reaches the provider wire
  (``max_tokens`` / ``maxOutputTokens`` / ``num_predict``) and truncation is
  *detected*, not guessed (``finish_reason="length"``, ``finishReason="MAX_TOKENS"``,
  ``done_reason="length"``, plus the usage-arithmetic fallback) (D1/D3).
* Router pass-through — ``route_llm_request`` forwards ``max_output_tokens`` to the
  adapter and returns ``truncated`` on the ``LLMResponse`` (D1).
* D2c budget gating — a provider whose ``tpm`` cannot fit ``input + predicted
  output`` (realistic completion, not the safety ceiling) is ``budget_skip``-ped
  *before* any call (no usage row, no breaker), while a provider that fits still
  gets called.
* Consumer honesty (D4) — a truncated rubric/eval never reaches ``_coerce_rubric``
  (no silent JSON repair): it raises with ``output_truncated`` + ``can_continue``,
  preserving a content prefix for the interactive park-and-ask lane.

Zero-network: adapters are ``httpx.MockTransport`` doubles; scoring flows use the
scripted mock sequencer from ``tests.doubles``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import psycopg
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

from backend.app.auth.service import AuthResult, AuthService  # noqa: E402
from backend.app.core_engine.errors import RubricGenerationFailedError, ScoringFailedError  # noqa: E402
from backend.app.db.context import DbContext  # noqa: E402
from backend.app.llm.adapters.gemini import GeminiAdapter  # noqa: E402
from backend.app.llm.adapters.ollama import OllamaAdapter  # noqa: E402
from backend.app.llm.adapters.openai_compatible import OpenAICompatibleAdapter  # noqa: E402
from backend.app.llm.errors import ProvidersExhaustedError  # noqa: E402
from backend.app.llm.limits import (  # noqa: E402
    ALLOWANCE_RUBRIC,
    BASE_OUTPUT_TOKENS,
    PREDICTED_OUTPUT_DEFAULT,
    PREDICTED_OUTPUT_EVAL,
    PREDICTED_OUTPUT_RUBRIC,
    SCAFFOLD_BOUND_RUBRIC,
    budget_expected,
    count_prompt_tokens,
    echo_pool_tokens,
    estimate_eval_cap,
    estimate_rubric_cap,
    predicted_output_tokens,
    tokens,
)
from backend.app.llm.registry import REGISTRY, spec_for  # noqa: E402
from backend.app.llm.router import route_llm_request  # noqa: E402
from backend.app.llm.service import LlmProviderService  # noqa: E402
from tests.doubles.mock_provider import ok, scripted_factory  # noqa: E402
from tests.doubles.mock_provider import truncated as truncated_response

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5435/autoapply")
PASSWORD = "Str0ng!password"
DEFAULT_CHAIN = ["gemini", "ollama", "groq", "openrouter"]
PROVIDER_URLS = {"gemini": "https://generativelanguage.googleapis.com", "ollama": "http://localhost:11434"}

# A JD whose responsibility + skill pool is large enough that the *calculation*
# (not the base) drives the rubric cap — the user-mandated responsibilities
# driver: echo_pool + scaffold + allowance > 6000.
_BIG_RESP_SENTENCE = (
    "Responsibility number {i}: own, design, ship, lead, mentor, review, and operate "
    "production backend services across multiple regions and uptime SLOs, drive the "
    "technical roadmap, set reliability and observability standards, run incident "
    "retrospectives, hire engineers, represent the team in architecture reviews, and "
    "collaborate with data, platform, and frontend guilds on quarterly planning and "
    "capacity forecasting for the entire service landscape."
)
_BIG_RESP = [_BIG_RESP_SENTENCE.format(i=i) for i in range(40)]

# Varied prose ("the" + enumerate) so tiktoken counts ~4 tokens per word: a
# ~3000-token input that, with the 6000 cap, clears groq's measured 8000 tpm.
_BIG_PROMPT = "\n".join(
    f"The candidate paragraph number {i} discusses distributed systems, "
    "reliability engineering, incident response, capacity planning, and the "
    "tradeoffs between latency, cost, and availability in multi-region deployments."
    for i in range(120)
)
_BIG_JD = {
    "title": "Staff Engineer",
    "company": "BigCo",
    "responsibilities": _BIG_RESP,
    "required_skills": ["Python", "PostgreSQL", "Docker", "Kubernetes", "Terraform"],
}


def _capture(cap: dict, *, status: int = 200, payload=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["body"] = request.read().decode()
        return httpx.Response(status, json=payload or {}, request=request)

    return httpx.MockTransport(handler)


# ============================================================ D2: formula pins
def test_cap_is_base_floored_and_never_below_6000() -> None:
    """cap = max(6000, calc): a small JD keeps the base, never dips below it."""
    small = {"responsibilities": ["Own the backend service"], "required_skills": ["Python"]}
    assert estimate_rubric_cap(small) == BASE_OUTPUT_TOKENS
    assert BASE_OUTPUT_TOKENS == 6000
    # Eval: scaffold + allowance already exceeds the base on its own.
    assert estimate_eval_cap() >= BASE_OUTPUT_TOKENS


def test_rubric_cap_rises_with_responsibilities() -> None:
    """Responsibilities drive the predictor: a bigger pool raises the cap."""
    pool = echo_pool_tokens(_BIG_JD)
    expected_calc = pool + SCAFFOLD_BOUND_RUBRIC + ALLOWANCE_RUBRIC
    cap = estimate_rubric_cap(_BIG_JD)
    assert cap == expected_calc
    assert cap > BASE_OUTPUT_TOKENS, "large responsibilities must raise the cap above the 6000 base"


def test_budget_expected_is_input_plus_predicted_output() -> None:
    """`budget_expected = input + predicted output` — the wire cap (6000) is NOT
    added to the input: the realistic output the step produces drives the gate."""
    assert budget_expected(2421, PREDICTED_OUTPUT_EVAL) == 2421 + PREDICTED_OUTPUT_EVAL
    assert budget_expected(2421, PREDICTED_OUTPUT_RUBRIC) == 2421 + PREDICTED_OUTPUT_RUBRIC
    assert count_prompt_tokens("hello world") == tokens("hello world")
    assert count_prompt_tokens("hi", "sys") == tokens("hi") + tokens("sys")


def test_env_override_only_raises() -> None:
    os.environ["LLM_MAX_OUTPUT_TOKENS_RUBRIC"] = "100"
    try:
        assert estimate_rubric_cap(_BIG_JD) >= BASE_OUTPUT_TOKENS
    finally:
        os.environ.pop("LLM_MAX_OUTPUT_TOKENS_RUBRIC", None)


# ============================================================ D1: adapter wire
def test_openai_compatible_sends_cap_and_detects_length() -> None:
    cap: dict = {}
    adapter = OpenAICompatibleAdapter(
        transport=_capture(
            cap,
            payload={
                "model": "groq-model",
                "choices": [{"message": {"content": "trunc"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 6000},
            },
        )
    )
    resp = adapter.chat(
        prompt="hi",
        system_message="sys",
        model="groq-model",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
        max_output_tokens=6000,
    )
    body = json.loads(cap["body"])
    assert body["max_tokens"] == 6000, "cap must reach the wire"
    assert resp.truncated is True, "finish_reason=length must flag truncation"


def test_openai_compatible_usage_arithmetic_fallback() -> None:
    cap: dict = {}
    adapter = OpenAICompatibleAdapter(
        transport=_capture(
            cap,
            payload={
                "model": "groq-model",
                "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 6000},
            },
        )
    )
    resp = adapter.chat(
        prompt="hi",
        model="groq-model",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
        max_output_tokens=6000,
    )
    assert resp.truncated is True, "completion >= cap flags truncation even on finish_reason=stop"


def test_openai_compatible_omits_max_tokens_when_unset() -> None:
    cap: dict = {}
    adapter = OpenAICompatibleAdapter(transport=_capture(cap, payload={"choices": [{"message": {"content": "ok"}}]}))
    adapter.chat(prompt="hi", model="m", base_url="https://api.groq.com/openai/v1", api_key="k")
    body = json.loads(cap["body"])
    assert "max_tokens" not in body, "no cap -> provider default (never a hardcoded 16384)"


def test_gemini_sends_cap_and_detects_max_tokens() -> None:
    cap: dict = {}
    adapter = GeminiAdapter(
        transport=_capture(
            cap,
            payload={
                "candidates": [{"content": {"parts": [{"text": "t"}]}, "finishReason": "MAX_TOKENS"}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 6000},
            },
        )
    )
    resp = adapter.chat(
        prompt="hi",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com",
        api_key="k",
        max_output_tokens=6000,
    )
    body = json.loads(cap["body"])
    assert body["generationConfig"]["maxOutputTokens"] == 6000
    assert resp.truncated is True


def test_ollama_sends_cap_and_detects_done_reason_length() -> None:
    cap: dict = {}
    adapter = OllamaAdapter(
        transport=_capture(
            cap,
            payload={"message": {"content": "t"}, "done_reason": "length", "eval_count": 6000},
        )
    )
    resp = adapter.chat(
        prompt="hi",
        model="llama3",
        base_url="http://localhost:11434",
        max_output_tokens=6000,
    )
    body = json.loads(cap["body"])
    assert body["num_predict"] == 6000
    assert resp.truncated is True


# ======================================================== D1: router pass-through
async def test_router_forwards_cap_and_returns_truncated() -> None:
    conn, user = await _register()
    try:
        await _add_provider(conn, user.id, "gemini")
        factory, adapters, _log = scripted_factory({"gemini": [truncated_response(ct=6000)]})
        resp = await route_llm_request(
            conn,
            user_id=user.id,
            prompt="hello",
            system_message="sys",
            max_output_tokens=6000,
            adapter_factory=factory,
        )
        assert resp.truncated is True
        assert adapters["gemini"].calls[0]["max_output_tokens"] == 6000
    finally:
        await conn.close()


# ======================================================== D2c: budget gating
async def test_budget_skip_fits_capable_provider_still_called() -> None:
    """A provider whose tpm cannot fit `input + predicted output` is skipped,
    the fitting provider still answers. Predicted output raised via env to push
    groq's 8000 tpm over the line (~3000-token prompt + 1000 predicted)."""
    conn, user = await _register()
    try:
        os.environ["LLM_PREDICTED_OUTPUT_TOKENS_EVAL"] = "10000"
        try:
            # groq priority 0 (would be first), gemini priority 1.
            await _add_provider(conn, user.id, "groq", priority=0)
            await _add_provider(conn, user.id, "gemini", priority=1)
            factory, adapters, _log = scripted_factory({"gemini": [ok("from gemini")]})
            resp = await route_llm_request(
                conn,
                user_id=user.id,
                prompt=_BIG_PROMPT,
                max_output_tokens=6000,
                step="scoring",
                provider_chain=["groq", "gemini"],
                adapter_factory=factory,
            )
            assert resp.truncated is False
            assert "groq" not in adapters, "groq must never be called when budget_expected > tpm"
            assert "gemini" in adapters, "the fitting provider still answers"
        finally:
            os.environ.pop("LLM_PREDICTED_OUTPUT_TOKENS_EVAL", None)
    finally:
        await conn.close()


async def test_budget_skip_all_providers_under_cap_exhausts() -> None:
    """When every configured provider is too small, we fail soft (exhausted)."""
    conn, user = await _register()
    try:
        os.environ["LLM_PREDICTED_OUTPUT_TOKENS_EVAL"] = "10000"
        try:
            await _add_provider(conn, user.id, "groq")
            factory, adapters, _log = scripted_factory({})
            with pytest.raises(ProvidersExhaustedError) as excinfo:
                await route_llm_request(
                    conn,
                    user_id=user.id,
                    prompt=_BIG_PROMPT,
                    max_output_tokens=6000,
                    step="scoring",
                    provider_chain=["groq"],
                    adapter_factory=factory,
                )
            attempts = excinfo.value.details.get("attempts") or []
            assert attempts and attempts[0].get("error_type") == "budget_skip"
            assert "groq" not in adapters, "budget-skip must not place a call"
        finally:
            os.environ.pop("LLM_PREDICTED_OUTPUT_TOKENS_EVAL", None)
    finally:
        await conn.close()


def test_predicted_output_is_per_step_realistic_not_the_cap() -> None:
    """The budget predictor uses realistic completion sizes per step (< cap),
    so a provider that can genuinely serve the call is not excluded."""
    assert BASE_OUTPUT_TOKENS == 6000
    assert predicted_output_tokens("rubric_generation") == PREDICTED_OUTPUT_RUBRIC
    assert predicted_output_tokens("scoring") == PREDICTED_OUTPUT_EVAL
    assert predicted_output_tokens("unknown_step") == PREDICTED_OUTPUT_DEFAULT
    for step in ("rubric_generation", "scoring"):
        assert predicted_output_tokens(step) < BASE_OUTPUT_TOKENS, "predictions must stay under the safety cap"


def test_groq_spec_declares_measured_tpm() -> None:
    assert REGISTRY["groq"].tpm == 8000
    assert spec_for("groq").tpm == 8000
    assert spec_for("gemini").tpm is None, "unmetered providers are not budget-gated"


# ======================================================== D4: consumer honesty
async def test_rubric_generation_flags_truncation_and_never_repairs() -> None:
    conn, user = await _register()
    try:
        await _add_provider(conn, user.id, "gemini")
        jd = _jd_payload()
        factory, _adapters, _log = scripted_factory(
            {"gemini": [truncated_response(content='{"position_title": "Tru', ct=6000)]}
        )
        with pytest.raises(RubricGenerationFailedError) as excinfo:
            await asyncio.wait_for(
                _generate_rubric(conn, user, jd, factory),
                timeout=20,
            )
        details = excinfo.value.details
        assert details.get("error_type") == "output_truncated"
        assert details.get("can_continue") is True
        assert details.get("max_output_tokens", 0) >= BASE_OUTPUT_TOKENS
        assert details.get("content_prefix"), "partial content must be preserved for park-and-ask"
    finally:
        await conn.close()


async def test_evaluation_flags_truncation() -> None:
    from backend.app.core_engine.scoring.evaluator import ResumeEvaluator  # noqa: E401
    from backend.app.core_engine.scoring.scoring_models import build_evaluation_model  # noqa: E401
    from tests.integration.test_scoring import RUBRIC, _resume_payload, _role_from  # noqa: F401

    conn, user = await _register()
    try:
        await _add_provider(conn, user.id, "gemini")

        from backend.app.core_engine.resume_models import JSONResume
        from backend.app.core_engine.scoring.resume_text import convert_json_resume_to_text

        role = _role_from(RUBRIC)
        factory, _adapters, _log = scripted_factory({"gemini": [truncated_response(ct=6000)]})
        evaluator = ResumeEvaluator(role, build_evaluation_model(role))
        resume_text = convert_json_resume_to_text(JSONResume.model_validate(_resume_payload()))
        job_id, _snapshot_id = await _seed_job(conn, user)
        with pytest.raises(ScoringFailedError) as excinfo:
            await evaluator.evaluate_resume(
                conn=conn,
                user_id=user.id,
                job_id=job_id,
                resume_text=resume_text,
                adapter_factory=factory,
            )
        assert excinfo.value.details.get("cause") == "output_truncated"
    finally:
        await conn.close()


# ------------------------------------------------------------- local helpers
async def _register() -> tuple[psycopg.AsyncConnection, AuthResult]:
    conn = await psycopg.AsyncConnection.connect(APP_URL)
    try:
        result = await AuthService(conn).register(
            email=f"{uuid.uuid4().hex[:10]}@example.com",
            password=PASSWORD,
            name="Cap Tester",
        )
    except Exception:
        await conn.close()
        raise
    return conn, result


async def _add_provider(conn: psycopg.AsyncConnection, user_id: uuid.UUID, name: str, *, priority: int = 0) -> None:
    await LlmProviderService(conn).add_provider(
        user_id=user_id,
        name=name,
        base_url=PROVIDER_URLS.get(name, f"http://{name}.example.com/v1"),
        model=f"{name}-model",
        api_key="k" * 10,
        priority=priority,
    )


def _jd_payload() -> dict:
    import json as _json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    return _json.loads((root / "tests" / "fixtures" / "scoring" / "jd_payload.json").read_text(encoding="utf-8"))


async def _seed_job(conn, user) -> tuple[uuid.UUID, uuid.UUID]:
    """Job + bound snapshot rows so the router's provider_usage FK inserts hold."""
    from psycopg.types.json import Jsonb

    jd = _jd_payload()
    async with DbContext(conn, user.id).transaction() as db:
        job_row = await (
            await db.execute(
                """INSERT INTO jobs (user_id, title, company, url, platform, source, status)
                   VALUES (%s, %s, %s, %s, 'greenhouse', 'manual', 'discovered') RETURNING id""",
                (
                    str(user.id),
                    jd["title"],
                    jd.get("company", "Acme"),
                    f"https://boards.greenhouse.io/cap/{uuid.uuid4().hex}",
                ),
            )
        ).fetchone()
        job_id = job_row[0]
        snap_row = await (
            await db.execute(
                "INSERT INTO job_snapshots (content_hash, payload, raw_text) VALUES (%s, %s, %s) RETURNING id",
                (uuid.uuid4().hex, Jsonb(jd), "cap fixture snapshot"),
            )
        ).fetchone()
        snapshot_id = snap_row[0]
        await db.execute("UPDATE jobs SET current_snapshot_id = %s WHERE id = %s", (str(snapshot_id), str(job_id)))
    return job_id, snapshot_id


async def _generate_rubric(conn, user, jd, factory):
    from backend.app.core_engine.scoring.rubric_generator import generate_rubric

    job_id, snapshot_id = await _seed_job(conn, user)
    return await generate_rubric(
        conn,
        user_id=user.id,
        job_id=job_id,
        snapshot_id=snapshot_id,
        jd_payload=jd,
        adapter_factory=factory,
    )
