# Augment Task: Better Extraction + Standards Display + Witness Audit Tracking

## Context

This is Certiva — a Next.js 14 (App Router) + FastAPI platform for ISO certification bodies.
The backend uses SQLite (`auditors.db`, `auth.db`) on Railway (ephemeral — no migration tool needed, just `create_tables()` on startup).

---

## What Needs To Be Done

### Task 1 — Improve PDF Extraction: Validate EA Codes Against Official IAF List

**File:** `backend/auditors/extractor.py`

The extractor's system prompt currently tells Claude to "look for sector codes, NACE/EA codes" but gives no reference list — so Claude invents wrong code numbers. Update the system prompt to embed the full official IAF EA code table so Claude can map scope descriptions to the correct EA code numbers.

Replace the `_SYSTEM_PROMPT` constant with:

```python
_SYSTEM_PROMPT = """\
You are parsing an auditor CV or IFC form (FR.201). Extract all available fields.
Return ONLY valid JSON with these keys:
  name, email, phone, mobile, role,
  education (list of {degree, institution, year}),
  languages (list of {language, level}),
  field_of_expertise,
  ea_codes (list of strings — use ONLY codes from the official IAF EA code list below),
  accreditation_bodies (list of strings like "UAF", "TURKAK"),
  standard_qualifications (list of {standard_code, accreditation_body, technical_depth, experience_years}),
  work_experience (list of {employer, position, start_date, end_date, description}),
  training_records (list of {training_date, institution, subject, duration_days, standard_code, certificate_available}).
Use null for any field not found.

OFFICIAL IAF EA CODE LIST — only use codes from this table. Format as "EA N" (e.g. "EA 3"):
EA 1  - Agriculture, forestry and fishing
EA 2  - Mining and quarrying
EA 3  - Food products, beverages and tobacco
EA 4  - Textiles and textile products
EA 5  - Leather and leather products
EA 6  - Wood and wood products
EA 7  - Pulp, paper and paper products
EA 8  - Publishing companies
EA 9  - Printing companies
EA 10 - Manufacture of coke and refined petroleum products
EA 11 - Nuclear fuel
EA 12 - Chemicals, chemical products and fibres
EA 13 - Pharmaceuticals
EA 14 - Rubber and plastic products
EA 15 - Non-metallic mineral products
EA 16 - Concrete, cement, lime, plaster and similar products
EA 17 - Basic metals and fabricated metal products
EA 18 - Machinery and equipment
EA 19 - Electrical and optical equipment
EA 20 - Shipbuilding
EA 21 - Aerospace
EA 22 - Other transport equipment
EA 23 - Manufacturing not elsewhere classified
EA 24 - Recycling
EA 25 - Electricity supply
EA 26 - Gas supply
EA 27 - Water supply
EA 28 - Construction
EA 29 - Wholesale and retail trade; repair of motor vehicles, motorcycles and personal/household goods
EA 30 - Hotels and restaurants
EA 31 - Transport, storage and communication
EA 32 - Financial intermediation, real estate, renting
EA 33 - Information technology
EA 34 - Engineering services
EA 35 - Other services
EA 36 - Public administration
EA 37 - Education
EA 38 - Health and social work
EA 39 - Other social services

STANDARD QUALIFICATIONS RULES:
- standard_code must be the ISO standard reference, e.g. "ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001".
- For each qualification, include accreditation_body if mentioned (e.g. "UAF", "TURKAK", "DAkkS").
- technical_depth: one of "Lead Auditor", "Team Auditor", "Technical Expert".
- experience_years: total years of documented auditing experience for that standard (integer).
- A qualification should only be included if there is evidence of BOTH: (a) relevant training/certification AND (b) auditing experience. If only training is mentioned with no experience, still include it but set experience_years to 0.
"""
```

After extracting, also add a post-extraction validation step. In the `extract_auditor_from_document` function, after `result = json.loads(repair_json(raw))`, add:

