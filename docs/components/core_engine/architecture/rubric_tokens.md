# Rubric Generation — Token Cost Analysis

Status: **implemented + verified** (token-cost levers 4.1/4.2/4.3 landed and green;
live measurements recorded 2026-09-22 →  09-24).
Accompanying doc: `rubric_generator.md`. Live-test context recorded week of 2026-09-22.

---

## 1. Measured baseline (live run, `rubric_generation` step)

| Provider      | prompt tokens | completion tokens | total  | status |
|---------------|---------------:|------------------:|-------:|--------|
| groq          | ~2,173         | ~5,873            | ~8,046 | 429 rate_limited |
| groq (retry)  | ~2,173         | ~5,843            | ~8,016 | 429 rate_limited |
| openrouter    | —              | —                 | —      | 402 insufficient_credits (billing, not tokens) |
| gemini        | —              | —                 | ~9.8k  | 429 (free-tier generation quota) |

Key structural fact: groq free tier = **8,000 tokens/min (TPM)**. The original
4.3 baseline treated a rubric call as ~8.0k total (completion ~5.8k), so it was
thought to consume the entire window — that belief drove the live-test blocker
`test_live_second_score_hits_rubric_cache` and the (wrong) routing conclusion below.

**CORRECTED 2026-09-25 (4.4 budget-math fix):** the 4.3 gate added `max_output_tokens`
(6000) to the full input, overstating every call by the whole safety cap. The D2c
budget now uses the *realistic per-step output* instead: rubric 1,747 + 3,300 =
5,047 and eval 2,105 + 4,500 = 6,605 both fit groq's 8,000 window. groq serves
both steps; no routing change is required (see §4.4 below). The one residual edge:
a worst-case eval whose output runs to the 6,000 cap = 2,105 + 6,000 = 8,105 >
8,000 → single-full-length eval 429s → gemini absorbs it (deferred, deep-dive
after 4.5).

Completion (~5.8k) is ~2.7× the prompt (~2.1k). **Completion is the cost driver.**

---

## 2. What drives the token count

### Input side (~2.1k)
- `rubric_generator_prompt.jinja` embeds the **entire structured JD payload**
  verbatim (`jd_json`, line 9) by design (S7-v2 B1 — the gate needs the full corpus
  to verify grounding).
- Plus a verbose example JSON skeleton (~800 tokens of schema prose) and long
  STEP 1 / STEP 2 / Guidelines instruction blocks.

### Completion side (~5.8k)
Generated JSON contains, for 3–5 categories × 2–5 anchors:
- `categories[].jd_sources` — literal JD sentences, echoed verbatim
- `categories[].requirement_text` — exact required-skill wording (near-duplicate of `jd_sources`)
- `categories[].anchors[].band` — model-written band labels
- `derivation.scoreable` — **every** required skill + responsibility, echoed verbatim (largest single chunk)
- `derivation.eligibility` — schedule/shift/location/visa wording, echoed verbatim
- `derivation.removed` — field/role/reason triples
- JSON key/syntax repetition, `icon` (constant "•", negligible <15 tokens)

**Rough composition of the ~5.8k completion:**

| Component                              | approx tokens |
|----------------------------------------|--------------:|
| derivation.scoreable (verbatim echo)   | ~1.5–2.5k     |
| jd_sources + requirement_text per cat  | ~1–2k         |
| eligibility (verbatim)                 | ~200–500      |
| anchors / band labels                  | ~400–800      |
| icon                                   | <15           |
| JSON syntax repetition                 | ~50–150       |

Conclusion: completion is dominated by **verbatim JD echo, duplicated across
fields** — not by model-written content.

---

## 3. What `jd_sources` and `requirement_text` are FOR

Both fields describe **where each category's scoring criterion came from in the
JD**. They are the audit trail the S7-v2 partition gate uses to prove the rubric
is grounded in the real posting rather than hallucinated.

- `jd_sources`: literal strings copied verbatim from the JD payload.
  - Consumed ONLY by the grounding gate (`validate_partition`,
    `rubric_generator.py:467-474`): every entry must be a literal string present
    in the JD payload.
  - Confirmed: **never rendered into any prompt** (grep of `templates/*.jinja`
    finds no eval-mode usage). Exists purely for server-side validation.
