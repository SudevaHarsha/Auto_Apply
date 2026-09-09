# Job Discovery & JD Extraction Strategy

> **Purpose of this file:** One place that explains — in plain language — where our jobs come from, how we read job descriptions out of them, why we built it this way, and what we deliberately refuse to do. Written so that re-reading it months later still makes sense without any other context.
>
> **Status:** Strategy approved in discussion; not yet implemented. Implementation items are marked 📋 throughout.
>
> **Date:** 2026-08-26 · **Based on:** competitor analysis in `competitors/COMPARISON.md`

---

## 1. The one-paragraph summary

We collect jobs from **8 legitimate sources** (bots, public APIs, email — never by pretending to be a human user on LinkedIn), and we read each job description through a **5-door cascade** where the first doors cost nothing and only unknown pages ever reach the AI. On top we add two memory layers — a shared cache and immutable snapshots — so we never pay twice for the same posting and always know exactly which version of a posting we scored against.

**Why this design:** every competitor that scrapes aggressively either died (AIHawk), lives in constant maintenance debt (ApplyPilot's config catalog), or burns engineering time fighting detection (AutoApply). We spend the same effort on coverage and accuracy instead.

---

## 2. Background — what we learned from the competitors

Our system scored **3 out of 5** in both "Discovery breadth" and "JD capture craft" against three competitors. Here is *why* each of them is strong/weak, because the strategy below is built directly on those lessons.

### 2.1 AIHawk — weak at everything (scored 2/2)

- Logs into LinkedIn as the user with Selenium and scrolls saved searches. One source only.
- LinkedIn fights back (bot detection) → selectors break constantly → silently finds nothing.
- Re-scrapes the entire search space every run, remembers nothing.
- Its "extraction" asks GPT questions about raw DOM → hallucinated fields, unauditable.
- **Lesson taken:** keyword filters and canned answer banks survived; the architecture did not.

### 2.2 ApplyPilot — widest funnel (scored 5/5), but rented

Its breadth comes from four source families:

| Family | How it actually fetches | Interface status |
|---|---|---|
| Boards via JobSpy lib (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs) | Calls the boards' **unofficial internal endpoints** (reverse-engineered, no login) | Gray zone |
| ~48 Workday portals | POSTs to Workday's **private CXS JSON API** (`/wday/cxs/{tenant}/{site}/jobs`) using a hand-maintained company list | Public data, private API |
| ~30 Greenhouse/Lever slugs | Public boards / official APIs | Clean ✅ |
| Detail pages | JSON-LD → CSS → LLM cascade; hardest cases delegated to a Claude Code agent driving the user's real Chrome | Mixed |

**Its weakness = maintenance ceiling:** breadth is bought with configuration mass. Every Workday refresh silently breaks N entries; every board endpoint change breaks JobSpy. And being gray-zone means one provider crackdown kills a chunk of sources overnight.

**Lessons taken (ideas, not sources):**
- Zero-token cascades — try free structured data before paying the LLM.
- SKIPPED-as-first-class outcomes — record *why* something was rejected, don't drop it silently.
- Strategy caching — intelligence spent once, executed deterministically forever after.

### 2.3 AutoApply — best truth layer, weakest funnel (scored 4/4)

- Discovery is essentially LinkedIn scraping (persistent browser sessions, pacing jitter) plus hand-listed Greenhouse/Lever slugs. No open keyword search at all.
- All its engineering cleverness flows into **evasion** (fingerprints, humanized pacing) instead of coverage.
- Where it wins: immutable content-hash snapshots of postings, freshness states, typed extraction schema, ~105 test files.
- **Lessons taken:** snapshot versioning, freshness FSM, rich structured schema, decision-record culture.

### 2.4 Our own honest gaps (why we scored 3)

| Gap | Cause |
|---|---|
| Discovery = 3 | Funnel was push-only (Telegram/Discord/manual paste). No automated pull from any board. Coverage depended entirely on which groups the user joined. |
| Capture = 3 | Single-stage extractor: fetch HTML → dump whole page into LLM → parse. No cheap stages first. Same posting extracted again and again for different users. No versioning. No freshness checks — extension could open an expired posting days later. |

---

## 3. Design principles (the rules everything below follows)

1. **Never impersonate.** We never log into a site as a user, never fake a browser fingerprint, never hammer undocumented internal endpoints from our servers. Reading what a bot you own was added to, calling an officially public API, or reading the user's own email — all fine. Everything else — no.
2. **Pull structured before scraping HTML.** If the same fact exists as clean JSON somewhere, never parse it out of a web page.
3. **Never pay twice.** Same posting seen by two users → extracted once, cached for both.
4. **Every decision leaves a trace.** Filtered, expired, failed — recorded with a reason, never silently dropped.
5. **Every artifact binds to a version.** Scores, rubrics, packages reference the exact snapshot of the posting they were computed against.

---

## 4. THE SOURCE LIST — where our jobs come from

Think of it as: **we only read what companies publicly display or hand us willingly.**

| # | Source | How it works | Cost | Phase |
|---|---|---|---|---|
| 1 | **Telegram groups/channels** | User adds our bot to groups they're in. When someone posts "we're hiring: [link]", the bot catches the message, extracts URLs, creates a job row | Free | Live today |
| 2 | **Discord servers** | Same idea via Discord bot | Free | Live today |
| 3 | **Manual paste** | User pastes any job URL into dashboard / chat / extension popup | Free | Live today |
| 4 | **Greenhouse watchlists** 📋 | Big companies host careers on `boards.greenhouse.io/{company}`. Greenhouse publishes an **official public API**: `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`. We poll it per user's company list and get clean JSON with full descriptions | Free | Build now |
| 5 | **Lever watchlists** 📋 | Same pattern: `api.lever.co/v0/postings/{slug}?mode=json` | Free | Build now |
| 6 | **Aggregator search** 📋 | Sites built FOR programmatic access: **Adzuna, Remotive, RemoteOK, Arbeitnow** (+ JSearch free tier). They aggregate postings from thousands of companies. We run the user's keyword/location/remote/salary preferences against their APIs | Free tier | Build now |
| 7 | **RSS feeds** 📋 | Company career blogs and remote-job feeds publish update feeds; we subscribe and ingest new entries | Free | Build now |
| 8 | **Email alerts** 📋 | User switches on LinkedIn/Indeed alert emails → those emails land in *their* inbox → our IMAP reader ingests them automatically. The boards' own matching engines work **for** us, legally, through the user's consented mailbox | Free | Phase 2 |

### 4.1 What users configure (Settings → Job Sources)

Each user manages their own sources. Per source they set:

```
Type:        greenhouse | lever | aggregator | rss   (telegram/discord/email are
                                                      connection-based, not config-based)
Config:      {"company_slug": "stripe"}                        ← watchlist
             {"provider": "adzuna", "keywords": ["backend"],   ← open search
              "locations": ["Berlin"], "remote_only": true,
              "salary_min": 80000}
Active:      on/off toggle
Schedule:    automatic (staggered polling), manual "Poll now" button
```

### 4.2 What we deliberately DON'T take — and why

| Skipped source | Why skipped |
|---|---|
| Logging into LinkedIn/Indeed as the user (AIHawk/AutoApply style) | Account bans land on the user; ToS violation; detection arms race forever |
| Unofficial board endpoints (JobSpy-style) | No account to ban, but still ToS-violating private endpoints — and at SaaS scale the IP reputation and legal exposure land on **us**, not a hobbyist's home connection |
| Workday private CXS endpoints (ApplyPilot style) | Data is public but the API is undocumented; matching ApplyPilot here means maintaining a growing company-config catalog forever |

This skipped set is what we called **"the scraped long tail."** We accept losing it because:

1. **Aggregators index much of the same inventory** through legitimate doors — Adzuna-class search recovers a large share of what native Indeed/LinkedIn search would give.
2. **Email alerts are the sanctioned backdoor** — the user tells LinkedIn/Indeed what they want; the boards' own relevance engine sends matches to the user's inbox; we ingest the inbox. Better relevance than any scraper, zero risk.
3. **JSON-LD catches much of the rest for free** (see Door 2 below) — most modern career pages embed structured markup for Google anyway.

**Residual true loss:** real-time native board search UX and deep Fortune-500 Workday catalogs. That is the price of the no-impersonation rule — and it's exactly where AIHawk died and where AutoApply burns its roadmap.

---

## 5. THE EXTRACTION CASCADE — how we read a job description

Rule: **never pay for what you can get free; never guess what you can read directly.**

When any URL enters the funnel (from ANY source — bot message, paste, API poll), it walks five doors in order. Each door runs only if earlier doors left gaps. Most jobs finish at Door 1 or 2 having spent **zero tokens**.

```
URL ──▶ Door 0 ──▶ Door 1 ──▶ Door 2 ──▶ Door 3 ──▶ Door 4 ──▶ Door 5 ──▶ structured JD
        classify    ask ATS     read hidden   strip page    LLM fills     tiny patch-up
                    public API  label         text only     the form      if critical
                                                                            fields missing
```

| Door | What happens | Token cost | Quality |
|---|---|---|---|
| **0. Classify** | Regex fingerprinting of the URL: is it Greenhouse? Lever? LinkedIn? Unknown? Routes to the right door and enables platform-specific handling downstream | 0 | — |
| **1. ATS public API** | If Greenhouse/Lever → call their official public JSON endpoints directly. Get title, description, location, department as clean data. **Best possible quality — no parsing at all** | 0 | ★★★★★ |
| **2. JSON-LD label** | Any page: look for `<script type="application/ld+json">` containing schema.org `JobPosting` markup. Websites embed this summary card for Google Search — we just read it | 0 | ★★★★☆ |
| **3. Text stripping** | Fallback: cut menus/ads/footers out of the HTML, keep only the main posting text (readability-style reduction, typically ~10× smaller input) | 0 | raw material |
| **4. LLM form-filling** | Send the CLEAN short text (never raw HTML) to the LLM, which fills our structured Pydantic form (schema in §6). One cheap call on free-tier providers | ~1 call | ★★★★☆ |
| **5. Gap check** | Validate the filled form. Only if *critical* fields are missing (e.g., skills empty), one targeted follow-up question to the LLM | 0–1 calls | completeness |

### 5.1 Why this beats every competitor's extractor

| Competitor | Their way | Our answer |
|---|---|---|
| AIHawk | GPT answers questions about raw DOM → hallucinations, no audit trail | Structured stages, deterministic where possible, provenance on every field |
| ApplyPilot | Similar cascade idea — but its Stage-1 equivalents depend on fragile reverse-engineered endpoints; cached scrape-strategies go stale when sites redesign | Our Doors 1–2 use **stable public contracts** (official APIs, SEO markup standards) that don't rot. Nothing cached to go stale |
| AutoApply | Playwright-scrape then typed-schema extract — accurate but pays full acquisition + evasion cost, and single-tenant so it re-extracts per instance | Same schema quality, near-zero marginal cost via Doors 1–2, plus shared cache below |

---

## 6. The structured JD form (what Door 4 fills)

Extended from our current Title/Company/Skills/Requirements model toward AutoApply-level richness. Every field carries `confidence` + `extracted_via_door` so we always know how each fact was obtained.

```jsonc
{
  "title": "...",
  "company": "...",
  "location": "...",
  "remote_policy": "onsite | hybrid | remote",
  "employment_type": "full_time | contract | ...",
  "seniority": "junior | mid | senior | staff | lead",
  "experience_range": {"min_years": 3, "max_years": null},
  "salary": {"min": null, "max": null, "currency": "USD", "period": "year"},
  "skills": {
    "required": ["python", "postgres"],
    "preferred": ["kafka"]
  },
  "education": {...},
  "work_auth_visa": {...},           // sponsorship offered? restrictions?
  "benefits": [...],
  "responsibilities": [...],
  "screening_question_hints": [...], // likely ATS questions to prefill answers for
  "posted_at": "...",
  "application_deadline": null,
  "_meta": {"extracted_via_door": 2, "confidence": {...}}
}
```

These fields feed straight into rubric generation weights (our scoring differentiator) and interview/screening-question prep.

---

## 7. Memory layers — never pay twice, never score against a ghost

### 7.1 Shared extraction cache 📋

Extraction results keyed by **content fingerprint** of the posting. Stored WITHOUT user_id, outside row-level-security — legal and safe because job postings are public data with zero personal information.

> Example: 500 users see the same Stripe posting → Door 1/2 runs **once**, 499 cache hits. On free-tier quotas this is transformative. (Single-user competitors never even face this problem.)

### 7.2 Immutable snapshots 📋

Every extraction writes an append-only `job_snapshots` row: `{id, content_hash UNIQUE, payload, captured_at}`. Rubrics, scores, and application packages **bind to a snapshot_id**.

> Answers forever: *"What EXACTLY did we score against?"* and *"Did the posting change since we prepared the package?"*

### 7.3 Freshness FSM 📋

Jobs carry `freshness_state: fresh | stale | expired` with stake-tiered budgets adopted from AutoApply:

| Tier | Budget | Meaning |
|---|---|---|
| Search-tier | 72h | listing considered current for discovery/ranking |
| Package-tier | 6h | re-check right before the Chrome Extension opens the form — kills the "extension opens a dead posting" failure class |

---

## 8. Decision-trace upgrades (outcome-as-data) 📋

Whenever the system decides NOT to proceed with something it has seen, it records why — queryable, never silent:

```sql
ALTER TABLE applications ADD COLUMN skip_reason TEXT;
-- fill-time blockers on the application: 'ss_wall', 'captcha',
-- 'unsupported_platform', 'expired'
-- invariant: applications.status='skipped'  ⇒  applications.skip_reason IS NOT NULL
```

A job that isn't shown to the user is simply left in `jobs.status` (e.g. `discovered`/`scored` below threshold, or `skipped`) — there is no `jobs.skip_reason`; the canonical `skip_reason` lives on `applications` and records why a fill was blocked.

Plus URL canonicalization before dedup (strip UTM/tracking params) so the same job entering via Telegram AND a Greenhouse poll counts once (`jobs UNIQUE(user_id, url)`).

---

## 9. Implementation plan

| Step | Items | Size |
|---|---|---|
| **a. Quick wins** | URL classifier (Door 0) · GH/Lever probe (Door 1) · JSON-LD reader (Door 2) inside existing extractor · URL normalizer | days |
| **b. Discovery unlock** | `job_sources` table + RLS · `/api/sources` CRUD + poll trigger API · poller service honoring `next_poll_at` + `rate_limit_state` circuit breakers · first aggregator integration (Adzuna) · extend `jobs.source` CHECK constraint | core build |
| **c. Quality unlock** | ~~`job_snapshots` migration~~ (written: migration 025 in `docs/database/schema.md` ✅) · freshness FSM fields+budgets (written in 025 ✅) · shared `jd_cache` runtime + cache-hit path · bind rubrics/packages to `snapshot_id` at build time | core build |
| **d. Phase 2 breadth** | IMAP ingestion (alert emails) · RSS source type · remaining aggregators | later |

Schema sketches for steps b/c live in §8 above and in the discussion history. Step **c**'s snapshot + freshness spec is now formalized as **migration 025** in `docs/database/schema.md` (canonical) and mirrored in the core-engine component schema; the shared `jd_cache` hit-path (`jd_cache` runtime, cache warm, snapshot binding) remains stub-until-implementation. No new API endpoints are required for snapshots (internal-only), so no `docs/api_contracts/schema.md` change is needed there.

---

## 10. Expected outcome

| Dimension | Before | After | Why believable |
|---|---|---|---|
| Discovery breadth | 3 | **~4.5** | Push channels + public-API pull + email alerts ≈ boards + career sites + keyword search. Only ApplyPilot's gray-zone long tail stays uncovered — deliberately (§4.2) |
| JD capture craft | 3 | **~4.5** | Five-door cascade ≥ ApplyPilot's, with none of its staleness problems; shared cache on top which nobody else even has |
| Truth/versioning | 1 | **~4.5** | Snapshots + freshness ≈ AutoApply's best layer, plus evidence-chain linkage theirs lacks |
| Structured schema | 3 | **~4.5** | Typed schema with per-field provenance feeding a scoring loop no competitor has |

The residual half-point everywhere is the honest price of Rule 1 (never impersonate) — and it is the right trade, because that half-point is precisely where AIHawk died and where AutoApply spends its engineering budget.