```python
# Validate and clean EA codes against official list
VALID_EA_NUMBERS = set(range(1, 40))  # EA 1 through EA 39
raw_ea = result.get("ea_codes") or []
cleaned_ea = []
for code in raw_ea:
    if isinstance(code, str):
        # Normalize: "EA3", "3", "EA 3" → "EA 3"
        normalized = code.strip().upper()
        if normalized.startswith("EA"):
            num_part = normalized[2:].strip()
        else:
            num_part = normalized
        try:
            num = int(num_part)
            if num in VALID_EA_NUMBERS:
                cleaned_ea.append(f"EA {num}")
            else:
                logger.warning("[Auditors/Extractor] Dropped invalid EA code: %s", code)
        except ValueError:
            logger.warning("[Auditors/Extractor] Could not parse EA code: %s", code)
result["ea_codes"] = cleaned_ea
```

Also add a flag for qualifications that may need human review:

```python
# Flag qualifications missing accreditation_body
for q in result.get("standard_qualifications") or []:
    if not q.get("accreditation_body"):
        q["_needs_review"] = True
```

---

### Task 2 — Add Standards Display to Auditor List (First Screen)

**File:** `frontend/src/app/(app)/auditors/page.tsx`

Currently the auditor table has these columns: Name/Role, EA Codes, Last Audit, Status, Warnings.
The qualifications (standards) are only visible on the detail page. Add a "Standards" column to the table.

**2a. In the `AuditorRow` component,** add a new `<td>` after the EA Codes cell:

```tsx
<td className="px-4 py-3">
  {a.qualifications.length === 0 ? (
    <span className="text-gray-300 text-xs">—</span>
  ) : (
    <div className="flex flex-wrap gap-1">
      {a.qualifications.slice(0, 3).map((q) => (
        <span
          key={q.standard_code}
          className="inline-block rounded px-1.5 py-0.5 text-xs font-medium"
          style={{ background: '#F0FAF4', color: '#1A4731' }}
          title={q.technical_depth ?? ''}
        >
          {q.standard_code}
        </span>
      ))}
      {a.qualifications.length > 3 && (
        <span className="text-xs text-gray-400">+{a.qualifications.length - 3}</span>
      )}
    </div>
  )}
</td>
```

**2b. Add the column header** to the `<thead>` row (after "EA Codes", before "Last Audit"):

```tsx
<th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-400">Standards</th>
```

**2c. Update the skeleton row** (`SkeletonRow` component) to have 8 cells instead of 7 (add one `<td>` with `animate-pulse` block).

---

### Task 3 — Witness Audit Tracking (Backend)

**Context:** ISO/IEC 17021-1 Section 7.1 requires CBs to have a documented process for monitoring the ongoing competence of their auditors. The standard practice expected by accreditation bodies (UAF, TÜRKAK) is:
- New auditor: must be witnessed within the **first 12 months** for each scope (standard + EA code cluster they work in).
- Ongoing: at minimum **once every 3 years** per scope area.
- The CB must keep dated records of each witness event including who observed, what client, which standard, and the outcome.

**3a. Add `AuditorWitnessRecord` model** to `backend/auditors/models.py`:

```python
class AuditorWitnessRecord(Base):
    """CB's own witness audit records for its auditors (ISO 17021-1 §7.1)."""
    __tablename__ = "auditor_witness_records"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id     = Column(String, ForeignKey("auditors.id"), nullable=False)
    witness_date   = Column(String, nullable=False)   # "YYYY-MM-DD"
    client_name    = Column(String)
    standard_code  = Column(String)                   # e.g. "ISO 9001"
    ea_code        = Column(String)                   # e.g. "EA 3"
    role_witnessed = Column(String)                   # "Lead Auditor" | "Team Auditor"
    observer_name  = Column(String)                   # name of the CB witness observer
    outcome        = Column(String)                   # "Satisfactory" | "Needs Improvement" | "Unsatisfactory"
    notes          = Column(Text)
    created_at     = Column(DateTime, default=datetime.utcnow)

    auditor = relationship("Auditor", back_populates="witness_records")
```

