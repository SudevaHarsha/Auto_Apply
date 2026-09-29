# Free LLM Provider Tiers

Reference for expanding the provider set in `backend/app/llm/registry.py` beyond the current
`gemini` / `groq` / `openrouter` / `ollama`. Research refreshed **2026-09-25** from the OmniRoute
catalog (`vendor/OmniRoute/open-sse/config/freeModelCatalog.data.ts`,
`docs/reference/FREE_TIERS.md`) plus live provider docs.

> Free tiers change without notice. Every row carries a verification date and source; re-check
> before wiring a provider into routing. `tpm`/`rpm` figures are the default-free-plan values,
> not the developer/paid tiers.

## TL;DR — what to add first

All of these are **key-based, OpenAI-compatible** (drop-in via `OpenAICompatibleAdapter` — one
line in the registry, no adapter):

1. **nara** — ~210M tokens/month *recurring daily* (NaraRouter free tier resets daily, 07:00 WIB /
   00:00 UTC), OpenAI-compatible. Added to registry + live-verified (2026-09-25).
2. **cloudflare-ai** (Workers AI) — 10,000 Neurons/day *recurring daily*. Added to registry +
   live-verified (2026-09-25); base URL needs your account ID.
3. ~~**mistral**~~ — **deferred (2026-09-25)**: free API quota removed from the free plan (2026-09
   restructure — free tier now = Vibe/Studio access only, API credits sold separately). Account
   Billing shows **0 credits**; every key returns `429` with `x-ratelimit-limit-req-minute: 0`,
   although auth works (`GET /v1/models` → 200, 46 models). Revisit only if the account gains
   API credits.
4. **sambanova** — ⚠️ contested: free tier reportedly withdrawn (402) as of 2026-08; verify
   before adding.

`together` and `siliconflow` host permanently-free (uncapped) models but now require a paid
top-up minimum (`together`) or publish no token cap (`siliconflow`, `recurring-uncapped`).

## Registry mechanics

- New providers = **one registry entry** for OpenAI-compatible endpoints
  (`backend/app/llm/registry.py:36-49`); no migration is ever needed again.
