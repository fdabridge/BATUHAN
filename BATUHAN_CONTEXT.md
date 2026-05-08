# BATUHAN — Full System Context for AI Agents

> This document is the single source of truth about the BATUHAN platform.
> It is written for an AI agent that needs to understand, debug, extend, or reason
> about the system exactly as a senior developer who built it would.

---

## 1. What BATUHAN Is

BATUHAN is an **AI-driven ISO certification audit report generation platform** built for
**IFC Global LLC**, a certification body (the company that runs the audits, not the client).

Given a set of company documents, a blank Word template, and some style-reference sample
reports, BATUHAN autonomously generates a fully filled, professionally worded ISO audit
report — the same document an experienced auditor would write by hand after a site visit.

It supports **Stage 1** (documentation review) and **Stage 2** (implementation audit) reports
across **8 ISO standards**, including integrated multi-standard audits.

---

## 2. Supported Standards

| Code  | Standard | Full Name |
|-------|----------|-----------|
| QMS   | ISO 9001:2015 | Quality Management System |
| EMS   | ISO 14001:2015 | Environmental Management System |
| OHSMS | ISO 45001:2018 | Occupational Health & Safety |
| FSMS  | ISO 22000:2018 | Food Safety Management System |
| MDQMS | ISO 13485:2016 | Medical Devices Quality Management |
| ISMS  | ISO 27001:2022 | Information Security Management |
| ABMS  | ISO 37001:2016 | Anti-Bribery Management |
| ENMS  | ISO 50001:2018 | Energy Management System |

**Integrated audits** are fully supported: the user selects multiple standards and one
unified report covering all selected standards is generated. Non-selected standard sections
are labelled "Not applicable."

---

## 3. What It Does — The Full Pipeline

```
User Uploads → PREPROCESSING → STEP A → STEP B → STEP C → ASSEMBLING → Final DOCX
```

### PREPROCESSING
- Extracts text from all uploaded company documents (PDF, DOCX, TXT, PNG, JPG, TIFF)
- Runs OCR (Tesseract) on scanned/image documents; prefers OCR output when it yields
  more text than the direct extraction
- Caps corpus at **40,000 chars/doc** and **120,000 chars total** (~30k tokens)
- Parses the blank `.docx` template to extract section structure (`TemplateMap`)
- Reads sample audit reports to extract **style/tone only** (`StyleGuidance`) — never
  content, company names, or data from samples
- Whitelists certifier names (IFC Global LLC) from the blocked-name list by checking
  whether they appear in the blank template

### STEP A — Evidence Extraction (Prompt A)
- Sends the full document corpus + selected standard(s) + stage to Claude
- Claude extracts structured evidence into **7 categories**:
  1. `company_overview`
  2. `scope_of_activities`
  3. `documented_information`
  4. `key_processes_and_functions`
  5. `evidence_of_system_implementation`
  6. `audit_relevant_records`
  7. `identified_gaps`
- Each item is an `EvidenceItem` with `statement`, `source_filename`, `is_weak` flag
- Retries up to 3× on malformed output
- Persists: `step_a_evidence.json`, `step_a_traceability.txt`, `step_a_formatted.txt`

### STEP B — Report Generation (Prompt B)
- Receives `ExtractedEvidence` (no raw documents beyond this point)
- Claude writes one content block per template section using the evidence + style guidance
- Supports EN (English) and TR (Turkish) output language
- Runs safety checks on sections (placeholder detection, style violations)
- Persists: `step_b_report.json`, `step_b_formatted.txt`, `step_b_safety_check.txt`

### STEP C — Validation & Correction (Prompt C)
- Pre-validates the Step B report deterministically (missing sections, empty content,
  blocked names still present, placeholder patterns)
- Sends the report + evidence back to Claude for correction
- Claude rewrites any incorrect/incomplete sections and logs each change
- Post-validates corrected output for structural integrity
- Falls back to Step B output if Step C itself fails (graceful degradation)
- Persists: `step_c_report.json`, `step_c_correction_log.json`, `step_c_formatted.txt`

### LEAKAGE SCAN
Runs after Step C. Blocks delivery on **CRITICAL** violations:
- `COMPANY_NAME` — a blocked client company name (from sample reports) appears in output
- `PLACEHOLDER` — unfilled template placeholder `[...]`, `{...}`, `<insert...>`, TODO, TBD
- `PHRASE_COPY` — verbatim phrase >80 chars copied from a sample report (WARNING only)
ISO clause references like `[A.5.1]`, `[ISO 9001:2015]` are explicitly whitelisted.

### ASSEMBLING — Coordinate-Based LLM Mapping
This is the most complex step. Rather than using brittle heading-matching heuristics,
BATUHAN uses a **coordinate-based assembly** system:

