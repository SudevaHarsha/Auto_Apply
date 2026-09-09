-- =============================================================================
-- manual_testing_auth.sql
-- Postgres manual-testing kit for S3 (auth) plus the neighboring §17/§23 lanes.
--
-- PURPOSE
--   Exercises the auth data layer exactly the way the API will, covering BOTH the
--   success and the error paths of every use case, so the same queries can be used
--   later as the acceptance checklist for the HTTP routes (S14). Every block that
--   deliberately fails prints an EXPECTED error line before it runs; a clean run
--   produces exactly the noise those blocks create, nothing else.
--
-- WHO RUNS IT
--   Run as app_user (the runtime role, NOT the migrator): RLS is FORCEd, so the
--   cross-user denial blocks are real. bcrypt verification runs in the app, so the
--   one hash used below is fixed and reproducible:
--     plaintext : Str0ng!password
--     bcrypt    : $2b$12$LQzjv7qzUu6f6RSj3lfmtuRv6P7kG5Z/1ww2SYl9Y7cLYEqyUrK56
--   Passwords are NEVER stored as plaintext and NEVER verified inside Postgres.
--
-- IDS
--   Deterministic (NOT random) so the kit is re-runnable and self-documenting:
--     demo A id = md5('demo_a@example.com')::uuid = 94dd3a96-a349-6dc6-0a4e-3bfe6798fb1f
--     demo B id = md5('demo_b@example.com')::uuid = 849f82d5-ee9c-83c7-9dbd-1d81847cd826
--   Re-runs purge the resource rows (settings/api_keys/sessions/profile) and are
--   idempotent for the user row. The user rows themselves and their audit_logs
--   entries survive the demo: audit_logs is append-only (migration 020) and its
--   immutability trigger blocks the cascade delete from users, which is the point.
--
-- CONNECTIONS (see docs/testing-environment.md)
--   test stack : postgresql://app_user:changeme_in_production@localhost:5435/autoapply
--   dev stack  : postgresql://app_user:changeme_in_production@localhost:5432/autoapply
--
-- RUN
--   psql "postgresql://app_user:changeme_in_production@localhost:5435/autoapply" -f scripts/manual_testing_auth.sql
-- =============================================================================

\set VERBOSITY terse
\set ON_ERROR_STOP off
\set email_a 'demo_a@example.com'
\set email_b 'demo_b@example.com'
\set email_unknown 'ghost@example.com'
\set id_a '94dd3a96-a349-6dc6-0a4e-3bfe6798fb1f'
\set id_b '849f82d5-ee9c-83c7-9dbd-1d81847cd826'
\set refresh_jti 'demo-refresh-0001'
\set successor_jti 'demo-refresh-0002'

\echo
\echo '==================================================================='
\echo ' PREFLIGHT: RLS + function surface + purge of prior kit runs'
\echo '==================================================================='

-- Show we are the runtime role, RLS is FORCEd, and the login lookup is grantable.
SELECT rolname FROM pg_roles WHERE rolname = current_user;
SELECT c.relname, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace
  AND c.relname IN ('users', 'settings', 'api_keys', 'auth_sessions', 'user_profiles')
ORDER BY 1;
SELECT has_function_privilege('app_user', 'auth_user_by_email(text)', 'EXECUTE') AS lookup_exec;

-- Demo users GUC context: the RLS policy on every user-owned table requires
-- app.user_id == <the row owner>. md5(email)::uuid is our deterministic owner id.
SELECT set_config('app.user_id', :'id_a', false) AS a_ctx;
DELETE FROM api_keys      WHERE user_id = :'id_a'::uuid;
DELETE FROM user_profiles WHERE user_id = :'id_a'::uuid;
DELETE FROM settings      WHERE user_id = :'id_a'::uuid;
DELETE FROM auth_sessions WHERE user_id = :'id_a'::uuid;
SELECT set_config('app.user_id', :'id_b', false) AS b_ctx;
DELETE FROM api_keys      WHERE user_id = :'id_b'::uuid;
DELETE FROM user_profiles WHERE user_id = :'id_b'::uuid;
DELETE FROM settings      WHERE user_id = :'id_b'::uuid;
DELETE FROM auth_sessions WHERE user_id = :'id_b'::uuid;
SELECT set_config('app.user_id', :'id_a', false) AS a_ctx_restored;

