# Chrome Extension — Database Scope

Owns evidence storage (screenshots, PDFs, DOM snapshots).

---

## Tables Owned

```
TABLE      PURPOSE                              WRITES
────────────────────────────────────────────────────────
evidence   Screenshots, PDFs, DOM snapshots      INSERT
```

---

## Tables Read

```
TABLE             READ BY              WHY
────────────────────────────────────────────────────
applications      chrome_extension     links evidence to application
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE             WRITER               WHY
────────────────────────────────────────────────────
audit_logs        chrome_extension     logs evidence capture events (INSERT)
```

---

## Data Flow

```
FORM FILLED:
  chrome_extension → POST /api/evidence (type=screenshot, file_url)
  Backend API → evidence (INSERT)

SUBMIT CONFIRMED:
  chrome_extension → POST /api/evidence (type=screenshot, file_url)
  chrome_extension → POST /api/evidence (type=pdf, file_url)
  Backend API → evidence (INSERT)

DOM CAPTURE:
  chrome_extension → POST /api/evidence (type=dom_snapshot, metadata=field_values)
  Backend API → evidence (INSERT)

VIEW EVIDENCE:
  chrome_extension → GET /api/applications/{id} (includes evidence)
  Backend API → evidence (SELECT WHERE application_id = $1)
```

---

## Relationships

```
users (1) ──────< (N) evidence
applications (1) ──< (N) evidence
```