1. The blank `.docx` template is scanned and every table cell is given a coordinate:
   `T<table>_R<row>_C<col>` (all 1-based). Cells are labelled `[EMPTY]`, `[LABEL — DO NOT MODIFY]`,
   or `[TEMPLATE INSTRUCTION — DO NOT OUTPUT]`.
2. The structure text is chunked to avoid the 8192-token output limit:
   - Small tables (≤40 empty cells) are bundled together
   - Large tables (>40) get their own Claude call
   - Very large tables (>80, e.g. ISO 27001 Annex A with 168 empty cells) are split into
     row-range sub-chunks of 35 rows each, with the header row repeated for context
3. Claude returns cell assignments in a structured format:
   ```
   CELL: T18_R3_C2
   CONTENT:
   [findings text]
   END_CELL
   ```
4. After mapping, `_auto_tick_conclusion_cells` post-processes the result: any
   `Conclusion(✓ / NC / OBS)` or `Result` column cell adjacent to a filled Findings cell
   that Claude left empty is automatically filled with `√`
5. Word checkbox controls (modern SDT, legacy fldChar, Unicode ☐) are activated natively
6. Template instruction cells are stripped before saving

---


## 4. How It Runs — Infrastructure

| Component | Technology | Role |
|-----------|-----------|------|
| API server | FastAPI + Uvicorn | Accepts uploads, queues jobs, serves downloads |
| Background worker | Celery (concurrency=2) | Executes the pipeline asynchronously |
| Message broker | Redis | Celery task queue + job artifact storage |
| File storage | Redis (binary keys) | All artifacts stored as Redis keys — no shared filesystem |
| Database | SQLite (via SQLAlchemy) | Optional; job state primarily lives in Redis |
| Containerisation | Docker | API and Worker run as separate containers |
| Deployment | Railway | Cloud; auto-redeploys on `git push origin main` |
| AI model | `claude-sonnet-4-6` | All LLM calls use this model |

**File passing:** Files are base64-encoded at the API layer and passed as Celery task
arguments through Redis. No shared filesystem between API and Worker. Each job writes to
a temp dir on the worker, which is cleaned up after completion or failure (always, in `finally`).

**Job states:** `QUEUED → PREPROCESSING → STEP_A → STEP_B → STEP_C → ASSEMBLING → COMPLETE`
or `FAILED` at any point.

---

## 5. API Endpoints

### Report Generation (async, job-based)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/jobs/create` | Submit docs + template → returns `job_id` |
| GET  | `/jobs/{job_id}/status` | Poll state (QUEUED/STEP_A/.../COMPLETE/FAILED) |
| GET  | `/jobs/{job_id}/download/report` | Download `audit_report_{job_id}.docx` |
| GET  | `/jobs/{job_id}/download/corrections` | Download `correction_log.txt` |
| GET  | `/jobs/{job_id}/summary` | JSON: standard, stage, correction count, files used |

**`POST /jobs/create` form fields:**
- `standards` (repeatable): `QMS`, `EMS`, `OHSMS`, `FSMS`, `MDQMS`, `ISMS`, `ABMS`, `ENMS`
- `stage`: `"Stage 1"` or `"Stage 2"`
- `company_documents`: files (PDF, DOCX, TXT, PNG, JPG, TIFF)
- `sample_reports`: files (style reference — content is never used)
- `template`: one `.docx` blank report template
- `org_name`, `org_address`, `org_phone`: optional; injected verbatim into the report
- `language`: `"EN"` (default) or `"TR"` (Turkish)

### Audit Plan Generator (synchronous, ~10s)
`POST /audit-plan/generate` — Upload a pre-filled FR.223 `.docx` (Tables 0 and 1 already
filled by the user). BATUHAN reads org info, selected standards, audit dates, and team;
calls Claude to generate an hourly schedule; fills Table 2; returns the completed `.docx`.

Schedule rules: 09:00–17:00, lunch 13:00–14:00, TA always paired with LA,
no "Wash-up Meeting" or "Write Draft Report" slots.

### Audit Time Calculator (synchronous, ~5s)
`POST /calculator/calculate` — Upload one or more application form files (PDF/DOCX/TXT).
Claude extracts org name, employee count, and standards from the form. The calculation
engine applies EA/IAF tables to produce:
- `final_ph1` (Stage 1 days), `final_ph2` (Stage 2 days), `final_total`
- Surveillance and recertification splits

---

## 6. Claude API Configuration & Cost

| Setting | Value |
|---------|-------|
| Model | `claude-sonnet-4-6` (env: `CLAUDE_MODEL`) |
| Max output tokens | `8192` (env: `CLAUDE_MAX_TOKENS`) |
| Temperature | `0.2` |
| Step A retries | up to 3× on malformed parse |
| Step B retries | up to 3× on malformed parse |
| Step C retries | up to 2× then falls back to Step B |
| Assembly calls | 2–6 per job depending on template size |