Also add `witness_records` to the `Auditor` class:
```python
witness_records = relationship("AuditorWitnessRecord", back_populates="auditor", cascade="all, delete-orphan")
```

Make sure `create_tables()` is called on app startup so this new table is created automatically. The call to `create_tables()` should already exist in `main.py` or the auditors service startup — verify this is in place and if not add it.

**3b. Add schemas** to `backend/auditors/schemas.py`:

```python
class WitnessRecordItem(BaseModel):
    id: Optional[int] = None
    witness_date: str
    client_name: Optional[str] = None
    standard_code: Optional[str] = None
    ea_code: Optional[str] = None
    role_witnessed: Optional[str] = None
    observer_name: Optional[str] = None
    outcome: Optional[str] = None   # "Satisfactory" | "Needs Improvement" | "Unsatisfactory"
    notes: Optional[str] = None

class WitnessRecordCreateSchema(BaseModel):
    witness_date: str
    client_name: Optional[str] = None
    standard_code: Optional[str] = None
    ea_code: Optional[str] = None
    role_witnessed: Optional[str] = None
    observer_name: Optional[str] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None

class WitnessStatusSchema(BaseModel):
    """Computed witness compliance status for one auditor."""
    auditor_id: str
    auditor_name: str
    last_witness_date: Optional[str]    # most recent witness_date across all records
    days_since_last_witness: Optional[int]
    witness_overdue: bool               # True if last_witness_date > 3 years ago OR never witnessed
    new_auditor_unwitnessed: bool       # True if created_at > 12 months ago and zero witness records
    total_witness_count: int
    records: list[WitnessRecordItem]
```

Also add `witness_records: list[WitnessRecordItem] = []` to `AuditorResponseSchema`.

**3c. Add API routes** to `backend/api/routes/auditors.py`:

```python
@router.get("/{auditor_id}/witness", response_model=WitnessStatusSchema)
def get_witness_status(
    auditor_id: str,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """Return all witness records + computed compliance status for one auditor."""
    from auditors.models import Auditor, AuditorWitnessRecord
    from datetime import date, timedelta
    
    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        raise HTTPException(status_code=404, detail="Auditor not found")
    
    records = db.query(AuditorWitnessRecord).filter(
        AuditorWitnessRecord.auditor_id == auditor_id
    ).order_by(AuditorWitnessRecord.witness_date.desc()).all()
    
    last_witness_date = records[0].witness_date if records else None
    days_since = None
    witness_overdue = True
    
    if last_witness_date:
        last_dt = date.fromisoformat(last_witness_date)
        days_since = (date.today() - last_dt).days
        witness_overdue = days_since > (3 * 365)
    
    # New auditor: created more than 12 months ago but never witnessed
    created = auditor.created_at.date() if auditor.created_at else date.today()
    new_auditor_unwitnessed = (len(records) == 0) and ((date.today() - created).days > 365)
    
    return WitnessStatusSchema(
        auditor_id=auditor_id,
        auditor_name=auditor.name,
        last_witness_date=last_witness_date,
        days_since_last_witness=days_since,
        witness_overdue=witness_overdue,
        new_auditor_unwitnessed=new_auditor_unwitnessed,
        total_witness_count=len(records),
        records=[WitnessRecordItem(
            id=r.id,
            witness_date=r.witness_date,
            client_name=r.client_name,
            standard_code=r.standard_code,
            ea_code=r.ea_code,
            role_witnessed=r.role_witnessed,
            observer_name=r.observer_name,
            outcome=r.outcome,
            notes=r.notes,
        ) for r in records],
    )


@router.post("/{auditor_id}/witness", status_code=201)
def add_witness_record(
    auditor_id: str,
    payload: WitnessRecordCreateSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_admin),
):
    """Log a new witness audit record for an auditor."""
    from auditors.models import Auditor, AuditorWitnessRecord
    
    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        raise HTTPException(status_code=404, detail="Auditor not found")
    
    record = AuditorWitnessRecord(
        auditor_id=auditor_id,
        **payload.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": "created"}


@router.delete("/{auditor_id}/witness/{record_id}", status_code=204)
def delete_witness_record(
    auditor_id: str,
    record_id: int,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_admin),
):
    from auditors.models import AuditorWitnessRecord
    rec = db.query(AuditorWitnessRecord).filter(
        AuditorWitnessRecord.id == record_id,
        AuditorWitnessRecord.auditor_id == auditor_id,
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(rec)
    db.commit()
```

