# Rubric Generation — Token Cost Analysis

Status: **investigation notes** (unimplemented, unmeasured — estimates, not facts).
Accompanying doc: `rubric_generator.md`. Live-test context recorded week of 2026-09-22.

---

## 1. Measured baseline (live run, `rubric_generation` step)

| Provider      | prompt tokens | completion tokens | total  | status |
|---------------|---------------:|------------------:|-------:|--------|
| groq          | ~2,173         | ~5,873            | ~8,046 | 429 rate_limited |
| groq (retry)  | ~2,173         | ~5,843            | ~8,016 | 429 rate_limited |
| openrouter    | —              | —                 | —      | 402 insufficient_credits (billing, not tokens) |
| gemini        | —              | —                 | ~9.8k  | 429 (free-tier generation quota) |

Key structural fact: groq free tier = **8,000 tokens/min (TPM)**. A single rubric
generation call runs ~8.0k total, so it alone consumes the entire window — every
subsequent call in the same minute 429s. This is what blocks the live test
`test_live_second_score_hits_rubric_cache` (fresh score + cache-hit re-score).
The blocker is a **quota + completion-size problem combined**, not a code fault.

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

### 4.3 Cap `max_tokens` lower
- `openai_compatible.py:74` sets `max_tokens=16384` — effectively no ceiling
  pressure. A cap like **4000** forces compaction. Validation is the guard.
  Small change, immediate, but a truncation edge case must be handled.

### 4.4 Route generation to a high-quota provider
- 8k TPM groq is too small for an ~8k call. Route `rubric_generation` to gemini
  (larger free window; scored 64/100 fine in live test 1), keep groq for the
  small eval. Pure config change — fixes the actual 429 blocker, not just raw cost.
- `openrouter` was 402 insufficient_credits on 2026-09-22; the standing config
  is `qwen/qwen3.8-27b:free` (`registry.py:39`), which now returns **429
  temporarily rate-limited upstream** (ModelRun/Google shared pool — auth passes,
  key valid, quota exhausted). Both `qwen/qwen3.8-27b:free` and
  `google/gemma-4-26b-a4b-it:free` are 429 upstream; free-tier models still need
  a prepaid OpenRouter balance once rate limit clears.

### 4.5 Trim the JD payload sent to the model
- `jd_input()` (`rubric_generator.py:98`) sends the full corpus because the gate
  needs tokens locally. The LLM only needs high-signal fields (skills,
  responsibilities, schedule/location/visa). Compact the JSON for the request;
  keep full payload on the server for `validate_partition`.

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