**Cost estimate per job** (Claude Sonnet list pricing ~$3/MTok input, $15/MTok output):
- Simple single-standard report: ~5 Claude calls → ~**$0.30–$0.50**
- ISO 27001 with full Annex A: ~8–9 Claude calls → ~**$0.60–$0.90**
- `max_retries=0` on the Celery task — jobs do NOT auto-retry (would re-bill API)

---

## 7. Prompts

All prompts in `backend/prompts/`. `#` comment lines stripped before use.

| File | Step | Key placeholders |
|------|------|-----------------|
| `prompt_a.txt` | Evidence Extraction | `{standard}`, `{stage}`, `{document_corpus}` |
| `prompt_b.txt` | Report Generation | `{standard}`, `{stage}`, `{evidence}`, `{template_sections}`, `{style_guidance}`, `{language_instruction}` |
| `prompt_c.txt` | Validation & Correction | `{standard}`, `{stage}`, `{generated_report}`, `{extracted_evidence}`, `{language_instruction}` |
| `prompt_assembly.txt` | Cell Mapping | `{selected_standard}`, `{non_applicable_standards}`, `{org_info}`, `{language_instruction}`, `{template_structure}`, `{report_content}` |

**Critical assembly prompt rules:**
- Columns named `Findings` → detailed text
- Columns named `Conclusion`, `Result`, or containing `✓` → only `√`, `NC`, or `OBS`
- Never leave Conclusion empty when Findings is filled; never write "Conforming"
- `[LABEL — DO NOT MODIFY]` cells must not be overwritten
- `[NON-SELECTED STANDARD]` tables → write "Not applicable" in content cells

---

## 8. Key Source Files

| File | Purpose |
|------|---------|
| `backend/jobs/tasks.py` | Celery task; full pipeline orchestration |
| `backend/pipeline/step_a/orchestrator.py` | Step A: evidence extraction |
| `backend/pipeline/step_b/orchestrator.py` | Step B: report generation |
| `backend/pipeline/step_c/orchestrator.py` | Step C: validation & correction |
| `backend/assembly/llm_mapper.py` | Coordinate-based cell mapping (most complex file) |
| `backend/assembly/result_packager.py` | Assembles final DOCX; chooses LLM vs heuristic mapper |
| `backend/assembly/docx_builder.py` | Fallback heuristic assembler (heading-match) |
| `backend/safety/leakage_detector.py` | Leakage scan: company names, placeholders, phrase copy |
| `backend/safety/failure_handler.py` | PipelineAbort, guards, Step C fallback |
| `backend/parsers/corpus_builder.py` | Merges text extraction + OCR into unified corpus |
| `backend/parsers/style_extractor.py` | Extracts style/tone from samples (never content) |
| `backend/parsers/ocr_pipeline.py` | Tesseract OCR for scanned docs and images |
| `backend/schemas/models.py` | All Pydantic data models |
| `backend/config/settings.py` | All env-var settings |
| `backend/audit_plan/routes.py` | Audit Plan Generator endpoint |
| `backend/calculator/routes.py` | Audit Time Calculator endpoint |
| `backend/api/routes/jobs.py` | Job creation and status/download endpoints |
| `backend/storage/file_store.py` | Redis-backed artifact storage |

---

## 9. Data Models

```
UploadBundle          → job submission inputs
ParsedDocument        → one extracted company document (filename, text, is_ocr_sourced, char_count)
TemplateMap           → ordered section list from blank template
StyleGuidance         → tone/structure notes + blocked_company_names + blocked_phrases
ExtractedEvidence     → Step A output: 7 evidence category lists of EvidenceItem
  └── EvidenceItem    → statement + source_filename + is_weak flag
GeneratedReport       → Step B output: list of ReportSection
  └── ReportSection   → title + content + order_index + has_weak_evidence
ValidatedReport       → Step C output: corrected ReportSection list + CorrectionLog
  └── CorrectionLog   → list of CorrectionEntry (section_title + description)
JobResult             → final delivery: DOCX path, corrections path, metadata
JobStatus             → real-time state with step_timestamps
```

Enums: `ISOStandard` (8 values), `AuditStage` (Stage 1/2), `ReportLanguage` (EN/TR),
`JobState` (QUEUED, PREPROCESSING, STEP_A, STEP_B, STEP_C, ASSEMBLING, COMPLETE, FAILED).

---

## 10. Assembly Deep-Dive — llm_mapper.py