- `requirement_text`: the exact required-skill/responsibility wording the
  category scores.
  - Consumed by the coverage gate (`rubric_generator.py:495`) AND
  - Rendered into the eval prompt — `rubric_generator_prompt.jinja:87`
    ("JD requirement this category scores: ...") — so the scorer can tie the
    category to the real requirement.

Takeaway: `jd_sources` and `requirement_text` are **near-duplicates of each other**.
`requirement_text` has a real scoring purpose; `jd_sources` is validation-only.

---

## 4. Ranked alternatives to reduce token cost

### 4.1 Eliminate the verbatim duplication — REAL win (large, honest lever)

Three independent changes. The big one is the **pointer wire format** for
`jd_sources` (4.1-b), decided on 2026-09-23. It REPLACES the earlier "dedupe the
JD echo across categories" idea entirely — pointers cannot be paraphrased and
cannot be duplicated, so it also removes the most failure-prone prompt rule.

#### 4.1-a Drop `requirement_text` from the generated rubric
- It is a literal near-duplicate of `jd_sources` (same JD wording), and the gate
  only validates `jd_sources` literally (`rubric_generator.py:467-474`).
- Keep the field optional (`default=""`) in `RubricSchema` / `PersistedRubric`
  (shared `RubricFacet`) so old cached envelopes still parse — B4 back-compat.
- Coverage token union (`rubric_generator.py:495,500`) already includes
  `jd_sources` + `scoreable`, so dropping it cannot flip a verdict.
- Eval render (`rubric_generator_prompt.jinja:86-88`, currently the ONLY
  grounding line the scorer sees):
  `{% if cat.jd_sources %}- JD requirement this category scores: {{ cat.jd_sources | first }}{% endif %}`
  → resolves to the literal string server-side before rendering.
- Honest math: ~10-20 tokens × 3-5 categories ≈ 30-100 tokens/completion (earlier
  ~1k claim was inflated).

#### 4.1-b `jd_sources` pointer wire format (NEW, decided) — the real win
Wire output uses compact references instead of full-sentence echo:

```
"jd_sources": ["skills[2]", "responsibilities[0]", "schedule[1]"]
```

Rules (non-negotiable):
1. **Resolve server-side at `_coerce_rubric` time.** The gate below never sees
   pointers. `loads → resolve_pointer(jd_payload, "skills[2]") → literal string`,
   THEN `RubricSchema.model_validate` + `validate_partition` run on the resolved
   literal — unchanged code paths. Pointer unresolvable → `RubricGenerationFailedError`,
   same malformed-output path as today.
2. **Resolution grammar**: `key[i]` where `key` is a top-level payload field and
   `i` a list index; dot-chained for nested dicts (`derivation.scoreable[0]`).
   Resolves to the string value; used verbatim.
3. **Number the arrays in the prompt**, or you trade one failure mode for another:
   LLMs are bad at positional counting. Render payload arrays WITH visible indices
   in the generation prompt (`[0] Python, [1] PostgreSQL, [2] Docker ...`) so the
   model copies an index instead of counting. Without this, `skills[2]` off-by-one
   silently grounds the WRONG requirement.
4. **Optional soft consistency lint** in `_anchor_lint`: resolved pointer tokens
   must share ≥1 token with the category's own anchors/bands/scoreable — catches
   wrong-index grounding without hard-rejecting. Soft-only (never triggers repair).
5. **Back-compat / hybrid**: `jd_sources` may contain EITHER a pointer or a
   literal; literals pass through unchanged. Old cached rubrics (and
   `tests/integration/test_scoring.py` mocks, e.g. L88/101/114 and L708's literal
   append) keep working with zero changes.
6. **Persistence unchanged**: `persist_envelope` stores the resolved literal
   string; `rubric_sha256` hashes the resolved envelope. Pointers exist only on
   the wire.
7. **Prompt changes**: `rubric_generator_prompt.jinja` example (L27) shows the
   pointer form; STEP 2 instruction (L57-58) changes from "copied verbatim, no
   paraphrasing" to "must be `key[i]` pointers from the INDEXED reference below;
   never retype text".

Honest math (this is the real large lever, NOT the inflated ~1k):
- `jd_sources` literal echo today ~1-2k tokens of completion (real JDs → full
  sentences / clauses × many entries). Pointers collapse that to ~6-12 tokens
  even with 3+ entries per category.
- PLUS reliability: paraphrase-failure hard-rejects today trigger an ~8k repair
  call; pointers eliminate that whole failure class. One avoided repair ≈ one
  avoided 8k call — may matter MORE than the raw completion cut.
