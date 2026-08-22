# DECIDAI Architecture

```text
React Frontend
      ↓
FastAPI Backend
      ↓
Document Extraction
      ↓
Gemini Analysis
      ↓
Structured Pydantic Validation
      ↓
Supabase PostgreSQL
      ↓
Human Final Decision
      ↓
Audit Trail
```

- **React frontend** collects case details, presents explainable AI output, and keeps human controls prominent.
- **FastAPI** keeps all Gemini and Supabase credentials server-side and exposes the application API.
- **Document extraction** reads submitted PDF, DOCX, and TXT evidence.
- **Gemini analysis** provides an advisory recommendation grounded in submitted information.
- **Pydantic validation** ensures the AI output follows DECIDAI's structured response schema.
- **Supabase PostgreSQL** stores cases, AI analyses, final human decisions, and audit events.
- **Human final decision** is explicitly entered by a reviewer; it is never generated automatically.
- **Audit trail** records case creation, AI analysis, human decisions, and overrides.
