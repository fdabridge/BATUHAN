# BATUHAN — Architecture & Tech Stack Decisions

## System Overview
BATUHAN is an internal AI-powered platform for a certification company that automates
ISO audit report creation using a strict 3-step pipeline: A (Evidence Extraction) →
B (Report Generation) → C (Validation & Correction).

---

## Tech Stack

### Backend
| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | pdfplumber/python-docx ecosystem, Anthropic SDK |
| Framework | FastAPI | Async support, automatic OpenAPI docs, Pydantic native |
| AI Provider | Anthropic Claude Sonnet 4.6 Extended | Required by BATUHAN.pdf |
| Task Queue | Celery + Redis | Reliable background job processing, retry support |
| Database | SQLite (dev) → PostgreSQL (prod) | Simple internal tool; upgrade path clear |
| File Storage | Local filesystem (dev) → S3-compatible (prod) | Structured by job ID |
| PDF Parsing | pdfplumber + PyMuPDF | Text extraction from company docs |
| DOCX Parsing | python-docx | Template parsing and final report assembly |
| OCR | Tesseract via pytesseract | Scanned PDFs and images |

### Frontend
| Layer | Choice | Reason |
|---|---|---|
| Framework | Next.js 14 (App Router) | React-based, SSR, file upload support |
| Language | TypeScript | Type safety across UI |
| Styling | Tailwind CSS | Rapid internal UI development |
| HTTP Client | fetch / axios | API calls to FastAPI backend |

### Infrastructure
| Layer | Choice | Reason |
|---|---|---|
| Job Queue Broker | Redis | Required by Celery |
| Secrets | .env + python-dotenv | Never hardcoded |
| Auth | Internal only — simple API key header (Phase 1) | Internal tool |

---

## Pipeline Architecture

```
User Upload (UI)
      │
      ▼
FastAPI /jobs/create
      │  stores files + metadata by job_id
      ▼
Celery Worker picks up job
      │
      ├─► PREPROCESSING
      │     - Text extraction (PDF/DOCX/TXT)
      │     - OCR (PNG/JPG/scanned PDF)
      │     - Template section parsing
      │     - Sample style extraction
      │
      ├─► STEP A  (Prompt A → Claude)
      │     - Evidence extraction
      │     - Output schema validation
      │     - Traceability tagging
      │
      ├─► STEP B  (Prompt B → Claude)
      │     - Report generation per section
      │     - Stage + standard aware
      │     - Safety checks
      │
      ├─► STEP C  (Prompt C → Claude)
      │     - Validation + correction
      │     - Correction log extraction
      │     - Final structure check
      │
      └─► ASSEMBLY
            - Insert content into .docx template
            - Export final report
            - Store correction log
            - Mark job COMPLETE
```

---

## Folder Structure

```
BATUHAN/
├── backend/
│   ├── api/
│   │   ├── routes/          # FastAPI route handlers
│   │   └── middleware/      # Auth, error handling
│   ├── pipeline/
│   │   ├── step_a/          # Prompt A orchestration
│   │   ├── step_b/          # Prompt B orchestration
│   │   └── step_c/          # Prompt C orchestration
│   ├── parsers/             # PDF, DOCX, OCR, template, style parsers
│   ├── jobs/                # Celery tasks and job state management
│   ├── storage/             # File I/O abstraction
│   ├── schemas/             # Pydantic data contracts
│   ├── config/              # Settings and env loader
│   ├── prompts/             # prompt_a.txt, prompt_b.txt, prompt_c.txt
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/
├── frontend/
│   ├── src/
│   │   ├── app/             # Next.js App Router pages
│   │   ├── components/      # UI components
│   │   └── lib/             # API client, types
│   └── public/
└── docs/
    └── architecture.md      # This file
```

---

## Data Flow Between Steps

```
UploadBundle
    │
    ▼
DocumentCorpus + TemplateMap + StyleGuidance
    │
    ▼  [Prompt A]
ExtractedEvidence  (7 sections, bullet facts, source-tagged)
    │
    ▼  [Prompt B]
GeneratedReport  (section_title → content, per template map)
    │
    ▼  [Prompt C]
ValidatedReport + CorrectionLog
    │
    ▼
Final .docx + corrections.txt
```

---

## Key Constraints (from BATUHAN.pdf / A / B / C)
- Pipeline order A → B → C is **non-negotiable**
- Template structure must **never change**
- No information may be **invented**
- Sample reports are **style-only** — no content copying
- Every claim must be **evidence-supported**
- Weak evidence → **cautious phrasing**, not omission
- Final output must be **ready for direct Word insertion**