- Prompt side grows slightly (indexed reference block, +100-200 tokens) — the
  only cost.

#### 4.1-c Keep `derivation.scoreable` name-only
- Hard gate only checks non-empty (`rubric_generator.py:451-452`); coverage check
  matches normalized token overlap (`rubric_generator.py:509-525`) with the full
  phrase living in `jd_sources`, so name-only entries pass.
- Template STEP 1: "scoreable may list each signal as a short name; the full
  phrase must appear in that category's `jd_sources`."
- Honest math: full-sentence echo ~0.5-1.5k → name-only ~150-300.

**Combined estimate (UNMEASURED):** completion ~5.8k → ~3.5-4.5k; prompt ~2.1k →
~2.2-2.3k (indexed reference block). Verify with §6 tokenization before trusting.

**STATUS: IMPLEMENTED 2026-09-23.** Changes landed + green:
- `rubric_generator.py`: `_render_indexed_jd()` builds the single JOB POSTING listing
  (arrays `key[i]` + scalars `key: value`); `_resolve_pointer()`
  (regex `key[.sub][i]`) resolves during `_coerce_rubric` (now takes `jd`); unresolved
  pointer → `RubricGenerationFailedError`; `_anchor_lint` soft check that resolved
  `jd_sources` shares content words with the JD corpus; `jd_input` carries `jd_body`
  + `jd_index`. `_POINTER_RE` corrected once (dot-chain was captured into a separate
  group → `skills.required[1]` never resolved).
- Templates: generate branch renders the single `JOB POSTING` listing + pointer
  instructions;
  example `jd_sources` shows pointer form; `requirement_text` line + STEP 1/2 wording
  updated; eval branch renders `jd_sources | first`. System template drops
  "exact requirement_text".
- `schemas.py`: `jd_sources`/`requirement_text` docstrings reflect wire + legacy roles.
- Tests (added, all green): pointer-resolves-and-gate-verdict-unchanged,
  unresolvable-pointer-raises-and-rolls-back, hybrid literal+pointer mix.
  Suite: `test_scoring.py` 25 passed + `test_scoring_guards.py` 10 passed (35 total).

**FIX B 2026-09-25 (spaced/dotted `jd_sources` pointers).** 4.1 rendered the
indexed listing verbatim, so a JD key containing a space/apostrophe produced a
pointer line like `other.What You'll Do[0]`. `_POINTER_RE` only matched
`[A-Za-z_]`-chained identifiers, so such a line failed `_looks_like_pointer`,
fell through as a *literal*, and leaked the raw pointer placeholder into
`jd_sources` (the grounding gate then passed it because the words do occur in
the JD). Providers differ: gemini happened to emit literals; groq emitted the
verbatim spaced pointers. Fix: `_POINTER_RE` is now `^([^\[]+?)\[(\d+)\]$` so
spaced/apostrophed segments are classified as pointers; resolution still splits
on `.` with exact body-key match, so unresolved pointers keep failing-loud
(`RubricGenerationFailedError`). Tests: `tests/units/test_pointer_resolution.py`
(8) + `tests/integration/test_scoring.py::test_rubric_spaced_dotted_pointer_resolves_not_leaks`
(no raw pointer in the persisted envelope, gate still clean, 2 calls).

**POST-4.1 CLEANUP 2026-09-24 (C1): removed `requirement_text` from the schema.**
It was already dead in the forward path (no template, evaluator, or prompt
references it; new rubrics emitted `""`). Dropping it everywhere:
- `schemas.py`: field removed from `RubricFacet`; `PersistedRubric` parses legacy
  envelopes fine because pydantic defaults to `extra='ignore'` (the D58 envelope
  also bakes rendered `criteria`/`system_message`, so cache-hit rebuild needs none
  of it).
- `role.py`: `Category.requirement_text` default removed (builders never set it).
- `rubric_generator.py`: `persist_envelope`/`build_role_definition`/
  `rebuild_role_definition` copy-points dropped; lint no longer tokenizes it.
- Tests: fixtures cleaned; `# 4.1-a: no requirement_text anywhere` assert kept.
  Suite re-run green (35 total).

