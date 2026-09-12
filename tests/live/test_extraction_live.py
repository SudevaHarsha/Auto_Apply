"""Live PDF extraction tests — opt-in, end-to-end with real LLM calls (S5, T5.5).

The full production flow over the real wire: real resume PDFs from
``tests/live/pdf/`` → ``ProfilesService.upload_profile`` with NO mock
(``adapter_factory=None`` → the default adapter factory) → 6 real section
calls → JSONResume persisted in ``profiles`` with ``pdf_sha256``.

Enabled ONLY by ``-Target test-integration-live`` (sets ``RUN_LIVE_LLM=1``) with
real keys in the gitignored ``.env.live``. Drop real resume PDFs into
``tests/live/pdf/`` (gitignored). A provider that replies 429/quota at runtime is
treated as environmental (skip); anything else fails the suite. Cost per run:
6 LLM calls per PDF.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

from backend.app.auth.service import AuthService
from backend.app.core_engine.profiles import ProfilesService
from backend.app.db.context import DbContext
from backend.app.llm.service import LlmProviderService

pytestmark = pytest.mark.live

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5432/autoapply")
PASSWORD = "Str0ng!password"
ROOT = Path(__file__).resolve().parents[2]
LIVE_PDF_DIR = Path(os.getenv("LIVE_EXTRACTION_PDF_DIR", str(ROOT / "tests" / "live" / "pdf")))

CLOUD_PROVIDERS = ("gemini", "groq", "openrouter")
KEY_ENV = {
    "gemini": "LIVE_GEMINI_API_KEY",
    "groq": "LIVE_GROQ_API_KEY",
    "openrouter": "LIVE_OPENROUTER_API_KEY",
}


def _key(name: str) -> str | None:
    raw = os.environ.get(KEY_ENV[name], "")
    stripped = raw.strip()
    if not stripped or stripped.upper().startswith("PASTE_"):
        return None
    return stripped


def _configured() -> list[tuple[str, str | None]]:
    return [(name, _key(name)) for name in CLOUD_PROVIDERS if _key(name)]


def _live_pdfs() -> list[Path]:
    return sorted(LIVE_PDF_DIR.glob("*.pdf"))


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


def _mail(tag: str = "live-extract") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _register() -> tuple[psycopg.AsyncConnection, object]:
    conn = await _conn()
    try:
        result = await AuthService(conn).register(email=_mail(), password=PASSWORD, name="Live Extraction Tester")
    except Exception:
        await conn.close()
        raise
    return conn, result


@pytest_asyncio.fixture(scope="module")
async def live_ctx() -> dict:
    if os.environ.get("RUN_LIVE_LLM") != "1":
        pytest.skip("live extraction tests disabled; run .\\tasks.ps1 -Target test-integration-live")
    if not _configured():
        pytest.fail("RUN_LIVE_LLM=1 but no LIVE_*_API_KEY configured - paste real keys into .env.live")
    pdfs = _live_pdfs()
    if not pdfs:
        raise RuntimeError(
            f"no live resume PDFs found in {LIVE_PDF_DIR} - drop your resumes there (e.g. resume.pdf, resume2.pdf)"
        )
    conn, result = await _register()
    user_id = result.id
    try:
        for index, (name, key) in enumerate(_configured()):
            await LlmProviderService(conn).add_provider(
                user_id=user_id, name=name, base_url=None, api_key=key, priority=index
            )
    except Exception:
        await conn.close()
        raise
    yield {"conn": conn, "user_id": user_id, "pdfs": pdfs}
    await conn.close()


async def _count(conn: psycopg.AsyncConnection, user_id: uuid.UUID, query: str, *params: object) -> int:
    async with DbContext(conn, user_id).transaction() as db:
        n = await db.fetch_scalar(query, tuple(params))
    return int(n or 0)


async def _run_one(conn: psycopg.AsyncConnection, user_id: uuid.UUID, pdf: Path, filename: str) -> None:
    """Upload once + verify a typed, valid JSONResume for a single PDF.

    ``work``/``education``/etc. may legitimately be empty (``[]``) or absent
    (``null``) for fresher resumes — the assertion is on shape (a section is a
    ``list`` or ``null``, never a wrong type), not non-emptiness. ``basics.email``
    is intentionally NOT asserted: the vendored pymupdf converter (I9-frozen)
    drops email lines on Type3-font PDFs, so email presence is provider/PDF
    dependent, not a pipeline invariant.
    """
    before = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true",
        str(user_id),
    )
    try:
        profile = await ProfilesService(conn).upload_profile(
            user_id=user_id, pdf_path=str(pdf), filename=filename, sha256=None, adapter_factory=None
        )
    except Exception as exc:  # noqa: BLE001 - surface 429/quota distinctly below
        types = await _success_types(conn, user_id)
        if not types:
            pytest.skip(f"provider(s) replied 429/quota during live run ({sorted(types)}): {exc}")
        raise

    resume = profile.json_resume
    assert isinstance(resume, dict), f"{filename}: resume must be a dict, got {type(resume)}"
    assert resume.get("basics", {}).get("name"), f"{filename}: basics.name missing"
    for section in ("work", "education", "skills", "projects", "awards"):
        value = resume.get(section)
        assert value is None or isinstance(value, list), (
            f"{filename}: {section} must be a list or null, got {type(value).__name__}"
        )

    row_count = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM profiles WHERE user_id = %s AND id = %s",
        str(user_id),
        str(profile.id),
    )
    assert row_count == 1, f"{filename}: profile row missing in DB"

    after = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true",
        str(user_id),
    )
    new_calls = after - before
    # One call per section, plus at most one retry per section (engine retry-on-None, I9).
    assert 6 <= new_calls <= 12, (
        f"{filename}: expected 6-12 successful usage rows (sections + retries), got {new_calls}"
    )

    again = await ProfilesService(conn).upload_profile(
        user_id=user_id, pdf_path=str(pdf), filename=filename, sha256=None, adapter_factory=None
    )
    assert again.id == profile.id, f"{filename}: re-upload must return the same profile row"
    final = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true",
        str(user_id),
    )
    assert final == after, f"{filename}: idempotent re-upload must not trigger new LLM calls"


async def test_live_pdfs_extract_complete_resumes(live_ctx: dict) -> None:
    """Every resume PDF in tests/live/pdf/ → complete JSONResume via real LLM calls."""
    conn, user_id, pdfs = live_ctx["conn"], live_ctx["user_id"], live_ctx["pdfs"]
    for pdf in pdfs:
        await _run_one(conn, user_id, pdf, filename=pdf.name)


async def _success_types(conn: psycopg.AsyncConnection, user_id: uuid.UUID) -> set[str]:
    async with DbContext(conn, user_id).transaction() as db:
        rows = await (
            await db.execute(
                "SELECT DISTINCT error_type FROM provider_usage "
                "WHERE user_id = %s AND success = false AND error_type IS NOT NULL",
                (str(user_id),),
            )
        ).fetchall()
    return {row[0] for row in rows}
