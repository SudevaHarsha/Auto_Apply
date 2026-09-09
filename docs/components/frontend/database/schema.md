# Frontend — Schema

No tables owned. This component renders data from the Backend API.

---

## No SQL Models

```
Frontend uses TypeScript interfaces, not SQLAlchemy models:

interface User { id: string; email: string; name: string; }
interface Profile { id: string; json_resume: JsonResume; }
interface Job { id: string; title: string; company: string; score: number; }
interface Application { id: string; job_id: string; status: string; }
// ... all 20 tables mapped to TS interfaces
```

---

## No SQL Migrations

```
Frontend does not create tables — it reads from Backend API
```