**POST-4.1 CLEANUP 2026-09-24 (C2): single indexed JOB POSTING replaces jd_json + index pair.**
The 4.1-b prompt rendered `jd_json` (full JSON, pre-4.1 baseline) AND a separate
`INDEXED REFERENCE` re-listing every array string — ~2.2-2.5k extra prompt chars
(+~700 tokens on the live JD; JOB POSTING appears twice). Fixed by merging into ONE
listing: `_render_indexed_jd` emits every array string as `key[i] value` AND every
scalar (title/location/remote_policy/sponsorship/salary) as `key: value`, so the
partition step still sees everything and the duplication is gone. Template renders
`{{ jd_index or jd_json }}`; fallback updated alike; system template wording updated.
Measured on `tests/live/chain/jd_1.json`: old pair = 2,646 (json) + 2,738 (index)
= 5,384 chars; new single listing = 3,133 chars (scalars included) — a 2,251-char
cut. Tests updated (pointer asserts + `JOB POSTING` header, `skills.required[0]`
presence); suite green (35 total).

### 4.2 Curb output verbosity (moderate, ~15–25%) — IMPLEMENTED 2026-09-26
- **4.2a band cap:** anchor rule now reads "each band ≤ 8 words in total,
  includes a signal from THIS JD, and describes observable resume evidence;
  min_points strictly ascend from 0; top band equals category max". The JD-term
  requirement keeps the `_anchor_lint` grounding overlap intact (terse generic
  bands would hit the generic-ladder soft hit and cost a repair); "top band
  equals category max" removes the un-anchored score zone (top < max) and forces
  weight↔ladder coherence. Mirrored in the system template.
- **4.2b prose trim:** generate-prompt bridge condensed to `Rules:`; eligibility
  examples shortened; the fairness bullet deleted from the prompt (already
  present, unchanged, in the system template). Frees ~150-225 prompt tokens.
- **4.2c weight by JD emphasis:** Guidelines now require assigning each
  category's max by the JD's relative emphasis — core responsibilities and
  explicitly-required skills outrank secondary signals, explicitly **never from
  generic industry expectations** (occupational stereotypes). Skeleton example
  now shows a `max: 30` / 0-15-30 category to teach non-uniform weights.
  Bonus: distinct maxes → distinct anchor grids → fewer copy-pasted-grid lint
  hits → fewer repairs. No Python change; weights were already honored by the
  scorer (eval renders `0-{{ cat.max }}`).
- Prompt rules are prompt-soft on purpose: `validate_partition` still accepts
  `top < max` and any weight spread (legacy cache back-compat + grading freedom).
  Downside accepted: distinct maxes mean `_shared_anchor_bands` rarely fires, so
  eval renders ladders inline — bounded by the 8-word cap.
- Tests: integration asserts band/weight rule strings + skeleton `"max": 30`;
  guard pins the same rules and proves distinct maxes (35/20/5) reach the eval
  criteria. Suite green.

### 4.3 JD-aware output cap = `max(6000, math)` — IMPLEMENTED 2026-09-24
Previously `openai_compatible.py:74` hardcoded `max_tokens=16384` (no ceiling
pressure at all). It's removed. The cap is now computed per call, floor of 6000,
and the math can only ever RAISE it — never lower it below the base. Implemented
end-to-end in 4.3 (D1-D4):

- **D2 estimator** — `backend/app/llm/limits.py`:
  - rubric: `cap = max(6000, echo_pool + 150 + allowance_rubric)` where
    `echo_pool` = tiktoken count of **every responsibility + every required
    skill** (the responsibilities driver: more responsibilities -> larger pool ->
    higher cap) and `allowance_rubric = 3500` (`LLM_RUBRIC_ALLOWANCE`).
  - eval: `cap = max(6000, 400 + allowance_eval + resume_tokens // 4)` with
    `allowance_eval = 5000` (`LLM_EVAL_ALLOWANCE`) — a long resume grows the
    completion budget, since eval echoes resume evidence.
  - env overrides (`LLM_MAX_OUTPUT_TOKENS_RUBRIC`/`_EVAL`) only raise further.
- **D2a exact input count** — the actually-rendered prompt + system message are
  token-counted via tiktoken cl100k_base before routing (char/4 is only the
  no-tiktoken fallback). Live pins: rubric rendered prompt 1,747; eval rendered
  prompt 2,105 (provider-tokenizer counts run ~40% higher, e.g. 2,421/2,310, and
  are NOT what the router budgets on; earlier notes wrongly used them —
  see the 4.4 correction).
