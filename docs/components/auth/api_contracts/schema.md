# Auth — API Contract

> **Consumes:** `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`, `GET /api/auth/me`
> **Owns:** None (auth is consumed, not exposed to other components)
> **Canonical source:** `docs/api_contracts/schema.md` §7
> **Transport:** Bearer-only (`Authorization` header). Cookies are NOT part of the API contract —
> an optional httpOnly cookie is a frontend (S18) transport concern only (D8, `plans/steps/S3-auth.md`).

---

## Endpoints Consumed

### POST /api/auth/register

Create a new user account.

**Request:**
```json
{
  "email": "string (required, valid email, unique)",
  "password": "string (required, min 8 chars, uppercase, lowercase, digit, special char)",
  "name": "string (required, 1-100 chars)"
}
```

**Response 201:**
```json
{
  "user": {
    "id": "uuid",
    "email": "string",
    "name": "string",
    "created_at": "iso8601"
  },
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Error codes:**
- `AUTH_USER_EXISTS` (409) — email already registered
- `AUTH_WEAK_PASSWORD` (400) — password does not meet requirements
- `VALIDATION_ERROR` (422) — request body failed validation

**Side effects:**
- INSERT into `users` table
- Creates default `settings` rows (chat_mode: bot, theme: dark)
- Logs `user_registered` to `audit_logs`

---

### POST /api/auth/login

Authenticate and receive JWT pair.

**Request:**
```json
{
  "email": "string (required)",
  "password": "string (required)"
}
```

**Response 200:**
```json
{
  "user": {
    "id": "uuid",
    "email": "string",
    "name": "string"
  },
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Error codes:**
- `AUTH_INVALID_CREDENTIALS` (401) — wrong email/password

**Side effects:**
- Logs `user_logged_in` to `audit_logs`

---

### POST /api/auth/refresh

Exchange a valid refresh token for a new access token.

**Request:**
```json
{
  "refresh_token": "string (required)"
}
```

**Response 200:**
```json
{
  "access_token": "string",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Error codes:**
- `AUTH_REFRESH_EXPIRED` (401) — refresh token expired
- `AUTH_TOKEN_INVALID` (401) — malformed or invalid token

---

### POST /api/auth/logout

Revoke the presented refresh token server-side and end the session (D9).

**Headers:** `Authorization: Bearer <refresh_token>`

**Response 200:**
```json
{
  "status": "ok"
}
```

**Error codes:**
- `AUTH_TOKEN_INVALID` (401) — malformed, expired, or already-revoked refresh token

**Side effects:**
- Marks the `auth_sessions` row (migration 026) revoked — `revoked_at` set.
- Old refresh token can no longer rotate. No new audit action (canonical set closed).

---

### GET /api/auth/me

Get the current authenticated user's profile.

**Headers:** `Authorization: Bearer <access_token>`

**Response 200:**
```json
{
  "id": "uuid",
  "email": "string",
  "name": "string",
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

**Error codes:**
- `AUTH_TOKEN_EXPIRED` (401) — access token expired
- `AUTH_TOKEN_INVALID` (401) — malformed or invalid token

---

## RLS Integration

After JWT validation, the backend sets PostgreSQL session variable for row-level security:

```sql
SET LOCAL app.user_id = '<uuid-from-jwt>';
```

Every query automatically filters rows by `user_id`. No cross-user data leakage is possible.

---

## Audit Actions

| Endpoint | Audit Action | Resource Type |
|----------|-------------|---------------|
| POST /register | `user_registered` | user |
| POST /login | `user_logged_in` | user |
| POST /logout | (none) | — |
| GET /me | (none) | — |