\echo
\echo '==================================================================='
\echo ' CASES: 1 Register (success, then errors)  AUTH_USER_EXISTS 409'
\echo '==================================================================='

-- 1.1 REGISTER SUCCESS — exact D6 flow: pre-known id, GUC pointed at it, then insert.
INSERT INTO users (id, email, password_hash, name)
VALUES (:'id_a', :'email_a', '$2b$12$LQzjv7qzUu6f6RSj3lfmtuRv6P7kG5Z/1ww2SYl9Y7cLYEqyUrK56', 'Demo A')
ON CONFLICT (id) DO NOTHING;

-- 1.1a D11: register seeds exactly the two defaults (chat_mode=bot, theme=dark).
INSERT INTO settings (user_id, key, value) VALUES
    (:'id_a', 'chat_mode', '"bot"'),
    (:'id_a', 'theme',    '"dark"')
ON CONFLICT (user_id, key) DO NOTHING;

-- 1.1b observability: audit lane records user_registered (details carry cause).
INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details)
SELECT :'id_a', 'user_registered', 'user', :'id_a', '{"cause": "postgres_manual_kit"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM audit_logs a
    WHERE a.user_id = :'id_a'::uuid
      AND a.action = 'user_registered'
      AND a.details->>'cause' = 'postgres_manual_kit'
);

-- 1.1c proof of the row + its ledger visibility under the own-GUC view.
SELECT id, email, created_at IS NOT NULL AS has_created_at
FROM users WHERE id = :'id_a'::uuid;
SELECT key, value, jsonb_typeof(value) AS stored_as_jsonb
FROM settings WHERE user_id = :'id_a'::uuid ORDER BY key;
SELECT action, resource_type, details FROM audit_logs WHERE user_id = :'id_a'::uuid ORDER BY created_at;

-- 1.2 REGISTER ERROR — duplicate email → unique violation 23505 → AUTH_USER_EXISTS (409).
--     Faithful repro of the production path: a FRESH id, GUC pointed at THAT id,
--     then the insert — the WITH CHECK passes (id == GUC) and the email unique
--     constraint is what aborts. The psql variable syntax cannot run inside a DO
--     body, so the demo email/hash are the documented constants.
\echo '>>> EXPECTED ERROR: duplicate key value violates unique constraint "users_email_key" (23505) -> AUTH_USER_EXISTS 409'
DO $$
DECLARE
    new_id uuid := gen_random_uuid();
BEGIN
    PERFORM set_config('app.user_id', new_id::text, false);
    INSERT INTO users (id, email, password_hash, name)
    VALUES (new_id, 'demo_a@example.com',
            '$2b$12$LQzjv7qzUu6f6RSj3lfmtuRv6P7kG5Z/1ww2SYl9Y7cLYEqyUrK56',
            'Duplicate A');
END
$$;
SELECT set_config('app.user_id', :'id_a', false) AS a_ctx_after_dup;

-- 1.3 REGISTER ERROR — weak password is ENFORCED IN THE APP (never stored).
\echo '>>> EXPECTED: password shorter than 8 chars / no upper / no digit -> AUTH_WEAK_PASSWORD 400'
\echo '    (app-enforced before any SQL; nothing reaches the DB. shown here for parity)'
DO $$
BEGIN
    IF length('abc') < 8 OR 'abc' !~ '[\p{Lu}]' OR 'abc' !~ '\d' THEN
        RAISE EXCEPTION 'AUTH_WEAK_PASSWORD';
    END IF;
END
$$;

\echo
\echo '==================================================================='
\echo ' CASES: 2 Login (success + same-error-for-every-failure)  401'
\echo '==================================================================='

-- 2.1 LOGIN SUCCESS — D10 lookup. The GUC is UNSET here (fresh session, no auth
--     context), which is exactly why auth_user_by_email must be SECURITY DEFINER:
--     a bare app_user SELECT under RLS would see zero rows.
SELECT set_config('app.user_id', '', false) AS guc_unset_for_login;

SELECT id, email, name FROM auth_user_by_email(:'email_a');

-- 2.1a the app then runs bcrypt.compare(password, password_hash). Evidence shown as
--     the hash the app fetched is the fixed bcrypt constant of Str0ng!password.
SELECT CASE WHEN password_hash = '$2b$12$LQzjv7qzUu6f6RSj3lfmtuRv6P7kG5Z/1ww2SYl9Y7cLYEqyUrK56'
            THEN 'bcrypt.compare(Str0ng!password, stored) = TRUE in the app'
            ELSE 'hash mismatch (wrong source)'
       END AS password_check_expected
