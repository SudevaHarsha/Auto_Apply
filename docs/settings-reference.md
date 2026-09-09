# Settings Table Reference

The `settings` table (created in `db/migrations/013_create_settings.sql`) stores
per-user key/value preferences. One row exists per written `(user_id, key)`
option; options that have never been written have **no row** and are supplied by
the read-time defaults merge (see below).

## Schema

```sql
CREATE TABLE settings (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT  NOT NULL,
    value   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
```

## All possible rows (authoritative spec — `backend/app/auth/settings_service.py` `SETTINGS_SPEC`)

| key                     | JSONB value shape              | valid values                                   | PUT default | seeded at register | example row (user = U)                          |
|-------------------------|--------------------------------|------------------------------------------------|-------------|--------------------|-------------------------------------------------|
| `chat_mode`             | string                         | `"bot"` \| `"agent"`                            | n/a         | yes (`"bot"`)      | `(U, 'chat_mode', '"bot"')`                     |
| `theme`                 | string                         | `"dark"` \| `"light"`                           | n/a         | yes (`"dark"`)     | `(U, 'theme', '"dark"')`                        |
| `auto_approve_threshold`| number (integer)               | integer 0..100                                 | 80          | no                 | `(U, 'auto_approve_threshold', 80)`             |
| `notifications_enabled` | boolean                        | `true` \| `false`                               | true        | no                 | `(U, 'notifications_enabled', true)`            |
| `llm_chain`             | array of strings               | non-empty array of `"gemini"`, `"ollama"`, `"groq"`, `"openrouter"` | `["gemini"]` | no            | `(U, 'llm_chain', '["gemini"]')`                |

Notes:
- `value` is JSONB, so every option writes as a JSON value: strings appear as
  `"..."` (quoted) when dumped by psql, numbers/booleans unquoted, arrays as JSON
  lists.
- Register side effect (`DEFAULT_SETTINGS_SEEDS` in
  `backend/app/db/repositories/auth_repository.py`): exactly **two** rows are
  inserted — `chat_mode="bot"` and `theme="dark"`. The other three options have
  no row until the user PUTs them.

## Read behavior (`SettingsService.get`)

`GET /api/auth/settings` returns all five keys, always:

```
defaults ∪ stored   (stored rows win for keys that exist)
```

Defaults: `chat_mode="bot"`, `theme="dark"`, `auto_approve_threshold=80`,
`notifications_enabled=true`, `llm_chain=["gemini"]`.

## Write behavior (`SettingsService.update`)

`PUT /api/auth/settings` is a partial upsert:

1. unknown key  -> `SETTINGS_KEY_INVALID` (400)
2. invalid value-> `SETTINGS_VALUE_INVALID` (422)
3. each valid key is **upserted** on `(user_id, key)` (INSERT ... ON CONFLICT
   DO UPDATE), so updates never create duplicate rows
4. writes an `settings_updated` audit row (`resource_type='settings'`)
5. returns the post-merge five-key object

## Garbage rows

Rows whose key is not in the five-key spec (e.g. a manually inserted
`(user, 'k', '{"options":...}')` row) are **ignored by GET** — the merge only
overlays spec keys — and the API refuses to create them. They are harmless but
should be deleted if pure: `DELETE FROM settings WHERE key NOT IN ('chat_mode','theme','auto_approve_threshold','notifications_enabled','llm_chain');`

## Example: full row set for one user

After registering and then PUTting all remaining defaults, the table holds five
rows for that user:

```
 user_id | key                      | value
---------+--------------------------+-------------------
 U       | chat_mode                | "bot"
 U       | theme                    | "dark"
 U       | auto_approve_threshold   | 80
 U       | notifications_enabled    | true
 U       | llm_chain                | ["gemini"]
```