- **D2c budget gating in `route_llm_request`/`generate_structured`** —
  `budget_expected = prompt_tokens + predicted_output(step)` is checked against
  each provider's declared `tpm` (`ProviderSpec.tpm`, registry; groq = 8000
  documented). A provider that cannot fit the expected call in its minute window
  is `budget_skip`-ped BEFORE any call — no usage row, no breaker trip, recorded
  in `attempts`. All under-cap -> `ProvidersExhaustedError` (fail-soft).
  `predicted_output` is the *realistic* per-step completion (rubric 3300 / eval
  4500, env-tunable), deliberately NOT the 6000 wire cap: 6000 is a safe output
  ceiling, so adding it to the full input overstates the real call. Ground truth
  (jd_1): rubric 1,747 + 3,300 = 5,047 < 8k → groq fits; eval 2,105 + 4,500 =
  6,605 < 8k → groq fits. Both steps stay on groq — no routing change (this is
  the 4.4 finding, see below).
- **D1/D3 adapter caps + truncation detection** — every adapter carries the
  computed cap on the wire (`max_tokens` openai-compatible / `maxOutputTokens`
  gemini / `num_predict` ollama, only when the caller passes one) and flags
  truncation honestly instead of guessing: `finish_reason == "length"` or
  `usage.completion_tokens >= max_output_tokens`, `finishReason == "MAX_TOKENS"`,
  `done_reason == "length"`. `ChatResponse.truncated` + `LLMResponse.truncated`
  flow back to the consumer.
- **D4 consumer honesty (no silent repair)** — `generate_rubric` /
  `evaluate_resume` check `response.truncated` BEFORE any JSON coercion and raise
  `RubricGenerationFailedError` / `ScoringFailedError` with
  `error_type="output_truncated"`, `can_continue=True`, the applied cap, the
  completion count, and a `content_prefix` — so the interactive lane can
  park-and-ask (Continue/Shorten/Fail against a `checkpoints` row) and batch
  lanes fail fast. Truncated output NEVER reaches `_repair_truncated`
  (`output_truncated` block precedes every `_coerce_rubric`/parse call).

Per-call effect (jd_1): rubric cap stays at the 6000 base (the small JD's
calculation ~3,724 < base); a synthetic 2,500-token responsibility pool raises
it to 6,150. Eval cap is 6000 for common resumes and grows with long ones.

### 4.4 Route on realistic output, not the worst-case cap
- **Correction (2026-09-25):** the earlier plan — "8k TPM groq is too small for an
  ~8k call, route rubric generation to gemini, keep groq for the small eval" — was
  built on budget math that added the **6000 safety ceiling to the full input**
  (rubric 2,421+6,000=8,421; eval 2,310+6,000=6,828 miscounted). That overstates
  every call by the whole cap. With the D2c budget fixed to use the *realistic
  per-step output*, both calls fit groq (rubric 5,047 / eval 6,605 < 8,000), so
  **no routing change is required**: groq serves both steps, gemini stays the
  failover, not the primary. (This replaces the pre-4.4 "route to gemini"
  requirement.) Verified against groq's published `gpt-oss-20b` free-tier limits
  (`console.groq.com/docs/rate-limits`): 8k TPM / 30 RPM / 1k RPD / 200k TPD.
- **TPM gating is generic, not groq-specific** — the budget check runs per
  provider at its turn in the chain (`router.py:300-301`); only registry entries
  declaring `tpm` are gated (groq=8000 today; gemini/openrouter unmetered). Adding
  a future provider with a `tpm` gates it automatically.
- **Known residual edge (deferred to the post-4.5 eval deep-dive):** a worst-case
  eval whose output runs to the 6000 cap = 2,105+6,000 = 8,105 > 8,000 — a single
  full-length eval 429s groq, trips its breaker, and gemini absorbs the call.
  Documenting the decision here; behavior to be finalized with the eval work after 4.5.
- `openrouter` was 402 insufficient_credits on 2026-09-22; the standing config
  is `qwen/qwen3.8-27b:free` (`registry.py:39`), which now returns **429
  temporarily rate-limited upstream** (ModelRun/Google shared pool — auth passes,
  key valid, quota exhausted). Both `qwen/qwen3.8-27b:free` and
  `google/gemma-4-26b-a4b-it:free` are 429 upstream; free-tier models still need
  a prepaid OpenRouter balance once rate limit clears.

### 4.5 Trim the JD payload sent to the model
- `jd_input()` (`rubric_generator.py:99`) sends the full corpus because the gate
  needs tokens locally. The LLM only needs high-signal fields. Compact the JSON
  for the request; keep the full payload on the server for `validate_partition`.