Import `WitnessRecordCreateSchema`, `WitnessStatusSchema`, `WitnessRecordItem` at the top of the routes file.

**3d. Add a `GET /auditors/witness-summary` endpoint** that returns overdue status for ALL auditors (for the dashboard warning badges):

```python
@router.get("/witness-summary", response_model=list[WitnessStatusSchema])
def witness_summary(
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """Return witness compliance status for every active auditor."""
    from auditors.models import Auditor, AuditorWitnessRecord
    from datetime import date
    
    auditors = db.query(Auditor).filter(Auditor.is_active == True).all()
    result = []
    for auditor in auditors:
        records = db.query(AuditorWitnessRecord).filter(
            AuditorWitnessRecord.auditor_id == auditor.id
        ).order_by(AuditorWitnessRecord.witness_date.desc()).all()
        
        last_witness_date = records[0].witness_date if records else None
        days_since = None
        witness_overdue = True
        
        if last_witness_date:
            last_dt = date.fromisoformat(last_witness_date)
            days_since = (date.today() - last_dt).days
            witness_overdue = days_since > (3 * 365)
        
        created = auditor.created_at.date() if auditor.created_at else date.today()
        new_auditor_unwitnessed = (len(records) == 0) and ((date.today() - created).days > 365)
        
        result.append(WitnessStatusSchema(
            auditor_id=auditor.id,
            auditor_name=auditor.name,
            last_witness_date=last_witness_date,
            days_since_last_witness=days_since,
            witness_overdue=witness_overdue,
            new_auditor_unwitnessed=new_auditor_unwitnessed,
            total_witness_count=len(records),
            records=[],  # omit full records in summary
        ))
    return result
```

**IMPORTANT:** The `/witness-summary` route must be registered **before** `/{auditor_id}` in the router, otherwise FastAPI will try to match "witness-summary" as an auditor ID and fail with a 404. Add it before the `/{auditor_id}` GET route.

---

### Task 4 — Witness Audit Tracking (Frontend)

**File:** `frontend/src/app/(app)/auditors/page.tsx`

**4a. Add `WitnessRecord` and `WitnessStatus` types** to `frontend/src/types/index.ts`:

```typescript
export interface WitnessRecord {
  id: number
  witness_date: string
  client_name: string | null
  standard_code: string | null
  ea_code: string | null
  role_witnessed: string | null
  observer_name: string | null
  outcome: 'Satisfactory' | 'Needs Improvement' | 'Unsatisfactory' | null
  notes: string | null
}

export interface WitnessStatus {
  auditor_id: string
  auditor_name: string
  last_witness_date: string | null
  days_since_last_witness: number | null
  witness_overdue: boolean
  new_auditor_unwitnessed: boolean
  total_witness_count: number
  records: WitnessRecord[]
}
```

**4b. Add witness overdue badge to the auditor list table.**

In `AuditorRow`, update the `StatusBadge` component (or add an additional badge in the warnings cell) to also show a "Witness Due" badge when the auditor is overdue. To do this:

1. Fetch `GET /auditors/witness-summary` using React Query with key `['witness-summary']`.
2. Pass the relevant `WitnessStatus` entry down to `AuditorRow` as a `witness` prop.
3. In `StatusBadge` (or the warnings column), if `witness.witness_overdue || witness.new_auditor_unwitnessed`, show:
   ```tsx
   <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs" style={{ background: '#FEE2E2', color: '#991B1B' }}>
     <AlertTriangle size={12} /> Witness Due
   </span>
   ```

