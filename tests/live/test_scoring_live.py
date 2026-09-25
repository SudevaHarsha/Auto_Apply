"""Live scoring tests — opt-in, end-to-end over the real wire (S7, D48-D58).

A genuinely fresh rubric + evaluation through the *real* cascade with real
providers (keys from ``.env.live``) and NO mocks:

  real provider router (failover/breaker/usage) → rubric generation call
  (json_mode + role.json-shaped schema) → evaluation call → normalize → one
  transaction: ``jobs.score`` + ``rubric_cache`` row + three-or-more
  ``rubric_evidence`` rows + ``job_scored`` audit, then a second score that must
  be served from the cache with a single call.

Enabled ONLY by ``-Target test-integration-live`` (sets ``RUN_LIVE_LLM=1``) with
real keys in the gitignored ``.env.live``. A provider outage (429/quota/5xx) or a
model that refuses/mangles the strict JSON is treated as environmental (skip —
model output is not a pipeline bug); a missing migration, constraint, or DB
failure fails the suite. Cost per run: 4-7 LLM calls.

Seed data: real payloads captured from live S5/S6 runs in ``tests/live/chain/``
(gitignored) when present; otherwise the deterministic scoring fixtures
(``tests/fixtures/scoring/``). Exact-value asserts only apply to cached/fixture
data; chain-data asserts use ranges because real model output drifts.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg.types.json import Jsonb

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

from backend.app.auth.service import AuthService  # noqa: E402
from backend.app.core_engine.errors import ScoringFailedError  # noqa: E402
from backend.app.core_engine.scoring.scorer import ScoreResult, score_job, score_profile  # noqa: E402
from backend.app.db.context import DbContext  # noqa: E402
from backend.app.llm.errors import ProvidersExhaustedError  # noqa: E402
from backend.app.llm.service import LlmProviderService  # noqa: E402

pytestmark = pytest.mark.live

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5435/autoapply")
PASSWORD = "Str0ng!password"
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "scoring"
CHAIN = ROOT / "tests" / "live" / "chain"
# Real evaluation output drifts run-to-run (same cached rubric + same resume);
# tolerate modest score movement but a big swing on an identical input is a bug.
APT_SCORE_DIFF = 10

CLOUD_PROVIDERS = ("groq", "gemini", "openrouter", "nara", "cloudflare-ai")
KEY_ENV = {
    "gemini": "LIVE_GEMINI_API_KEY",
    "groq": "LIVE_GROQ_API_KEY",
    "openrouter": "LIVE_OPENROUTER_API_KEY",
    "nara": "LIVE_NARA_API_KEY",
    "cloudflare-ai": "LIVE_CLOUDFLARE_AI_API_KEY",
}
BASE_URL_ENV = {
    "ollama": "LIVE_OLLAMA_URL",
    "cloudflare-ai": "LIVE_CLOUDFLARE_AI_BASE_URL",
}


def _key(name: str) -> str | None:
    raw = os.environ.get(KEY_ENV[name], "")
    stripped = raw.strip()
    if not stripped or stripped.upper().startswith("PASTE_"):
        return None
    return stripped


def _base_url(name: str) -> str | None:
    env = BASE_URL_ENV.get(name, "")
    raw = os.environ.get(env, "").strip() if env else ""
    if not raw or raw.upper().startswith("PASTE_"):
        return None
    return raw


def _configured() -> list[tuple[str, str | None]]:
    return [(name, _key(name)) for name in CLOUD_PROVIDERS if _key(name)]


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


def _mail(tag: str = "live-scoring") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _register() -> tuple[psycopg.AsyncConnection, object]:
    conn = await _conn()
    try:
        result = await AuthService(conn).register(email=_mail(), password=PASSWORD, name="Live Scoring Tester")
    except Exception:
        await conn.close()
        raise
    return conn, result


async def _seed(conn: psycopg.AsyncConnection, user_id: uuid.UUID, jd_index: int = 1) -> dict[str, Any]:
    """Job + snapshot (bound) + current profile — the only DB fixture, no LLM.

    Seed data source (fallback chain, S7):
      1. ``tests/live/chain/`` — real payloads captured from live S5/S6 runs
         (``profile.json`` + ``jd_<n>.json``, gitignored). The exact-value asserts
         are relaxed to ranges on chain data because real model output drifts.
      2. Otherwise the deterministic ``tests/fixtures/scoring/`` pair.
    """
    profile_chain = CHAIN / "profile.json"
    jd_chain = CHAIN / f"jd_{jd_index}.json"
    using_chain = profile_chain.exists() and jd_chain.exists()
    if using_chain:
        payload = json.loads(jd_chain.read_text(encoding="utf-8"))
        resume = json.loads(profile_chain.read_text(encoding="utf-8"))
    else:
        payload = json.loads((FIXTURES / "jd_payload.json").read_text(encoding="utf-8"))
        resume = json.loads((FIXTURES / "resume.json").read_text(encoding="utf-8"))
    async with DbContext(conn, user_id).transaction() as db:
        job_row = await (
            await db.execute(
                """INSERT INTO jobs (user_id, title, company, url, platform, source, status)
                   VALUES (%s, %s, %s, %s, 'greenhouse', 'manual', 'discovered') RETURNING id""",
                (
                    str(user_id),
                    payload["title"],
                    payload["company"],
                    f"https://boards.greenhouse.io/scoring/{uuid.uuid4().hex}",
                ),
            )
        ).fetchone()
        job_id = job_row[0]
        snap_row = await (
            await db.execute(
                "INSERT INTO job_snapshots (content_hash, payload, raw_text) VALUES (%s, %s, %s) RETURNING id",
                (uuid.uuid4().hex, Jsonb(payload), "live scoring snapshot"),
            )
        ).fetchone()
        snapshot_id = snap_row[0]
        await db.execute("UPDATE jobs SET current_snapshot_id = %s WHERE id = %s", (str(snapshot_id), str(job_id)))
        prof_row = await (
            await db.execute(
                "INSERT INTO profiles (user_id, original_pdf_url, json_resume) VALUES (%s, %s, %s) RETURNING id",
                (str(user_id), f"https://example.test/live/{uuid.uuid4().hex}.pdf", Jsonb(resume)),
            )
        ).fetchone()
    return {
        "job_id": job_id,
        "snapshot_id": snapshot_id,
        "profile_id": prof_row[0],
        "source": "chain" if using_chain else "fixture",
    }


async def _job_row(conn: psycopg.AsyncConnection, user_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    async with DbContext(conn, user_id).transaction() as db:
        cur = await db.execute(
            "SELECT score, status FROM jobs WHERE user_id = %s AND id = %s", (str(user_id), str(job_id))
        )
        row = await cur.fetchone()
    return {"score": row[0], "status": row[1]}


async def _count(conn: psycopg.AsyncConnection, user_id: uuid.UUID, query: str, *params: object) -> int:
    async with DbContext(conn, user_id).transaction() as db:
        n = await db.fetch_scalar(query, tuple(params))
    return int(n or 0)


async def _evidence_for(conn: psycopg.AsyncConnection, user_id: uuid.UUID) -> dict[str, int]:
    async with DbContext(conn, user_id).transaction() as db:
        cur = await db.execute("SELECT type, count(*) FROM evidence WHERE user_id = %s GROUP BY type", (str(user_id),))
        return {r[0]: int(r[1]) for r in await cur.fetchall()}


async def _audits(conn: psycopg.AsyncConnection, user_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
    async with DbContext(conn, user_id).transaction() as db:
        cur = await db.execute(
            "SELECT action, resource_type, resource_id, details FROM audit_logs"
            " WHERE user_id = %s AND action = %s ORDER BY created_at",
            (str(user_id), action),
        )
        return [{"resource_type": r[1], "resource_id": r[2], "details": dict(r[3] or {})} for r in await cur.fetchall()]


async def _add_providers(conn: psycopg.AsyncConnection, user_id: uuid.UUID) -> None:
    for index, (name, key) in enumerate(_configured()):
        await LlmProviderService(conn).add_provider(
            user_id=user_id, name=name, base_url=_base_url(name), api_key=key, priority=index
        )


@pytest_asyncio.fixture(scope="module")
async def live_ctx() -> dict:
    if os.environ.get("RUN_LIVE_LLM") != "1":
        pytest.skip("live scoring tests disabled; run .\\tasks.ps1 -Target test-integration-live")
    if not _configured():
        pytest.fail("RUN_LIVE_LLM=1 but no LIVE_*_API_KEY configured - paste real keys into .env.live")
    conn, user_id = await _register_with_providers()
    yield {"conn": conn, "user_id": user_id}
    await conn.close()


async def _register_with_providers() -> tuple[psycopg.AsyncConnection, uuid.UUID]:
    """Fresh registered user wired to the real providers — per-test isolation."""
    conn, result = await _register()
    user_id = result.id
    try:
        await _add_providers(conn, user_id)
    except Exception:
        await conn.close()
        raise
    return conn, user_id


async def _score_one(conn: psycopg.AsyncConnection, user_id: uuid.UUID, job_id: uuid.UUID) -> ScoreResult:
    """Score through the real cascade; environmental provider/model failures skip."""
    try:
        return await score_job(conn, user_id=user_id, job_id=job_id, adapter_factory=None)
    except ProvidersExhaustedError as exc:
        pytest.skip(f"real provider outage/quota during live scoring: {exc}")
    except ScoringFailedError as exc:
        pytest.skip(f"real model refused/mangled strict JSON during live scoring: {exc}")


async def test_live_fresh_score_real_generation_and_evaluation(live_ctx: dict) -> None:
    """One fresh score → 2-3 routed calls (incl. one possible gate repair), rubric persisted, evidence + audit."""
    conn, user_id = live_ctx["conn"], live_ctx["user_id"]
    seed = await _seed(conn, user_id, jd_index=1)
    usage_before = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND job_id = %s AND success",
        str(user_id),
        str(seed["job_id"]),
    )
    result = await _score_one(conn, user_id, seed["job_id"])

    assert 0 <= result.normalized <= 100
    job = await _job_row(conn, user_id, seed["job_id"])
    assert job["status"] == "scored"
    assert job["score"] == result.normalized
    assert result.per_facet, "live rubric produced no categories"

    rows = await _evidence_for(conn, user_id)
    assert rows.get("rubric_evidence", 0) == len(result.per_facet), "one rubric_evidence row per facet expected (D52)"

    cache_rows = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM rubric_cache WHERE job_id = %s",
        str(seed["job_id"]),
    )
    assert cache_rows == 1, "exactly one rubric_cache row after a fresh score (D58)"

    audits = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM audit_logs WHERE user_id = %s AND action = 'job_scored'",
        str(user_id),
    )
    assert audits == 1, "job_scored audit expected (D53)"

    usage_after = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND job_id = %s AND success",
        str(user_id),
        str(seed["job_id"]),
    )
    assert usage_after - usage_before in (2, 3), "fresh score = rubric (≤2 incl. gate repair) + 1 eval (D71)"


async def test_live_second_score_hits_rubric_cache(live_ctx: dict) -> None:
    """A re-score of the same snapshot is served from cache with a single call (D58)."""
    conn, user_id = live_ctx["conn"], live_ctx["user_id"]
    seed = await _seed(conn, user_id, jd_index=2)
    first = await _score_one(conn, user_id, seed["job_id"])

    usage_before = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND job_id = %s AND success",
        str(user_id),
        str(seed["job_id"]),
    )
    second = await _score_one(conn, user_id, seed["job_id"])

    assert second.rubric_sha256 == first.rubric_sha256, "cache hit reused the same rubric"
    if seed["source"] == "chain":
        assert 0 <= second.normalized <= 100, "chain re-score drifted out of the 0-100 band"
        assert abs(second.normalized - first.normalized) <= APT_SCORE_DIFF, (
            "same cached rubric vs same resume: re-score drift within tolerance"
        )
    else:
        assert second.normalized == first.normalized, "fixture pair must re-score deterministically"
    usage_after = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND job_id = %s AND success",
        str(user_id),
        str(seed["job_id"]),
    )
    assert usage_after - usage_before == 1, "cache-hit score = exactly 1 routed call (D58)"

    cache_rows = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM rubric_cache WHERE job_id = %s",
        str(seed["job_id"]),
    )
    assert cache_rows == 1, "re-score must not add a second rubric_cache row"


async def test_live_profile_score_audits_profile_scored(live_ctx: dict) -> None:
    """score_profile (profile-scored path, D53/I-c) → profile_scored audit, job scored."""
    conn, user_id = await _register_with_providers()
    try:
        seed = await _seed(conn, user_id, jd_index=2)
        try:
            result = await score_profile(
                conn,
                user_id=user_id,
                profile_id=seed["profile_id"],
                job_id=seed["job_id"],
                adapter_factory=None,
            )
        except ProvidersExhaustedError as exc:
            pytest.skip(f"real provider outage/quota during live profile score: {exc}")
        except ScoringFailedError as exc:
            pytest.skip(f"real model refused/mangled strict JSON during live profile score: {exc}")

        assert 0 <= result.normalized <= 100
        audits = await _audits(conn, user_id, "profile_scored")
        assert len(audits) == 1, "profile_scored audit expected exactly once (D53)"
        assert audits[0]["resource_type"] == "profile"
        assert audits[0]["resource_id"] == seed["profile_id"]
        assert int(audits[0]["details"].get("score", 0)) == result.normalized

        job = await _job_row(conn, user_id, seed["job_id"])
        assert job["status"] == "scored"
        assert job["score"] == result.normalized

        job_scored = await _audits(conn, user_id, "job_scored")
        assert job_scored == [], "profile-scored op must never audit job_scored (I-c)"
    finally:
        await conn.close()