**The two consumers (why this is safe at all).** The rubric-generation prompt
(`rubric_generator_prompt.jinja:9`, `{{ jd_index or jd_json }}`) and the gate
consume two *different* outputs of `jd_input()`:

| Consumer | Consumes | Needs |
|---|---|---|
| LLM (generation prompt) | `jd_index` / `jd_json` — the indexed listing | high-signal fields only: required skills, responsibilities, schedule/shift/location/office-policy, sponsorship, degree |
| Gate (`validate_partition`, `rubric_generator.py:467`) | `jd_tokens`, `required_skills`, `responsibilities` | the **full corpus** + exact coverage targets |

`validate_partition` never reads `jd_json`/`jd_index` — grounding matches every
`jd_sources` literal against `jd_tokens` (tokens of the full payload,
`rubric_generator.py:511-512`), and coverage runs over `required_skills` +
`responsibilities` (both derived from the full payload, L483-484). So **trimming
the prompt-side listing cannot weaken the gate**; the gate stays 100% on
server-side full payload. The only prompt-side inputs the gate checks
indirectly are the band/JD wording that flow through `_anchor_lint` (L446-451) —
unchanged.

**Design.** `jd_input()` keeps returning both halves, but `jd_json`/`jd_index`
are rendered from a **compact projection** of the body:
- KEPT (the decision inputs STEP 1 partitions on): `title`, `skills`,
  `responsibilities`, and the eligibility scalars/objects (`location`,
  `remote_policy`, `employment_type`, `work_auth_visa`, `salary`, `education`,
  `experience_range` when present).
- **`other` is NOT a safe wholesale trim (CORRECTED 2026-09-25).** The original
  draft assumed `other` holds only pitch/residual noise — from *one* fixture
  (jd_1), where "What You'll Do" verbatim-duplicates `responsibilities`. The
  second live fixture (jd_2) disproves that: its `other` carries real partition
  inputs that live **nowhere else** —
  - `Weekly Offs` (rotational 2-consecutive-day-off rule) — a unique
    schedule/eligibility constraint;
  - `Role Description` (the "stowing action" activity description) — unique
    anchor vocabulary (`_anchor_lint` grounds band words in the full corpus,
    `rubric_generator.py:446-448`);
  - `Work Environment` (24x7 / 9-hour / night-shift specifics) — largely but
    NOT fully duplicated by `responsibilities[3]` / `skills.required[6]`.
  Coverage targets never include `other` (they are `skills.required` +
  `responsibilities`, L483-484), so missing-`other` never trips coverage — the
  loss would be **silent**: unique eligibility wording would never be recorded
  in `derivation.eligibility` (the only downstream record; the eval prompt
  renders generic eligibility text only, never the JD wording), and unique
  vocabulary would leave the corpus the model can ground bands in.
  - **Correct rule: warn-drop only zero-information `other` strings** — content
    that is verbatim-identical to a kept `responsibilities`/required-skill
    string (pure dedupe, vocabulary-neutral). Keep everything else in `other`.
- TRIMMED (genuinely zero signal): `posted_at`, `_meta` (already excluded).
- Candidate for trimming (needs a review call): `company`, `good_to_have`,
  `screening_question_hints`. They are never coverage targets and carry no
  scoreable signal, but they give the model context for honest
  `derivation.removed` / anchor-language judgments.
- `jd_body`, `jd_tokens`, `required_skills`, `responsibilities` stay
  **full-payload** — `_resolve_pointer`, `validate_partition`, coverage, and
  `_repair_suffix` are byte-for-byte unchanged.

**Measured (2026-09-25, `_render_indexed_jd` walk):**

| Fixture | full listing | `posted_at` + verbatim-dup `other` (safe) | naive `other` drop (REJECTED — loses jd_2 eligibility/vocabulary) |
|---|---|---|---|
| jd_1 | 3,003 chars / 40 lines | ~2,602 (−13%; only `other["What You'll Do"]` is a verbatim dup, 379 chars) | 1,448 (−52%) — safe only because this fixture's `other` is redundant |
| jd_2 | 2,604 chars | ~2,514 (−3.5%; only `other["Hiring Duration"]` is a dup, 70 chars) | 1,390 (−47%) — **breaks**: drops `Weekly Offs` / `Role Description` / `Work Environment`, all unique |