- `tpm` in the entry is the per-minute token gate used by the router's TPM gating
  (`backend/app/llm/router.py`). Set it to the provider's **documented TPM**, not a guess
  (groq's `tpm=8000` is the documented free GPT-OSS value).
- Providers without a documented per-minute token cap that still gate by RPM/RPD can be set
  with `tpm=None` but should then be rate-limited by request count, not tokens.
- Always include a `default_model` that is actually on the provider's free tier
  (groq example: `openai/gpt-oss-20b`, not the retired `llama-3.3-70b-versatile`).

## Free-tier matrix

### Recurring free tiers (reset monthly)

| Provider | Steady tokens/mo | Rate limits | Models | Reset | ToS |
| -------- | ---------------- | ----------- | ------ | ----- | --- |
| **mistral (deferred)** | — | — | — | — | **deferred 2026-09-25** — free tier restructured to Vibe/Studio only; account shows 0 API credits; every key returns `429` (limit 0 req/min) with auth OK. See TL;DR. |
| **nara (registered)** | ~210M (one 7M/day bucket projected ×30) | — | 8 (NaraRouter lineup) | **daily** (07:00 WIB = 00:00 UTC) | caution |
| **llm7** | ~150M | 40 RPM, 200 req/hr (raised from 20/100) | 4 | monthly | caution — token now required |
| **xkiro** | ~150M | 20 RPM, ~1,000 RPD | 39 (DeepSeek V4 Pro/V3.2, Qwen3.7 Plus, Codestral/Devstral/Ministral 3) | **daily** | caution — forbids "OpenClaw-like" harnesses; hard stop guaranteed |
| **cloudflare-ai (registered)** | ~30M (+ budget lists ~122M) | 10,000 Neurons/day (≈366K output tokens/day on `@cf/openai/gpt-oss-20b`) | 9+ (Llama, GLM, Gemma, Nemotron hosted) | daily (neuron units) | caution — no-VPN clause |
| **groq (registered)** | ~30M | see below | 5 free | **daily** | caution — no resale |
| **api-airforce** | ~24M | 1 RPM, 1,000 RPD | 7 | monthly | caution — no competing services |
| **bluesminds** | ~7M | 20 RPM, 300 RPD | 22 | daily | ambiguous |
| **arcee-ai** | ~5M | via OpenRouter | 1 (Trinity Large Thinking, 262K ctx) | via OR | caution |
| **bazaarlink** | ~4M | 10–20 RPM, ~150 RPD | 32 | daily | caution — no key resale |
| **openrouter (registered)** | ~1M (50/day) | 20 RPM; 50 req/day → 1,000/day after $10 lifetime credits | 1 baseline + any `:free` variant (25+ models / 4 upstream providers) | **daily** (UTC midnight) | caution |
| **cohere** | ~800K | 20 RPM | 6 trial models, 1M ctx | monthly | caution — trial keys not for production |
| **huggingchat** | ~500K | hard $0.10/mo credit | 4 | monthly | caution |
| **morph** | ~400K | — | 2 | monthly | ok |
| **huggingface** | ~200K | hard $0.10/mo credit | 6 | monthly | caution |
| **kiro** | ~25K | — | 12 | monthly | **avoid** |

### Recurring free tiers (reset daily / per-request)

| Provider | Rate limits | Models | Reset | Notes |
| -------- | ----------- | ------ | ----- | ----- |
| **groq** | per model: `gpt-oss-120b`/`gpt-oss-20b`, `qwen3.6-27b`, `qwen3.8-27b` → 30 RPM, 1K RPD, 8K TPM, 200K TPD; `groq/compound`, `compound-mini` → 30 RPM, 250 RPD, 70K TPM | 8–10 free | **daily** | No card; org-level limits; cached tokens free |
| **gemini (registered)** | per model, e.g. `gemini-3.1-flash-lite` 15 RPM / 500 RPD / 250K TPM; `gemini-2.5-flash` 5 RPD / 250K TPM; `gemma-4-26b-it`/`gemma-4-31b-it` 16K RPM / 14.4K RPD / 16K TPM | 4+ | **daily** | No per-model monthly cap published since 2025-12 → uncapped-monthly |
| **nara (registered)** | daily token quota per model class (per-tier 429s, other classes keep working) | 58 served (verified via `/v1/models` 2026-09-25); free: nemotron-3.5-lightning-free, space-bunny-alpha-bynara, mimo-2.6-flash-free | **daily** (07:00 WIB = 00:00 UTC) | OpenAI-compatible `https://router.bynara.id/v1`; fair-use caps |

### Permanently free but uncapped / rate-limited only (no published token cap)

Real recurring free access; **never sum into a monthly budget** (`recurring-uncapped`).

| Provider | Free tier shape | Notes |
| -------- | --------------- | ----- |
| **gemini (registered)** | per-model daily/min limits, no monthly cap | large general lineup |
| **siliconflow** | permanently free `$0` models (Qwen3-8B, etc.) | rate/concurrency limited; $1 one-time credit; real-name gated |
| **glm-cn** | permanently free GLM models | ~20M first-month credit; real-name gated |
| **tencent** | Hunyuan-lite permanently free since May 2024 | real-name gated; sublicense prohibited |
| **baidu** | ERNIE Speed/Lite/Tiny permanently free | real-name gated |
| **kilo-gateway** | permanently free | 7 models |
| **ollama-cloud** | light **weekly** GPU-time free tier (new) | launched cloud inference w/ free tier; ambiguous ToS |
| **sparkdesk** | Spark Lite permanently free | 2 QPS per App ID; personal non-commercial |

### Contested / withdrawn

| Provider | Status | Detail |
| -------- | ------ | ------ |
| **cerebras** | withdrawn | 1M tokens/day no-card trial gone; now one-time **$5** credit, card required, 30-day. Not recurring. |
| **together** | changed | $25 signup credit removed; **$5 minimum purchase** now; ~80 permanently free models remain. |
| **nvidia** | changed | free dev tier keyless, 40 RPM, 70+ models; evaluation-only; one-time credit pool removed. |
| **deepinfra** | changed | free signup credit removed; card/prepayment now required. |

### One-time signup credit (does not recur)

| Provider | Credit | Validity | Notes |
| -------- | ------ | -------- | ----- |
| **vertex** | ~300M tokens | trial | caution |
| **agentrouter** | ~200M ($100) | — | referral may claim $200 |
| **predibase** | ~25M ($25) | 30-day | also 20K tokens/day serverless cap |
| **doubao** | ~15M + recurring 2M tokens/day free models | — | real-name |
| **ai21** | 10M ($10) | **7 days** (was 3 months) | **avoid** |
| **deepseek** | 5M | 30-day | cheap PAYG afterward ($0.28/M) |
| **hyperbolic** | ~5M ($1) | — | GPU rental needs $5 min deposit |
| **deepinfra** | ~1M | — | card now required |
| **fireworks** | ~1M | — | **avoid** (no-proxy ToS) |
| **novita** | ~500K | — | caution |
| **baichuan** | 80 CNY | 3 months | notice |

### Keyless (no API key)

`uncloseai` (free forever, IP throttling), `pollinations` (31 models, ~1 req/6–15s), `publicai`
(20 RPM), `opencode-zen` (⚠️ **403 unless OpenCode client contract** — `stream:true` + session
headers), `duckduckgo-web` (**avoid**), `t3-web` (**avoid**), `friendliai` (**avoid**), `blackbox`
(**avoid**), `coze` (**avoid**). Most others flagged `avoid` in `freeTierCatalog.ts` prohibit
proxy/automation use — not for an automated router.

## Reset cadence cheat sheet

| Cadence | Providers |
| ------- | --------- |
| **Daily** | gemini, groq, openrouter, nara, xkiro, cloudflare-ai, bazaarlink, bluesminds |
| **Monthly** | llm7, cohere, huggingchat, huggingface, morph, kiro, api-airforce |
| **Weekly** | ollama-cloud |
| **One-time** | vertex, agentrouter, predibase, ai21, deepseek, hyperbolic, deepinfra, novita, doubao (first-month) |
| **Uncapped (rate-limited only)** | siliconflow, glm-cn, tencent, baidu, kilo-gateway, gemini (month), ollama-cloud |

## Deferred providers

Providers evaluated and intentionally not wired into routing, with the reason and the exact
condition that would change the decision.

| Provider | Status | Reason / evidence | Revisit when |
| -------- | ------ | ----------------- | ------------ |
| **mistral** | **deferred** | Free plan restructured (2026-09): free tier now = limited Vibe + Studio access only; API usage runs off credits sold separately. Verified 2026-09-25: Billing shows **0 credits**; key auth OK (`GET /v1/models` 200, 46 models) but every `/chat/completions` returns `429` `rate_limited` (code 1300) with `x-ratelimit-limit-req-minute: 0`. Removed from registry + live-test chain 2026-09-25. | Account has a positive credit balance or a paid workspace with API quota. |
| **sambanova** | ⚠️ verify | Reported `402 PAYMENT_METHOD_REQUIRED` (2026-08-31); OmniRoute catalog still lists recurring ~6M/mo. Not added pending a clean key test. | A valid key completes a live `/chat/completions` call. |
| **github models** | retired | Fully shut down 2026-07-30 (playground, catalog, inference, BYOK). Endpoint dead. | Never — dead service. |

## Verification status

| Provider | Verified | Source |
| -------- | -------- | ------ |
| mistral | **deferred 2026-09-25** | console.mistral.ai → Billing shows **0 credits**; key auth OK (`GET /v1/models` 200, 46 models) but every inference `429` with `x-ratelimit-limit-req-minute: 0`. Free plan (mistral.ai/pricing) now covers Vibe/Studio only — API credits sold separately. |
| groq | 2026-08-09 / 2026-09-25 | console.groq.com/docs/rate-limits |
| gemini | 2026-09-02 | `open-sse/config/geminiRateLimits.json` |
| openrouter | 2026-06-05 / web 2026-09-25 | docs.api_reference/limits; FreeModelDailyRequests SDK |
| nara | 2026-09-25 | router.bynara.id/docs + pricing |
| cloudflare-ai | 2026-09-25 | developers.cloudflare.com/workers-ai/platform/pricing |
| cerebras/together/deepinfra | 2026-09-03 | live pricing pages per OmniRoute re-audit |

Sources: OmniRoute `vendor/OmniRoute/docs/reference/FREE_TIERS.md` (v3.8.50, 2026-09-03),
`freeModelCatalog.ts` / `freeModelCatalog.data.ts` / `freeTierCatalog.ts` / `geminiRateLimits.json`,
console.groq.com/docs/rate-limits (2026-08-09), docs.github.com GitHub Models prototyping docs,
router.bynara.id/docs, developers.cloudflare.com/workers-ai/platform/pricing,
openrouter.ai/docs/api_reference/limits. Free tiers move without warning — treat every figure as
a snapshot, not a contract.
