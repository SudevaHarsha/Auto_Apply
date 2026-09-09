# Auth — Database Scope

Owns user identity, API key management, and supplemental personal info.

---

## Tables Owned

```
TABLE           PURPOSE                              WRITES
────────────────────────────────────────────────────────────
users           Account + auth credentials           CREATE, UPDATE
api_keys        API keys for MCP/remote access       CREATE, UPDATE, DELETE
settings        User preferences                     CREATE, UPDATE
user_profiles   Supplemental personal info            CREATE, UPDATE
auth_sessions   Refresh-token revocation (logout)     CREATE, UPDATE
```

---

## Tables Read

```
TABLE             READ BY                      WHY
────────────────────────────────────────────────────
settings          auth (on user create)        creates default settings row
user_profiles     auth (on user create)        creates empty profile row
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE             WRITER               WHY
────────────────────────────────────────────────────
audit_logs        auth                 logs auth events (INSERT)
```

---

## Data Flow

```
REGISTER:
  auth → users (INSERT with pre-generated uuid4() id — D6, survives FORCE RLS)
  auth → settings (INSERT default preferences — exactly the canonical 2 rows, D11)
  auth → user_profiles (INSERT empty supplemental profile)
  auth → audit_logs (INSERT action: user_registered)

LOGIN:
  auth → users (via SECURITY DEFINER auth_user_by_email(email); single row, exact email — D10)
  auth → audit_logs (INSERT action: user_logged_in)

CREATE API KEY:
  auth → api_keys (INSERT key_hash = SHA-256; one-time plaintext returned exactly once — D7/D12)

VERIFY API KEY:
  auth → api_keys (SELECT by prefix, constant-time hash compare)

DELETE API KEY:
  auth → api_keys (DELETE by id)

LOGOUT (D9):
  auth → auth_sessions (UPDATE revoked_at = NOW() WHERE jti_hash AND revoked_at IS NULL)

SETTINGS (D11):
  Register seeds exactly 2 canonical rows; GET /settings = defaults ∪ stored (5 keys);
  PUT /settings upserts validated keys only → audit settings_updated.
```

---

## Relationships

```
users (1) ────< (N) api_keys
users (1) ────< (N) audit_logs
users (1) ────< (N) settings
users (1) ────< (N) auth_sessions
users (1) ──────── (1) user_profiles
```