**Honest math (UNMEASURED until §6 tokenization).** Today's measured rubric
rendered prompt is 1,747 tokens (D2a). The *safe* cut is small: best case
(verbose JDs whose `other` heavily duplicates responsibilities) trims
~400-500 chars ≈ −100-150 tokens → rubric expectation ~1,600 + 3,300 ≈ **4,900**
vs today's 5,047 — single-digit headroom, **no routing change** (4.4 already
fits both steps on groq). The 52-63% figures were wrong; do not implement
wholesale `other` trimming.

**Scope honesty.** 4.5 trims only the rubric **generation** call. The **eval**
prompt is resume-driven (`text_content`) + per-category criteria and never
embeds the JD listing — so 4.5 does **not** reduce the §4.4 residual edge
(worst-case eval 8,105 > 8,000). That edge still waits for the post-4.5 eval
deep-dive.

**Deeper fix out of 4.5 scope (noted, not specced):** several `other` keys
(`Weekly Offs`, `Work Environment`, `Role Description`) are partition-relevant
content that door-4 extraction leaves in the residual catch-all. Routing
schedule/`shift`/`office`-class content into real `StructuredJD` fields at
extraction would earn the token cut legitimately. Until then `other` must go to
the model largely in full.

**DEFERRED DECISION (revisit after a 50-100 JD empirical sweep):** which `other`
categories are recurring and partition-relevant enough to promote into real
`StructuredJD` typed fields (candidates: `schedule`/`shift`, `work_environment`
/`office_policy`, `compensation_notes`) — and then which schema fields to make
**mandatory** — should be decided from data, not speculation. Plan: run the
live/extraction suite over ~50-100 real JDs, tally recurring `other` keys vs
typed-field candidates and per-field fill rates, and only then (a) promote the
top candidates to typed fields (bump `CURRENT_SCHEMA_VERSION`), (b) mandate only
fields the sweep shows the model fills reliably, (c) re-verify the 4.5 token trim
on the shrunken `other`. Until that sweep exists, the required-`other` schema
change (presence) is the safe interim; do not add further mandates.

**The one behavioral risk (decision for review).** `_resolve_pointer`
(_coerce_rubric time) resolves pointers against the *full* payload, so a model
emitting a pointer/band referencing a trimmed, unseen field still grounds
server-side. Options:
1. **Soft (recommended):** rely on the existing prompt rule "reference JD text
   ONLY with `key[i]` pointers from the listing above" + `_anchor_lint`/hard
   gate. No new failure class; a hallucinated trimmed-field pointer only
   survives if it is *also* in the corpus; invented sources are caught by
   coverage if they miss a required/listed responsibility.
2. Hard: resolve-and-check-at-coercion that every pointer targets a **kept**
   field; a pointer into a trimmed field → `RubricGenerationFailedError` →
   single repair call (reintroduces the repair-cost class 4.1-b removed).
   Not recommended unless live measurement shows invented pointers.

**Test plan (when approved):**
- Unit `jd_input`: prompt-side drops `posted_at`/`_meta` and verbatim-duplicate
  `other` strings, keeps all novel `other` content; `jd_body`/`jd_tokens` still
  cover the FULL payload.
- Unit (jd_2 lens): a novel `other` value (`Weekly Offs`) stays in the prompt
  listing and remains pointer-resolvable + grounds server-side.
- Integration `test_scoring.py`: jd_1 + jd_2 generations stay 1-call gate-clean
  (no repair); coverage counts identical to pre-4.5.
- Live/chain: render + token-count the compressed prompt on jd_1 and jd_2.
- Regression: legacy cached rubrics unaffected (prompt-only change).

**STATUS: DESIGN 2026-09-25 — corrected after review; pending review; NOT
implemented.**

### Examined and rejected
- Two-phase extract-then-build: adds a call, same total tokens.
- Dropping `jd_sources` verbatim entirely: breaks the D70 grounding gate.

---

## 5. Honesty log / corrections
- An earlier claim of "40–60% off completion via verbosity" was an **estimate,
  not a measurement**, and correctly challenged. Correction: shortening bands
  alone is ~15–25%; dropping `icon` is <1%; the real "large chunk" lever is
  **verbatim-echo duplication**.

## 6. Suggested verification (do before trusting numbers)
- Pull a persisted rubric envelope from `rubric_cache` (e.g., the Stackbinary
  live job, sha `d96c785a...`) and tokenize it field by field to get the true
  composition of the completion tokens.
