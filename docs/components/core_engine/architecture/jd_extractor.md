# Core Engine — JD Extractor

Fetches a career page URL and extracts structured job description data using a 5-door cascade. Never pays for what it can get free; never guesses what it can read directly.

---

## Extraction Cascade (5 Doors)

Every URL walks doors in order. Each door runs only if earlier doors left gaps. Most postings finish at Door 1 or 2 at zero token cost.

```
URL ──▶ Door 0 ──▶ Door 1 ──▶ Door 2 ──▶ Door 3 ──▶ Door 4 ──▶ structured JD
        classify    ask ATS     read hidden   strip page    LLM fills     Door 5
                    public API  label         text only     the form       (gap-fill)
```

### Door 0 — URL Classification (0 tokens)

Regex fingerprinting routes the URL to the correct downstream door.

| Pattern | Routes to |
|---|---|
| `boards.greenhouse.io/*` or `*.greenhouse.io/jobs/*` | Door 1 (Greenhouse API) |
| `jobs.lever.co/*` or `lever.co/postings/*` | Door 1 (Lever API) |
| `*.myworkdayjobs.com/*` | Door 2 (JSON-LD) |
| Any other URL | Door 2 (JSON-LD) |

### Door 1 — ATS Public API (0 tokens)

For Greenhouse and Lever, call their official public JSON endpoints directly. Cleanest possible data — no parsing required.

| ATS | Endpoint | Response |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | JSON: title, description, location, department |
| Lever | `api.lever.co/v0/postings/{slug}?mode=json` | JSON: title, description, team, commitment |

### Door 2 — JSON-LD Label (0 tokens)

Any page: look for `<script type="application/ld+json">` containing schema.org `JobPosting` markup. Most modern career pages embed this for Google Jobs — we just read it. Zero HTML parsing required.

### Door 3 — Text Stripping (0 tokens)

Fallback: cut menus, ads, footers out of the HTML. Keep only the main posting text using readability-style reduction. Input to LLM becomes ~10× smaller than raw HTML.

### Door 4 — LLM Form-Filling (~1 call)

Send the CLEAN short text (never raw HTML) to the LLM via the provider chain. LLM fills the structured JD form (§Structured JD Schema below). One cheap call on free-tier providers.

### Door 5 — Gap-fill (0–1 calls)

Validate the filled form. Only if critical fields are missing (e.g., skills completely empty), one targeted follow-up question to the LLM.

---

## Shared Extraction Cache

Results keyed by content fingerprint. Stored WITHOUT user_id — public job data, zero PII.

500 users see the same Stripe posting → Door 1/2 runs **once**, 499 users hit cache.

On free-tier quotas this is transformative. Single-user competitors never face this problem, so the idea doesn't exist elsewhere.

---

## Snapshots & Freshness (Truth/Versioning)

Every extraction result is immutable and version-stamped so "what did we score against?" is forever answerable — the gap we deliberately do **not** inherit from competitors.

### Job Snapshots

- The cache is backed by the **`job_snapshots`** table: a row per unique `content_hash` with the full structured JD as `payload`.
- `content_hash` is the fingerprint key also used by the shared cache (one table serves both).
- When a posting is re-fetched and the hash **changes**, a new snapshot row is inserted and `jobs.current_snapshot_id` advances — the posting is a *different version*.
- `applications.snapshot_id` records exactly which snapshot the rubric/package was built against, so a stale package can be flagged instead of silently mis-scored.

### Freshness FSM (stake-tiered budgets)

| Tier | Budget | State transition |
|---|---|---|
| Search-tier | 72h | `fresh → stale` after 72h; drives discovery/ranking |
| Package-tier | 6h | `stale → expired` if confirm re-fetch fails; blocks extension fill |

Flow:

```
fetch → compute content_hash
  ├─ cache hit (hash in job_snapshots)   → load payload, refresh last_fetched_at, keep fresh
  ├─ hash changed                        → new snapshot, bump jobs.current_snapshot_id
  └─ fetch fails / 404                   → jobs.freshness_state = stale
          └─ at package time (6h) confirm fails → expired (blocks fill → skip_reason='expired')
```

`jobs.freshness_state` (user-scoped) mirrors the snapshot check per user; `job_snapshots` is shared and RLS-exempt (no PII, public job data).

---

## Structured JD Schema

Extended schema with per-field provenance. Each field carries `confidence` + `extracted_via_door`.

```jsonc
{
  "title": "Senior Backend Engineer",
  "company": "Stripe",
  "location": "San Francisco, CA (Remote)",
  "remote_policy": "remote",
  "employment_type": "full_time",
  "seniority": "senior",
  "experience_range": {"min_years": 5, "max_years": null},
  "salary": {"min": 150000, "max": 200000, "currency": "USD", "period": "year"},
  "skills": {
    "required": ["python", "postgres", "redis"],
    "preferred": ["kafka", "kubernetes"]
  },
  "education": {"level": "bachelors", "field": "Computer Science"},
  "work_auth_visa": {"sponsorship": true},
  "responsibilities": ["Design APIs", "Lead team of 5"],
  "screening_question_hints": ["Why interested in Stripe?"],
  "posted_at": "2026-08-15",
  "_meta": {"extracted_via_door": 2, "confidence": {"title": 0.95, "skills": 0.8}}
}
```

Fields feed directly into rubric generation weights and screening-question prep.

---

## Platform Detection

```
URL Pattern                          Platform
────────────────────────────────────────────────────
boards.greenhouse.io/*               → greenhouse
*.greenhouse.io/jobs/*               → greenhouse
jobs.lever.co/*                      → lever
lever.co/postings/*                  → lever
*.myworkdayjobs.com/*                → workday
linkedin.com/jobs/*                  → linkedin (manual paste only)
indeed.com/viewjob/*                 → indeed (manual paste only)
(any other URL)                      → generic
```

---

## What Changes vs Previous Design

| Before | After |
|---|---|
| 3 steps: fetch → parse → LLM | 5 doors: classify → API → JSON-LD → strip → LLM → gap-fill |
| Every URL hits the LLM | Most finish at Door 1 or 2 (zero tokens) |
| No caching | Shared content-fingerprint cache across users |
| No per-field provenance | Each field tagged with `extracted_via_door` and `confidence` |
| Flat structured schema | Extended schema: seniority, experience range, salary, visa, remote policy |
| No version truth | `job_snapshots` immutable, hash-stamped, `applications.snapshot_id` binds rubric to version |
| No freshness tracking | `freshness_state` FSM with stake-tiered budgets (72h search / 6h package) |