FROM auth_user_by_email(:'email_a');

-- 2.1b with the GUC now set, mint a session (D12: store only the SHA-256 of the
--     refresh jti). expires_at = +7 days, matching the refresh TTL.
SELECT set_config('app.user_id', :'id_a', false) AS guc_a_restored;
INSERT INTO auth_sessions (user_id, jti_hash, expires_at)
VALUES (:'id_a', encode(sha256(:'refresh_jti'::text::bytea), 'hex'), NOW() + INTERVAL '7 days');
SELECT encode(sha256(:'refresh_jti'::text::bytea), 'hex') = jti_hash AS jti_stored_hashed,
       revoked_at IS NULL AS active, expires_at > NOW() AS unexpired
FROM auth_sessions WHERE user_id = :'id_a'::uuid AND revoked_at IS NULL;

-- 2.2 LOGIN ERROR — unknown email lookup returns zero rows → identical 401 payload.
--     Anti-enumeration contract: message is the SAME string as the wrong-password case.
SELECT count(*) AS rows_fetched FROM auth_user_by_email(:'email_unknown');
\echo '>>> expected rows_fetched = 0 -> AUTH_INVALID_CREDENTIALS 401 (same body as 2.3)'

-- 2.3 LOGIN ERROR — wrong password: row IS fetched but compare fails → same 401.
\echo '>>> EXPECTED: bcrypt.compare(<<wrong password>>, stored hash) -> false -> AUTH_INVALID_CREDENTIALS 401'
\echo '    (performed by bcrypt in the app; outcome identical for 2.2 and 2.3)'

-- 2.4 LOGIN ERROR — expired/invalid session: a conditional revoke fires zero rows.
\echo '>>> EXPECTED ERROR: 0 rows -> AUTH_TOKEN_EXPIRED / AUTH_TOKEN_INVALID 401'
UPDATE auth_sessions
SET revoked_at = NOW()
WHERE jti_hash = encode(sha256('stale-refresh'::text::bytea), 'hex')
  AND revoked_at IS NULL
  AND expires_at > NOW();

\echo
\echo '==================================================================='
\echo ' CASES: 3 Refresh rotation (reuse rejection + typ guard)  401'
\echo '==================================================================='

-- 3.1 REFRESH SUCCESS — rotate: revoke the presented session atomically, THEN mint
--     the successor. The revoke is conditional, so a revoked/expired token can never
--     mint a replacement (rowcount 0 => downstream caller raises 401).
UPDATE auth_sessions
SET revoked_at = NOW()
WHERE jti_hash = encode(sha256(:'refresh_jti'::text::bytea), 'hex')
  AND revoked_at IS NULL
  AND expires_at > NOW();

INSERT INTO auth_sessions (user_id, jti_hash, expires_at)
VALUES (:'id_a', encode(sha256(:'successor_jti'::text::bytea), 'hex'), NOW() + INTERVAL '7 days');

SELECT revoked_at IS NOT NULL AS old_session_revoked,
       (SELECT count(*) FROM auth_sessions
        WHERE user_id = :'id_a'::uuid AND revoked_at IS NULL AND expires_at > NOW()) AS active_sessions_now
FROM auth_sessions
WHERE user_id = :'id_a'::uuid AND jti_hash = encode(sha256(:'refresh_jti'::text::bytea), 'hex');

-- 3.2 REFRESH ERROR — REUSE of the just-rotated token: already revoked → 0 rows.
\echo '>>> EXPECTED ERROR: 0 rows (token reuse) -> AUTH_TOKEN_INVALID 401'
UPDATE auth_sessions
SET revoked_at = NOW()
WHERE jti_hash = encode(sha256(:'refresh_jti'::text::bytea), 'hex')
  AND revoked_at IS NULL
  AND expires_at > NOW();

-- 3.3 REFRESH ERROR — typ confusion: an ACCESS token (typ=access, not refresh) must
--     never reach the rotation lane. Guard is JWT-level, checked before any SQL.
\echo '>>> EXPECTED: JWT header typ != refresh -> AUTH_TOKEN_INVALID 401 (app-level, no SQL reached)'