**4c. Add a witness audit panel to the auditor detail page.**

The auditor list rows currently navigate to a detail URL on click (`/auditors/[id]` or similar). Find where the detail view is rendered — it may be a slide-over, modal, or separate page. Add a "Witness Audits" section:

If there is an existing detail slide-over or modal that opens when clicking a row, add a "Witness Audits" tab or section at the bottom of it. If the detail is a separate page (`/auditors/[id]/page.tsx`), add the section there.

The witness section should contain:

**Status banner:**
```tsx
// If witness_overdue or new_auditor_unwitnessed:
<div className="rounded-md p-3 text-sm" style={{ background: '#FEE2E2', color: '#991B1B' }}>
  ⚠ Witness audit overdue. ISO 17021-1 §7.1 requires witnessing at least once every 3 years per auditor.
  Last witnessed: {witnessStatus.last_witness_date ?? 'Never'}
</div>

// If compliant:
<div className="rounded-md p-3 text-sm" style={{ background: '#F0FAF4', color: '#1A4731' }}>
  ✓ Witness audit up to date. Last: {witnessStatus.last_witness_date} ({witnessStatus.days_since_last_witness} days ago)
</div>
```

**Witness record table:**
Show all past witness records in a table with columns: Date, Client, Standard, EA Code, Role, Observer, Outcome.
Outcome cell should use colored badges: Satisfactory = green, Needs Improvement = amber, Unsatisfactory = red.

**"Log witness audit" button:**
A button with label "Log witness audit" opens a small inline form (or a nested slide-over) with fields:
- Witness date (`<input type="date">`)
- Client name (`<input type="text">`)
- Standard (`<input type="text">`, e.g. "ISO 9001")
- EA Code (`<input type="text">`, e.g. "EA 3")
- Role witnessed (`<select>`: Lead Auditor / Team Auditor / Technical Expert)
- Observer name (`<input type="text">`)
- Outcome (`<select>`: Satisfactory / Needs Improvement / Unsatisfactory)
- Notes (`<textarea>`)
- Save button calls `POST /auditors/{id}/witness` with the form data
- On success, invalidate `['witness-status', auditorId]` and `['witness-summary']` React Query caches

---

## API Summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/auditors/{id}/witness` | any | Get all witness records + status for one auditor |
| `POST` | `/auditors/{id}/witness` | admin | Log a new witness record |
| `DELETE` | `/auditors/{id}/witness/{record_id}` | admin | Remove a witness record |
| `GET` | `/auditors/witness-summary` | any | Overdue status for all active auditors |

All calls use the axios instance from `@/lib/api` which adds the Bearer token automatically.

---

## Styling Rules

- Certiva green: `#1A4731` (CSS) / `certiva-primary` (Tailwind)
- Surface: `#F0FAF4` / `certiva-surface`
- Warning (amber): `#FEF3C7` background / `#92400E` text
- Danger (red): `#FEE2E2` background / `#991B1B` text
- Success (green): `#F0FAF4` background / `#1A4731` text
- Loading: `<Loader2 size={16} className="animate-spin" />` from lucide-react
- Error fields: `border-red-300` + `text-red-500`
- No new npm packages. No new backend Python packages.

---

## Do Not Change

- `backend/auditors/extractor.py` existing JSON repair logic — only update `_SYSTEM_PROMPT` and add EA validation after parsing
- `backend/requirements.txt` — already correct, no new packages needed
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.tsx`
- `frontend/src/components/layout/` (Sidebar, Topbar)
- `backend/api/routes/auth.py`
- Any other file not listed above

---

## Priority Order

1. Task 1 (better EA code extraction) — small backend change, high value
2. Task 2 (standards column in table) — small frontend change, immediately visible
3. Task 3 (witness backend) — new DB table + endpoints
4. Task 4 (witness frontend) — UI for the tracking

Complete all four tasks in order.
