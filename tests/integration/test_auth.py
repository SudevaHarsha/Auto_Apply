"""T3 — auth lifecycle through the service layer (S3), plus §17/§23 services.

S3 ships no HTTP routers (D7: API-key capability stays repo-level; route assembly is
the backend_api step). These tests therefore drive AuthService / SettingsService /
UserProfileService over a live connection, assert the canonical error envelopes, and
verify route integrity on the FastAPI app (no /api/auth, no /api/keys).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import jwt
import psycopg
import pytest

from backend.app.auth.errors import (
    InvalidCredentialsError,
    SettingsKeyInvalidError,
    SettingsValueInvalidError,
    TokenExpiredError,
    TokenInvalidError,
    UserExistsError,
    ValidationError,
    WeakPasswordError,
)
from backend.app.auth.security import (
    ACCESS_TTL,
    REFRESH_TTL,
    REFRESH_TYPE,
    jwt_secret,
    sha256_hex,
)
from backend.app.auth.service import AuthService
from backend.app.auth.settings_service import SettingsService
from backend.app.auth.user_profile_service import UserProfileService
from backend.app.db.context import DbContext
from backend.app.db.repositories.auth_repository import AuthRepository
from backend.app.main import app

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5432/autoapply")

PASSWORD = "Str0ng!password"
WEAK_PASSWORD = "short"

EXPECTED_DEFAULTS = {
    "chat_mode": "bot",
    "theme": "dark",
    "auto_approve_threshold": 80,
    "notifications_enabled": True,
    "llm_chain": ["gemini", "ollama", "groq", "openrouter"],
}


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


def _email(tag: str = "t") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _register(email: str | None = None) -> tuple[psycopg.AsyncConnection, dict]:
    """Register a fresh user; returns (open conn, {email, result: AuthResult})."""
    conn = await _conn()
    try:
        result = await AuthService(conn).register(email=email or _email(), password=PASSWORD, name="Auto Apply Tester")
    except Exception:
        await conn.close()
        raise
    return conn, {"email": (email or result.email).lower(), "result": result}


def _assert_envelope_shape(exc: Exception) -> None:
    env = exc.envelope()["error"]
    assert env["code"]
    assert env["timestamp"]
    assert env["request_id"]


def _jti_hash_of(token: str) -> str:
    payload = jwt.decode(token, jwt_secret(), algorithms=["HS256"])
    return sha256_hex(payload["jti"])


# ---------------------------------------------------------------- register
async def test_register_issues_token_pair_and_user_is_usable() -> None:
    conn = await _conn()
    try:
        svc = AuthService(conn)
        email = _email()
        result = await svc.register(email=email, password=PASSWORD, name="Tester")
        assert result.email == email.lower()
        assert result.name == "Tester"
        assert result.expires_in == int(ACCESS_TTL.total_seconds()) == 900
        assert result.access_token and result.refresh_token
        assert uuid.UUID(str(result.id)) is not None
        me = await svc.me(access_token=result.access_token)
        assert me.id == result.id and me.email == email.lower() and me.name == "Tester"
    finally:
        await conn.close()


async def test_register_seeds_exactly_two_settings_rows() -> None:
    # D11: register writes exactly chat_mode + theme; the rest merge at read time.
    conn, bag = await _register()
    try:
        async with DbContext(conn, bag["result"].id).transaction() as db:
            rows = await AuthRepository(db).get_settings(bag["result"].id)
        assert sorted(key for key, _, _ in rows) == ["chat_mode", "theme"]
    finally:
        await conn.close()


async def test_register_duplicate_email_is_409() -> None:
    conn, bag = await _register()
    try:
        with pytest.raises(UserExistsError) as exc:
            await AuthService(conn).register(email=bag["email"], password=PASSWORD, name="Second")
        assert exc.value.status == 409
        assert exc.value.code == "AUTH_USER_EXISTS"
        _assert_envelope_shape(exc.value)
    finally:
        await conn.close()


async def test_register_weak_password_is_400() -> None:
    conn = await _conn()
    try:
        with pytest.raises(WeakPasswordError) as exc:
            await AuthService(conn).register(email=_email(), password=WEAK_PASSWORD, name="Weak")
        assert exc.value.status == 400
        assert exc.value.code == "AUTH_WEAK_PASSWORD"
        _assert_envelope_shape(exc.value)
    finally:
        await conn.close()


# -------------------------------------------------------------------- login
async def test_login_success_and_audit_row() -> None:
    conn, bag = await _register()
    try:
        result = await AuthService(conn).login(email=bag["email"], password=PASSWORD)
        assert result.id == bag["result"].id
        assert result.access_token and result.refresh_token
        async with DbContext(conn, result.id).transaction() as db:
            n = await db.fetch_scalar("SELECT count(*) FROM audit_logs WHERE action = 'user_logged_in'")
        assert int(n or 0) == 1
    finally:
        await conn.close()


async def test_login_wrong_password_is_401_and_creates_no_session() -> None:
    conn, bag = await _register()
    try:
        with pytest.raises(InvalidCredentialsError) as exc:
            await AuthService(conn).login(email=bag["email"], password="Wrong!password1")
        assert exc.value.status == 401
        assert exc.value.code == "AUTH_INVALID_CREDENTIALS"
        async with DbContext(conn, bag["result"].id).transaction() as db:
            n = await AuthRepository(db).count_sessions(bag["result"].id)
        assert n == 1  # only the register-time session exists
    finally:
        await conn.close()


async def test_login_unknown_email_matches_wrong_password_error() -> None:
    # Anti-enumeration: identical code AND message regardless of email existence.
    async def wrong_password_msg() -> str:
        conn, bag = await _register()
        try:
            try:
                await AuthService(conn).login(email=bag["email"], password="Wrong!password1")
            except InvalidCredentialsError as exc:
                return exc.message
        finally:
            await conn.close()
        raise AssertionError("expected InvalidCredentialsError")

    conn = await _conn()
    try:
        with pytest.raises(InvalidCredentialsError) as exc:
            await AuthService(conn).login(email=_email("ghost"), password="Wrong!password1")
        assert exc.value.code == "AUTH_INVALID_CREDENTIALS"
        assert exc.value.message == await wrong_password_msg()
        _assert_envelope_shape(exc.value)
    finally:
        await conn.close()


# ------------------------------------------------------------------- refresh
async def test_refresh_rotation_issues_new_pair_and_rejects_old() -> None:
    conn, bag = await _register()
    try:
        svc = AuthService(conn)
        rotated = await svc.refresh(refresh_token=bag["result"].refresh_token)
        assert rotated.access_token and rotated.refresh_token
        assert rotated.refresh_token != bag["result"].refresh_token
        # The old token was revoked atomically -> immediate reuse is rejected.
        with pytest.raises(TokenInvalidError) as exc:
            await svc.refresh(refresh_token=bag["result"].refresh_token)
        assert exc.value.code == "AUTH_TOKEN_INVALID"
        # The new pair is a live session.
        me = await svc.me(access_token=rotated.access_token)
        assert me.id == bag["result"].id
    finally:
        await conn.close()


async def test_refresh_rejects_expired_token() -> None:
    conn, bag = await _register()
    try:
        now = datetime.now(UTC)
        expired_payload = {
            "sub": str(bag["result"].id),
            "jti": str(uuid.uuid4()),
            "typ": REFRESH_TYPE,
            "iat": now - REFRESH_TTL - ACCESS_TTL,
            "exp": now - ACCESS_TTL,
        }
        expired = jwt.encode(expired_payload, jwt_secret(), algorithm="HS256")
        with pytest.raises(TokenExpiredError) as exc:
            await AuthService(conn).refresh(refresh_token=expired)
        assert exc.value.code == "AUTH_TOKEN_EXPIRED"
        assert exc.value.status == 401
    finally:
        await conn.close()


async def test_refresh_rejects_access_token_type() -> None:
    conn, bag = await _register()
    try:
        with pytest.raises(TokenInvalidError) as exc:
            await AuthService(conn).refresh(refresh_token=bag["result"].access_token)
        assert exc.value.code == "AUTH_TOKEN_INVALID"
    finally:
        await conn.close()


# -------------------------------------------------------------------- logout
async def test_logout_revokes_session_server_side() -> None:
    conn, bag = await _register()
    try:
        svc = AuthService(conn)
        await svc.logout(refresh_token=bag["result"].refresh_token)
        with pytest.raises(TokenInvalidError):
            await svc.refresh(refresh_token=bag["result"].refresh_token)
        async with DbContext(conn, bag["result"].id).transaction() as db:
            n = await db.fetch_scalar(
                "SELECT count(*) FROM auth_sessions WHERE jti_hash = %s AND revoked_at IS NOT NULL",
                (_jti_hash_of(bag["result"].refresh_token),),
            )
        assert int(n or 0) == 1
    finally:
        await conn.close()


# ------------------------------------------------------------------------ me
async def test_me_rejects_garbage_and_refresh_tokens() -> None:
    conn, bag = await _register()
    try:
        svc = AuthService(conn)
        with pytest.raises(TokenInvalidError):
            await svc.me(access_token="not.a.token")
        with pytest.raises(TokenInvalidError):
            await svc.me(access_token=bag["result"].refresh_token)  # typ is refresh
    finally:
        await conn.close()


# ------------------------------------------------------- RLS cross-user deny
async def test_cross_user_settings_default_denied() -> None:
    """RLS default-deny at the data layer: an A-scoped context sees/writes no B rows."""
    conn_a, bag_a = await _register(_email("a"))
    try:
        conn_b, bag_b = await _register(_email("b"))
        try:
            async with DbContext(conn_b, bag_b["result"].id).transaction() as db:
                await AuthRepository(db).upsert_setting(bag_b["result"].id, "theme", "light")
            # A-scoped context queries B's settings -> 0 rows (no leak to anyone).
            async with DbContext(conn_a, bag_a["result"].id).transaction() as db:
                rows = await AuthRepository(db).get_settings(bag_b["result"].id)
            assert rows == []
            # A-scoped context attempts a settings row attributed to B -> WITH CHECK rejects.
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                async with DbContext(conn_a, bag_a["result"].id).transaction() as db:
                    await AuthRepository(db).upsert_setting(bag_b["result"].id, "notifications_enabled", True)
        finally:
            await conn_b.close()
    finally:
        await conn_a.close()


# ------------------------------------------------------------------- §17
async def test_settings_defaults_merge_and_update() -> None:
    conn, bag = await _register()
    try:
        svc = SettingsService(conn)
        user_id = bag["result"].id
        assert await svc.get(user_id=user_id) == EXPECTED_DEFAULTS
        merged = await svc.update(user_id=user_id, updates={"chat_mode": "agent", "auto_approve_threshold": 55})
        assert merged == {**EXPECTED_DEFAULTS, "chat_mode": "agent", "auto_approve_threshold": 55}
        async with DbContext(conn, user_id).transaction() as db:
            rows = await AuthRepository(db).get_settings(user_id)
            n_audit = await db.fetch_scalar("SELECT count(*) FROM audit_logs WHERE action = 'settings_updated'")
        assert len(rows) == 3  # chat_mode + theme seeds, auto_approve_threshold added
        assert int(n_audit or 0) == 1
    finally:
        await conn.close()


async def test_settings_validation_errors() -> None:
    conn, bag = await _register()
    try:
        svc = SettingsService(conn)
        with pytest.raises(SettingsKeyInvalidError) as exc:
            await svc.update(user_id=bag["result"].id, updates={"spam_key": 1})
        assert exc.value.status == 400
        assert exc.value.code == "SETTINGS_KEY_INVALID"
        for bad in (
            {"chat_mode": "turbo"},
            {"auto_approve_threshold": "high"},
            {"llm_chain": []},
        ):
            with pytest.raises(SettingsValueInvalidError) as exc:
                await svc.update(user_id=bag["result"].id, updates=bad)
            assert exc.value.status == 422
            assert exc.value.code == "SETTINGS_VALUE_INVALID"
            _assert_envelope_shape(exc.value)
    finally:
        await conn.close()


# ------------------------------------------------------------------- §23
async def test_user_profile_created_then_updated() -> None:
    conn, bag = await _register()
    try:
        svc = UserProfileService(conn)
        user_id = bag["result"].id
        assert await svc.get(user_id=user_id) is None
        created = await svc.update(
            user_id=user_id,
            fields={
                "phone": "+1 555 0100",
                "linkedin_url": "https://li/x",
                "github_url": "https://gh/x",
                "website_url": "https://x.dev",
                "address": "101 Main St",
                "city": "Austin",
                "state": "TX",
                "country": "US",
                "postal_code": "78701",
                "date_of_birth": date(1990, 5, 12),
                "gender": "female",
                "ethnicity": "prefer_not_to_say",
                "veteran_status": "no",
                "disability_status": "prefer_not_to_say",
                "work_authorization": "us_citizen",
                "custom_fields": {"referral": "linkedin", "years_experience": 7},
            },
        )
        assert created["phone"] == "+1 555 0100"
        assert created["city"] == "Austin"
        assert created["country"] == "US"
        assert created["date_of_birth"] == date(1990, 5, 12)
        assert created["custom_fields"] == {"referral": "linkedin", "years_experience": 7}
        created_at = created["created_at"]
        updated = await svc.update(
            user_id=user_id,
            fields={"phone": "+1 555 0199", "state": "CA", "github_url": None},
        )
        assert updated["phone"] == "+1 555 0199"  # changed in place
        assert updated["state"] == "CA"  # added on update
        assert updated["github_url"] is None  # cleared to NULL
        assert updated["city"] == "Austin"  # preserved across upsert
        assert updated["linkedin_url"] == "https://li/x"
        assert updated["custom_fields"] == {"referral": "linkedin", "years_experience": 7}
        assert updated["created_at"] == created_at  # same row, updated not re-inserted
        assert updated["updated_at"] >= created_at
        async with DbContext(conn, user_id).transaction() as db:
            cursor = await db.execute("SELECT action FROM audit_logs WHERE resource_type = 'user_profile'")
            actions = [row[0] for row in await cursor.fetchall()]
        assert sorted(actions) == ["user_profile_created", "user_profile_updated"]
    finally:
        await conn.close()


async def test_user_profile_rejects_unknown_field() -> None:
    conn, bag = await _register()
    try:
        with pytest.raises(ValidationError) as exc:
            await UserProfileService(conn).update(user_id=bag["result"].id, fields={"bogus_field": 1})
        assert exc.value.code == "VALIDATION_ERROR"
        assert exc.value.status == 422
    finally:
        await conn.close()


# ------------------------------------------------------------------ §5 D10 lookup carve-out
async def test_login_sec_def_lookup() -> None:
    """D10: auth_user_by_email is the narrow SECURITY DEFINER login lookup — single
    exact-email row, EXECUTE granted to app_user, while a plain RLS SELECT by email
    stays blocked from any tenant scope."""
    conn_a, bag_a = await _register()
    conn_b, bag_b = await _register()
    try:
        email_a = bag_a["email"]
        # (1) SECURITY DEFINER carve-out returns exactly the one matching row,
        #     regardless of the calling tenant scope (GUC is B here).
        async with DbContext(conn_b, bag_b["result"].id).transaction() as db:
            cur = await db.execute("SELECT * FROM auth_user_by_email(%s)", (email_a,))
            rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0][1] == email_a
        assert len(rows[0]) == 4  # id, email, password_hash, name

        # (2) unknown email -> empty result (no row, no error).
        async with DbContext(conn_b, bag_b["result"].id).transaction() as db:
            cur = await db.execute("SELECT * FROM auth_user_by_email(%s)", ("ghost@example.com",))
            assert await cur.fetchall() == []

        # (3) function is STABLE + SECURITY DEFINER and EXECUTE is granted to app_user.
        async with DbContext(conn_b, bag_b["result"].id).transaction() as db:
            proc = await (
                await db.execute("SELECT prosecdef, provolatile FROM pg_proc WHERE proname = 'auth_user_by_email'")
            ).fetchone()
            granted = await db.fetch_scalar(
                "SELECT has_function_privilege('app_user', 'auth_user_by_email(text)', 'EXECUTE')"
            )
        assert proc is not None
        assert proc[0] is True and proc[1] == "s"  # prosecdef + STABLE
        assert granted is True

        # (4) plain SELECT by email is still RLS-blocked from B's scope (0 rows).
        async with DbContext(conn_b, bag_b["result"].id).transaction() as db:
            cur = await db.execute("SELECT id, email FROM users WHERE email = %s", (email_a,))
            assert await cur.fetchall() == []
    finally:
        await conn_a.close()
        await conn_b.close()


# ------------------------------------------------------------------ §7 global audit shape (I5)
async def test_auth_audit_actions_exactly_canonical() -> None:
    """I5: one user's full flow writes exactly the canonical audit action set —
    nothing extra across register/login/settings/profile."""

    conn, bag = await _register()
    try:
        svc = AuthService(conn)
        user_id = bag["result"].id
        login = await svc.login(email=bag["email"], password=PASSWORD)
        assert login.id == user_id

        await SettingsService(conn).update(user_id=user_id, updates={"theme": "light"})

        profile = UserProfileService(conn)
        await profile.update(user_id=user_id, fields={"phone": "+1 555 0100", "city": "Austin"})
        await profile.update(user_id=user_id, fields={"linkedin_url": "https://li/x"})

        async with DbContext(conn, user_id).transaction() as db:
            cur = await db.execute(
                "SELECT action, count(*) FROM audit_logs WHERE user_id = %s GROUP BY action",
                (str(user_id),),
            )
            counters = {row[0]: row[1] for row in await cur.fetchall()}
        assert len(counters) == 5, counters
        assert counters == {
            "user_registered": 1,
            "user_logged_in": 1,
            "settings_updated": 1,
            "user_profile_created": 1,
            "user_profile_updated": 1,
        }
    finally:
        await conn.close()


# ------------------------------------------------------------------ §23/§7 api keys (D7/D12)
async def test_api_key_create_lookup_touch_revoke() -> None:
    """D7/D12 repo-level key registry: one-time secret, SHA-256 hash, prefix lookup."""
    conn, bag = await _register()
    try:
        user_id = bag["result"].id
        expires = datetime.now(UTC) + timedelta(days=30)
        async with DbContext(conn, user_id).transaction() as db:
            created = await AuthRepository(db).create_api_key(user_id=user_id, name="cli", expires_at=expires)
        assert created["prefix"].startswith("aa_")
        assert created["secret"].startswith(f"{user_id}:")
        assert created["key_hash"] == sha256_hex(created["secret"])
        assert created["expires_at"] == expires
        assert created["secret"] != created["key_hash"]  # plaintext never stored

        wrong_secret = "someone-else-secret"
        assert sha256_hex(wrong_secret) != created["key_hash"]  # non-matching secret fails

        async with DbContext(conn, user_id).transaction() as db:
            row = await AuthRepository(db).find_api_key_by_prefix(created["prefix"])
        assert row is not None
        assert row["user_id"] == user_id
        assert row["name"] == "cli"
        assert row["key_hash"] == created["key_hash"]
        assert row["last_used_at"] is None

        async with DbContext(conn, user_id).transaction() as db:
            await AuthRepository(db).touch_api_key(created["id"])
            row = await AuthRepository(db).find_api_key_by_prefix(created["prefix"])
        assert row is not None and row["last_used_at"] is not None

        async with DbContext(conn, user_id).transaction() as db:
            assert await AuthRepository(db).revoke_api_key(created["id"]) is True
            assert await AuthRepository(db).find_api_key_by_prefix(created["prefix"]) is None
    finally:
        await conn.close()


async def test_api_key_cross_user_scope_and_unknown_prefix() -> None:
    """RLS scopes api_keys to their owner; unknown prefix has no row (D7)."""
    conn_a, bag_a = await _register()
    conn_b, bag_b = await _register()
    try:
        async with DbContext(conn_a, bag_a["result"].id).transaction() as db:
            created = await AuthRepository(db).create_api_key(user_id=bag_a["result"].id, name="a")
        async with DbContext(conn_a, bag_a["result"].id).transaction() as db:
            assert await AuthRepository(db).find_api_key_by_prefix("aa_unknown") is None
        async with DbContext(conn_b, bag_b["result"].id).transaction() as db:
            assert await AuthRepository(db).find_api_key_by_prefix(created["prefix"]) is None
    finally:
        await conn_a.close()
        await conn_b.close()


# ------------------------------------------------------------------ D7 routes
def test_no_auth_or_keys_http_routes_registered() -> None:
    """D7: S3 adds no HTTP surface; API-key capability is repo/service-level only."""
    paths = [route.path for route in app.routes]
    assert not any(p.startswith(("/api/auth", "/api/keys")) for p in paths), paths
    assert "/health" in paths