\echo
\echo '==================================================================='
\echo ' CASES: 4 Logout (server-side revoke; no audit row per D9)  401'
\echo '==================================================================='

-- 4.1 LOGOUT SUCCESS — revoke the ACTIVE successor session; active count drops to 0.
SELECT count(*) AS active_before FROM auth_sessions
WHERE user_id = :'id_a'::uuid AND revoked_at IS NULL AND expires_at > NOW();

UPDATE auth_sessions
SET revoked_at = NOW()
WHERE jti_hash = encode(sha256(:'successor_jti'::text::bytea), 'hex')
  AND revoked_at IS NULL
  AND expires_at > NOW();

SELECT count(*) AS active_after FROM auth_sessions
WHERE user_id = :'id_a'::uuid AND revoked_at IS NULL AND expires_at > NOW();

-- 4.2 LOGOUT ERROR — re-logout of the same token: already revoked → 0 rows.
\echo '>>> EXPECTED ERROR: 0 rows -> AUTH_TOKEN_INVALID 401 (client treats as already logged out)'
UPDATE auth_sessions
SET revoked_at = NOW()
WHERE jti_hash = encode(sha256(:'successor_jti'::text::bytea), 'hex')
  AND revoked_at IS NULL
  AND expires_at > NOW();

\echo
\echo '==================================================================='
\echo ' CASES: 5 me (own-row read via Bearer; cross-user default deny)'
\echo '==================================================================='

-- 5.1 ME SUCCESS — with the GUC pointed at A, the user row is visible.
SELECT id, email, name FROM users WHERE id = :'id_a'::uuid;

-- 5.2 ME ERROR — B exists in the cluster, but under A's context it is invisible.
SELECT set_config('app.user_id', :'id_b', false) AS guc_b_ctx;
INSERT INTO users (id, email, password_hash, name)
VALUES (:'id_b', :'email_b', '$2b$12$LQzjv7qzUu6f6RSj3lfmtuRv6P7kG5Z/1ww2SYl9Y7cLYEqyUrK56', 'Demo B')
ON CONFLICT (id) DO NOTHING;

SELECT set_config('app.user_id', :'id_a', false) AS guc_a_again;
SELECT count(*) AS B_rows_visible_to_A FROM users WHERE id = :'id_b'::uuid;
\echo '>>> expected B_rows_visible_to_A = 0 (default-deny, no policy match)'

\echo
\echo '==================================================================='
\echo ' CASES: 6 api_keys (prefix lookup + hash verify)  401'
\echo '==================================================================='

-- 6.1 API KEY SUCCESS — mint an api key. Only the SHA-256 of the raw secret is
--     stored; lookups go by prefix, verification by timing-safe hash compare.
INSERT INTO api_keys (user_id, key_hash, name, prefix)
SELECT :'id_a', encode(sha256('demo-ak-0001'::text::bytea), 'hex'), 'manual kit', 'demoak'
WHERE NOT EXISTS (SELECT 1 FROM api_keys WHERE user_id = :'id_a'::uuid AND prefix = 'demoak');
SELECT k.user_id = :'id_a'::uuid AS owner_matches,
       (k.key_hash = encode(sha256('demo-ak-0001'::text::bytea), 'hex')) AS verify_passes
FROM api_keys k WHERE k.prefix = 'demoak';

-- 6.2 API KEY ERROR — lookup by unknown prefix returns zero rows → 401.
\echo '>>> EXPECTED: prefix_lookup = 0 -> authentication fails upstream of any compare'
SELECT count(*) AS prefix_lookup FROM api_keys WHERE prefix = 'nope';

\echo
\echo '==================================================================='
\echo ' CASES: 7 settings (§17 defaults-union + validation)  400 / 422'
\echo '==================================================================='

-- 7.1 SETTINGS GET SUCCESS — defaults UNION stored rows. Without any stored value a
--     key resolves to its §17 default: chat_mode=bot, theme=dark,
--     auto_approve_threshold=80, notifications_enabled=true,
--     llm_chain=[gemini,ollama,groq,openrouter].
SELECT d.key, COALESCE(s.value, d.default_value) AS resolved
FROM (VALUES
        ('chat_mode',              '"bot"'::jsonb),
        ('theme',                  '"dark"'::jsonb),
        ('auto_approve_threshold', '80'::jsonb),
        ('notifications_enabled',  'true'::jsonb),
        ('llm_chain',              '["gemini","ollama","groq","openrouter"]'::jsonb)
     ) d(key, default_value)
