"""T5 — core-engine extraction + profiles service (S5), §8 Profile Endpoints.

Drives ``extract_profile`` / ``ProfilesService`` over a live connection with
the deterministic mock sequencer (D26, S4 ``mock_provider`` via
``adapter_factory``). Proves:
- happy-path PDF → JSONResume with required sections non-empty (1)
- 6 routed calls via adapter_factory + exhaustion path (1b)
- identical bytes → same profile row, zero extra LLM calls (2)
- vendor tree byte-unmodified via sha256 manifest (3)
- §8 CRUD exact shapes + RLS cross-user isolation + audit (3b)
- validation rejects non-PDF / oversized / unknown ID (3c)
- extraction failure rolls back rows + files (4)
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

from backend.app.auth.service import AuthService
from backend.app.core_engine.errors import ExtractionFailedError, ProfileNotFoundError, ValidationError
from backend.app.core_engine.extraction import sha256_hex
from backend.app.core_engine.profiles import ProfilesService
from backend.app.db.context import DbContext
from backend.app.llm.service import LlmProviderService
from tests.doubles.mock_provider import http, ok, scripted_factory

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5432/autoapply")
PASSWORD = "Str0ng!password"
ROOT = Path(__file__).resolve().parents[2]
VENDOR_PDF = ROOT / "vendor" / "hiring_agent" / "resume" / "sample.pdf"
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "vendor_manifest.json"

SAMPLE_PDF_BYTES = VENDOR_PDF.read_bytes()
SAMPLE_SHA256 = sha256_hex(SAMPLE_PDF_BYTES)

SECTION_ORDER = ["basics", "work", "education", "skills", "projects", "awards"]


def _json_wrap(section_key: str, content: object) -> str:
    return json.dumps({section_key: content})


MOCK_CONTENT = {
    "basics": _json_wrap("basics", {"name": "Test User", "email": "test@example.com", "summary": "Summary"}),
    "work": _json_wrap(
        "work", [{"name": "Acme", "position": "Engineer", "startDate": "2023-01", "endDate": "2024-01"}]
    ),
    "education": _json_wrap("education", [{"institution": "MIT", "area": "CS", "studyType": "BSc"}]),
    "skills": _json_wrap("skills", ["Python", "SQL"]),
    "projects": _json_wrap("projects", [{"name": "ProjectX", "description": "A tool", "technologies": ["Python"]}]),
    "awards": _json_wrap("awards", [{"title": "Best", "awarder": "Org", "date": "2024-01"}]),
}

BAD_CONTENT = "this is not valid json at all"


def _ok_factory():
    # All 6 section calls route through the same provider ("gemini").
    responses = [ok(MOCK_CONTENT[name]) for name in SECTION_ORDER]
    return scripted_factory({"gemini": responses})


def _fail_factory():
    responses = [http(500)] * 6
    return scripted_factory({"gemini": responses})


def _bad_json_factory():
    responses = [ok(BAD_CONTENT)] * 6
    return scripted_factory({"gemini": responses})


async def _conn():
    return await psycopg.AsyncConnection.connect(APP_URL)


async def _register():
    conn = await _conn()
    try:
        result = await AuthService(conn).register(
            email=f"{uuid.uuid4().hex[:10]}@example.com",
            password=PASSWORD,
            name="Extraction Tester",
        )
    except Exception:
        await conn.close()
        raise
    return conn, result


async def _add_provider(conn, user_id):
    await LlmProviderService(conn).add_provider(
        user_id=user_id, name="gemini", base_url="https://test.example.com", model="gemini-model",
    )


async def _usage_rows(conn, user_id):
    async with DbContext(conn, user_id).transaction() as db:
        cur = await db.execute(
            "SELECT success, provider_id FROM provider_usage WHERE user_id = %s ORDER BY created_at",
            (str(user_id),),
        )
        return await cur.fetchall()


async def _audit_count(conn, user_id, action):
    async with DbContext(conn, user_id).transaction() as db:
        return await db.fetch_scalar(
            "SELECT count(*) FROM audit_logs WHERE user_id = %s AND action = %s", (str(user_id), action),
        )


async def _profile_count(conn, user_id):
    async with DbContext(conn, user_id).transaction() as db:
        return await db.fetch_scalar("SELECT count(*) FROM profiles WHERE user_id = %s", (str(user_id),))


# ================================================================== 1 — happy path
async def test_resume_pdf_to_jsonresume(tmp_path) -> None:
    conn, user = await _register()
    uid = user.id
    try:
        await _add_provider(conn, uid)
        factory, _adapters, _log = _ok_factory()
        os.environ["STORAGE_ROOT"] = str(tmp_path)
        svc = ProfilesService(conn)
        result = await svc.upload_profile(
            user_id=uid, pdf_path=str(VENDOR_PDF), sha256=SAMPLE_SHA256, filename="sample.pdf",
            adapter_factory=factory,
        )
        resume = result.json_resume
        assert resume["basics"], "basics missing"
        assert resume["basics"]["name"] == "Test User"
        assert resume["work"]
        assert resume["education"]
        assert resume["skills"]
        assert resume["projects"]
        assert resume["awards"]
        async with DbContext(conn, uid).transaction() as db:
            cur = await db.execute(
                "SELECT json_resume FROM profiles WHERE user_id = %s AND id = %s",
                (str(uid), str(result.id)),
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0]["basics"]["name"] == "Test User"
        usage = await _usage_rows(conn, uid)
        assert len(usage) == 6
        assert all(r[0] for r in usage)
    finally:
        os.environ.pop("STORAGE_ROOT", None)
        await conn.close()


# ============================================================ 1b — router wiring + exhaustion
async def test_extraction_routes_through_router(tmp_path) -> None:
    conn, user = await _register()
    uid = user.id
    try:
        await _add_provider(conn, uid)
        factory, _adapters, log = _fail_factory()
        os.environ["STORAGE_ROOT"] = str(tmp_path)
        with pytest.raises(ExtractionFailedError):
            await ProfilesService(conn).upload_profile(
                user_id=uid, pdf_path=str(VENDOR_PDF), sha256=SAMPLE_SHA256, filename="sample.pdf",
                adapter_factory=factory,
            )
        assert len(log) >= 1, "adapter_factory was never called"
        assert "gemini" in log
        usage = await _usage_rows(conn, uid)
        assert len(usage) >= 1
        assert not any(r[0] for r in usage)
        assert await _profile_count(conn, uid) == 0
    finally:
        os.environ.pop("STORAGE_ROOT", None)
        await conn.close()


# ================================================================== 2 — idempotent upload
async def test_extraction_idempotent(tmp_path) -> None:
    conn, user = await _register()
    uid = user.id
    try:
        await _add_provider(conn, uid)
        factory, _adapters, _log = _ok_factory()
        os.environ["STORAGE_ROOT"] = str(tmp_path)
        svc = ProfilesService(conn)
        first = await svc.upload_profile(
            user_id=uid, pdf_path=str(VENDOR_PDF), sha256=SAMPLE_SHA256, filename="sample.pdf",
            adapter_factory=factory,
        )
        usage_after_first = len(await _usage_rows(conn, uid))
        audits_after_first = await _audit_count(conn, uid, "profile_uploaded")
        second = await svc.upload_profile(
            user_id=uid, pdf_path=str(VENDOR_PDF), sha256=SAMPLE_SHA256, filename="sample.pdf",
            adapter_factory=factory,
        )
        assert second.id == first.id
        assert await _profile_count(conn, uid) == 1
        assert len(await _usage_rows(conn, uid)) == usage_after_first
        assert await _audit_count(conn, uid, "profile_uploaded") == audits_after_first
    finally:
        os.environ.pop("STORAGE_ROOT", None)
        await conn.close()


# ================================================================= 3 — vendor untouched
async def test_vendor_untouched() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    for rel_path, expected_hash in manifest.items():
        full = ROOT / "vendor" / "hiring_agent" / rel_path
        actual_hash = hashlib.sha256(full.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"vendor file {rel_path} modified: {actual_hash} != {expected_hash}"


# ======================================================== 3b — CRUD + RLS cross-user
async def test_profiles_crud_rls(tmp_path) -> None:
    conn_a, user_a = await _register()
    conn_b, user_b = await _register()
    uid_a, uid_b = user_a.id, user_b.id
    try:
        await _add_provider(conn_a, uid_a)
        os.environ["STORAGE_ROOT"] = str(tmp_path)
        factory_a, _, _ = _ok_factory()
        svc_a = ProfilesService(conn_a)
        profile_a = await svc_a.upload_profile(
            user_id=uid_a, pdf_path=str(VENDOR_PDF), sha256=SAMPLE_SHA256, filename="sample.pdf",
            adapter_factory=factory_a,
        )
        summaries = await svc_a.list_profiles(user_id=uid_a)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.id == profile_a.id
        assert s.original_pdf_url.startswith("/data/profiles/")
        current = await svc_a.get_current_profile(user_id=uid_a)
        assert current.id == profile_a.id
        assert current.json_resume["basics"]["name"] == "Test User"
        audits_before = await _audit_count(conn_a, uid_a, "profile_uploaded")
        updated = await svc_a.update_profile(
            user_id=uid_a, profile_id=profile_a.id, json_resume={"basics": {"name": "Updated"}},
        )
        assert updated.json_resume["basics"]["name"] == "Updated"
        assert await _audit_count(conn_a, uid_a, "profile_uploaded") == audits_before + 1
        svc_b = ProfilesService(conn_b)
        assert await svc_b.list_profiles(user_id=uid_b) == []
        with pytest.raises(ProfileNotFoundError):
            await svc_b.get_current_profile(user_id=uid_b)
        with pytest.raises(ProfileNotFoundError):
            await svc_b.update_profile(user_id=uid_b, profile_id=profile_a.id, json_resume={"basics": {"name": "X"}})
    finally:
        os.environ.pop("STORAGE_ROOT", None)
        await conn_a.close()
        await conn_b.close()


# ============================================================ 3c — validation
async def test_profiles_crud_validation(tmp_path) -> None:
    conn, user = await _register()
    uid = user.id
    try:
        os.environ["STORAGE_ROOT"] = str(tmp_path)
        svc = ProfilesService(conn)
        bad_ext = tmp_path / "bad.txt"
        bad_ext.write_bytes(b"not a pdf")
        with pytest.raises(ValidationError) as exc_info:
            await svc.upload_profile(user_id=uid, pdf_path=str(bad_ext), filename="bad.txt")
        assert ".pdf" in str(exc_info.value)
        bad_magic = tmp_path / "fake.pdf"
        bad_magic.write_bytes(b"NOTPDF-content")
        with pytest.raises(ValidationError) as exc_info:
            await svc.upload_profile(user_id=uid, pdf_path=str(bad_magic), filename="fake.pdf")
        assert "pdf" in str(exc_info.value).lower()
        big = tmp_path / "big.pdf"
        big.write_bytes(b"%PDF-" + b"\x00" * (10 * 1024 * 1024 + 1))
        with pytest.raises(ValidationError) as exc_info:
            await svc.upload_profile(user_id=uid, pdf_path=str(big), filename="big.pdf")
        assert "10MB" in str(exc_info.value) or "exceed" in str(exc_info.value).lower()
        with pytest.raises(ProfileNotFoundError):
            await svc.get_current_profile(user_id=uid)
    finally:
        os.environ.pop("STORAGE_ROOT", None)
        await conn.close()


# ======================================================== 4 — extraction failure rollback
async def test_extraction_failure_rolls_back(tmp_path) -> None:
    conn, user = await _register()
    uid = user.id
    try:
        await _add_provider(conn, uid)
        factory, _, _ = _bad_json_factory()
        os.environ["STORAGE_ROOT"] = str(tmp_path)
        with pytest.raises(ExtractionFailedError):
            await ProfilesService(conn).upload_profile(
                user_id=uid, pdf_path=str(VENDOR_PDF), sha256=SAMPLE_SHA256, filename="sample.pdf",
                adapter_factory=factory,
            )
        assert await _profile_count(conn, uid) == 0
        profiles_dir = Path(tmp_path) / "profiles" / str(uid)
        assert not profiles_dir.exists()
    finally:
        os.environ.pop("STORAGE_ROOT", None)
        await conn.close()