| Function | Purpose |
|----------|---------|
| `_build_table_structure_lines(tbl, tbl_num, selected_values, row_start, row_end)` | Coordinate-tagged lines for one table / row-range slice; returns `(lines, empty_count)` |
| `template_to_structure_text(template_path, selected_standards)` | Full-template structure string (used for debugging) |
| `_plan_call_chunks(template_path, selected_standards)` | Groups tables into Claude call chunks by empty-cell count |
| `get_cell_mapping(...)` | Main entry: iterates chunks, calls Claude per chunk, merges all mappings |
| `parse_cell_mapping(response)` | Parses `CELL:/CONTENT:/END_CELL` blocks → `{coord: content}` dict |
| `_auto_tick_conclusion_cells(body, mapping)` | Detects Findings/Conclusion column pairs; auto-fills `√` where Claude missed |
| `apply_cell_mapping(body, mapping)` | Builds coord→`tc` index; fills cells; handles checkbox activation |
| `_tick_checkbox_cell(tc)` | Activates modern SDT checkbox, legacy fldChar, or replaces Unicode ☐ |
| `strip_template_instruction_cells(body)` | Clears boilerplate instruction cells before saving |
| `_tbl_belongs_to_standard(tbl)` | Detects which ISO standard a table belongs to |

**Chunking thresholds:** `_LARGE_TABLE_THRESHOLD = 40`, `_ROW_CHUNK_SIZE = 35`

**Column detection:** `_CONCLUSION_COL_RE` matches `conclusion|result|✓|tick|nc|obs`;
`_FINDINGS_COL_RE` matches `finding|observation|remark`

---

## 11. Safety Architecture

**Layer 1 — Input guards (`failure_handler.py`)**
- `filter_readable_documents` — skips unreadable files; `PipelineAbort` if ALL empty
- `assert_template_valid` — aborts if template has no sections
- `assert_evidence_valid` — aborts if Step A returned nothing

**Layer 2 — Output leakage scan (`leakage_detector.py`)**
- CRITICAL (blocks delivery): company name in output, unfilled placeholders
- WARNING (logged only): verbatim phrase >80 chars from sample report
- Whitelisted: ISO clause refs `[A.5.1]`, `[ISO 9001:2015]`, certifier name in template

**Layer 3 — Structural validation (`step_c/pre_validator.py` + `post_validator.py`)**
- Pre: missing sections, empty content, blocked names, placeholders → fed to Prompt C
- Post: verifies corrected report has all sections, no empties

---

## 12. Quality Characteristics

### Strong ✅
- Single-standard reports (QMS, EMS, FSMS, etc.): complete, professional output
- Integrated multi-standard reports: all selected tables filled; non-selected → "Not applicable"
- Turkish-language output via `language_instruction` in prompts
- OCR for scanned PDFs and images
- ISO 27001 Annex A: all 93 controls filled across chunked calls (fixed 2026-05)
- Conclusion tick columns: auto-filled even when Claude misses them (fixed 2026-05)

### Degrades with ⚠️
- **Thin evidence** (<5,000 chars of company docs): findings will be generic
- **Complex/unusual templates**: heavily merged cells or non-standard layouts may confuse mapper
- **Stage 2 depth**: requires richer docs (procedures, records) than Stage 1 (just documentation)
- **Very large integrated audits** (3+ standards): more Claude calls = more latency

### Fallbacks
- Step C failure → Step B output used (graceful degradation)
- LLM mapper failure → heuristic `docx_builder` used
- Step A/B malformed output → retry up to 3×

---

## 13. Operational Facts

- **Certifier:** IFC Global LLC — always whitelisted; never blocked by leakage scan
- **Coordinate format:** `T<n>_R<r>_C<c>` — all 1-based; counts ALL `<w:tbl>` in body order
- **Artifact storage:** Redis key `{job_id}:{filename}`. Assembly debug files:
  `assembly_template_structure_chunk{N}.txt`, `assembly_cell_mapping_raw_chunk{N}.txt`
- **Concurrency:** 2 parallel jobs (Celery `--concurrency=2`)
- **No auto-retry:** `max_retries=0` on Celery task to avoid re-billing API
- **Temp cleanup:** always happens in `finally` block, even on failure

---

## 14. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | required | Claude API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Model identifier |
| `CLAUDE_MAX_TOKENS` | `8192` | Max output tokens per call |
| `CLAUDE_TEMPERATURE` | `0.2` | Temperature (all calls) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | (= REDIS_URL) | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery results |
| `ALLOWED_ORIGINS` | `http://localhost:3000,...` | CORS origins |
| `INTERNAL_API_KEY` | `change-me-in-production` | API auth header |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `DATABASE_URL` | `sqlite:///./batuhan.db` | DB connection |
| `PROMPTS_DIR` | `./prompts` | Prompt `.txt` file directory |
| `DEBUG` | `false` | Debug mode |