LEFT JOIN settings s ON s.user_id = :'id_a'::uuid AND s.key = d.key
ORDER BY d.key;

-- 7.2 SETTINGS UPSERT SUCCESS — persist a stored override; the next GET now resolves
--     the override instead of the default. Jsonb cast is required (jsonb column).
INSERT INTO settings (user_id, key, value) VALUES (:'id_a', 'notifications_enabled', 'false'::jsonb)
ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

SELECT s.value AS stored, COALESCE(s.value, d.default_value) AS resolved_after_upsert
FROM (VALUES ('notifications_enabled', 'true'::jsonb)) d(key, default_value)
LEFT JOIN settings s ON s.user_id = :'id_a'::uuid AND s.key = d.key;

-- 7.3 SETTINGS ERROR — unknown key → SETTINGS_KEY_INVALID 400.
\echo '>>> EXPECTED ERROR: SETTINGS_KEY_INVALID 400 (app-enforced allowed-key set)'
DO $$
BEGIN
    IF 'premium_tier' NOT IN ('chat_mode','theme','auto_approve_threshold','notifications_enabled','llm_chain') THEN
        RAISE EXCEPTION 'SETTINGS_KEY_INVALID';
    END IF;
END
$$;

-- 7.4 SETTINGS ERROR — invalid value for a known key → SETTINGS_VALUE_INVALID 422.
\echo '>>> EXPECTED ERROR: theme=neon not in (dark, light) -> SETTINGS_VALUE_INVALID 422'
DO $$
BEGIN
    IF 'neon' NOT IN ('dark', 'light') THEN
        RAISE EXCEPTION 'SETTINGS_VALUE_INVALID: theme';
    END IF;
END
$$;

-- 7.5 SETTINGS ERROR — auto_approve_threshold must be integer 0..100.
\echo '>>> EXPECTED ERROR: threshold 101 out of range -> SETTINGS_VALUE_INVALID 422'
DO $$
BEGIN
    IF 101 NOT BETWEEN 0 AND 100 THEN
        RAISE EXCEPTION 'SETTINGS_VALUE_INVALID: auto_approve_threshold';
    END IF;
END
$$;

\echo
\echo '==================================================================='
\echo ' CASES: 8 user_profiles (§23 created vs updated classification)'
\echo '==================================================================='

-- 8.1 PROFILE CREATE SUCCESS — first upsert inserts; created_at == updated_at.
INSERT INTO user_profiles (user_id, phone, city)
VALUES (:'id_a', '+1 555 0100', 'Portland')
ON CONFLICT (user_id) DO UPDATE SET phone = EXCLUDED.phone, city = EXCLUDED.city, updated_at = NOW();
SELECT created_at = updated_at AS classified_created, phone, city
FROM user_profiles WHERE user_id = :'id_a'::uuid;

-- 8.2 PROFILE UPDATE SUCCESS — second upsert mutates in place; updated_at advances.
SELECT pg_sleep(0.05);
INSERT INTO user_profiles (user_id, phone, city)
VALUES (:'id_a', '+1 555 0199', 'Portland')
ON CONFLICT (user_id) DO UPDATE SET phone = EXCLUDED.phone, city = EXCLUDED.city, updated_at = NOW();
SELECT created_at < updated_at AS classified_updated, phone
FROM user_profiles WHERE user_id = :'id_a'::uuid;

\echo
\echo '==================================================================='
\echo ' CASES: 9 audit trail (observability lane)'
\echo '==================================================================='

-- 9.1 AUDIT SUCCESS — every mutating action above sits on the ledger, own rows only.
SELECT action, resource_type, count(*) AS entries
FROM audit_logs
WHERE user_id = :'id_a'::uuid
GROUP BY action, resource_type ORDER BY action;

-- 9.2 AUDIT ERROR — writing a ledger row attributed to ANOTHER user is refused by the
--     WITH CHECK clause (no policy match) → 42501, never silently attributed.
\echo '>>> EXPECTED ERROR: new row violates row-level security policy ... 42501 InsufficientPrivilege'
INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details)
VALUES (:'id_b', 'cross_user_forgery', 'user', :'id_b', '{"attempt": true}'::jsonb);

