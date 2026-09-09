# MCP Engine — Schema

No tables owned. This component exposes MCP tools that call Backend API endpoints.

---

## No SQL Models

```
MCP engine uses tool definitions, not SQLAlchemy models.
Each tool maps to a Backend API endpoint:

tools:
  upload_resume(file_path)
    → POST /api/profiles/upload
    → returns { profile_id, sections_extracted }

  search_jobs(query?, status?)
    → GET /api/jobs?status=discovered
    → returns Job[]

  analyze_match(job_id)
    → POST /api/profiles/{id}/analyze
    → returns { score, strengths[], weaknesses[] }

  get_package(application_id)
    → GET /api/applications/{id}
    → returns { pdf_url, cover_letter, field_mappings }

  list_providers()
    → GET /api/llm/providers
    → returns LLMProvider[]

  get_checkpoint()
    → GET /api/checkpoints/pending
    → returns Checkpoint[]

  resume_pipeline(checkpoint_id)
    → POST /api/checkpoints/{id}/resume
    → returns { status, next_step }
```

---

## No SQL Migrations

```
MCP engine does not create tables — it reads/writes via Backend API
```
