# Backend API — Schema

No tables owned. This component uses SQLAlchemy models that map to tables owned by other components.

---

## SQLAlchemy Model Mapping

```python
# Models are defined here but map to tables owned by other components

from sqlalchemy import Column, String, Integer, JSON, ForeignKey, DateTime, Boolean, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import relationship

class User(Base):
    __tablename__ = "users"  # owned by auth
    id = Column(UUID, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    ...

class Profile(Base):
    __tablename__ = "profiles"  # owned by core_engine
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"))
    ...

class Job(Base):
    __tablename__ = "jobs"  # owned by core_engine
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"))
    ...

# ... all 20 tables mapped
```

---

## No SQL Migrations

```
Backend API does not create tables — it uses tables created by:
  auth → users, api_keys, settings, user_profiles
  core_engine → profiles, jobs, applications, pipeline_runs, job_snapshots
  discovery → telegram_connections, telegram_messages
  discord → discord_connections, discord_messages
  llm_router → llm_providers, provider_usage, rate_limit_state
  checkpointing → checkpoints
  observability → audit_logs, error_logs
  chrome_extension → evidence
```