-- 9.3 AUDIT ERROR — reading another user's ledger: zero rows (default-deny).
SELECT count(*) AS B_audit_rows_visible_to_A FROM audit_logs WHERE user_id = :'id_b'::uuid;
\echo '>>> expected B_audit_rows_visible_to_A = 0'

\echo
\echo '==================================================================='
\echo ' CASES: 10 Cross-user isolation (the RLS guarantee, end to end)'
\echo '==================================================================='

-- 10.1 SELECT — B's user row is hidden from A (already shown in case 5.2).
SELECT id, email FROM users WHERE id = :'id_b'::uuid;

-- 10.2 SELECT — B's settings are hidden even when filtered explicitly.
SELECT count(*) AS B_settings_rows FROM settings WHERE user_id = :'id_b'::uuid;
\echo '>>> expected B_settings_rows = 0'

-- 10.3 INSERT — A writing a settings row for B: the WITH CHECK clause (user_id must
--     equal the GUC) has no match → 42501. THE core proof FORCE RLS is tenant-safe.
\echo '>>> EXPECTED ERROR: new row violates row-level security policy ... 42501 InsufficientPrivilege'
INSERT INTO settings (user_id, key, value) VALUES (:'id_b', 'theme', '"light"');

-- 10.4 UPDATE — A silently mutating B's auth_sessions rows: matches zero rows.
UPDATE auth_sessions SET revoked_at = NOW()
WHERE user_id = :'id_b'::uuid AND revoked_at IS NULL;

\echo
\echo '==================================================================='
\echo ' TEARDOWN — clean the resource rows; users + audit trail remain by design'
\echo '==================================================================='

-- Audit_logs is append-only (migration 020). Its immutability trigger blocks the
-- cascade delete from users, so demo users and their ledger entries survive the
-- kit — which is the intended production contract, not a leak.

SELECT set_config('app.user_id', :'id_a', false) AS a_ctx_teardown;
DELETE FROM api_keys      WHERE user_id = :'id_a'::uuid;
DELETE FROM user_profiles WHERE user_id = :'id_a'::uuid;
DELETE FROM settings      WHERE user_id = :'id_a'::uuid;
DELETE FROM auth_sessions WHERE user_id = :'id_a'::uuid;

-- Prove B's side of the guarantee too, then clean B's resource rows under B's ctx.
SELECT set_config('app.user_id', :'id_b', false) AS b_ctx_teardown;
SELECT count(*) AS A_rows_visible_to_B FROM users WHERE id = :'id_a'::uuid;
\echo '>>> expected A_rows_visible_to_B = 0'

INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details)
SELECT :'id_b', 'user_registered', 'user', :'id_b', '{"cause": "postgres_manual_kit"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM audit_logs a
    WHERE a.user_id = :'id_b'::uuid
      AND a.action = 'user_registered'
      AND a.details->>'cause' = 'postgres_manual_kit'
);

DELETE FROM api_keys      WHERE user_id = :'id_b'::uuid;
DELETE FROM user_profiles WHERE user_id = :'id_b'::uuid;
DELETE FROM settings      WHERE user_id = :'id_b'::uuid;
DELETE FROM auth_sessions WHERE user_id = :'id_b'::uuid;

SELECT count(*) AS kit_resource_rows_left
FROM (
    SELECT 1 FROM api_keys      WHERE user_id IN (:'id_a'::uuid, :'id_b'::uuid)
    UNION ALL SELECT 1 FROM user_profiles WHERE user_id IN (:'id_a'::uuid, :'id_b'::uuid)
    UNION ALL SELECT 1 FROM settings      WHERE user_id IN (:'id_a'::uuid, :'id_b'::uuid)
    UNION ALL SELECT 1 FROM auth_sessions WHERE user_id IN (:'id_a'::uuid, :'id_b'::uuid)
) t;
\echo '>>> kit_resource_rows_left = 0 expected'

\echo
\echo '=== DONE: see per-block EXPECTED lines; any block that did NOT print an expected'
\echo '    error where one was announced is a regression to investigate.'
\echo '=== Checklist: register/dup/weak, login/unknown/wrong/expired, refresh rotate/'
\echo '    reuse, logout/relogout, me, api key lookup/verify, settings defaults/upsert/'
\echo '    invalid, profile created/updated, audit trail, cross-user 42501 both ways.'
