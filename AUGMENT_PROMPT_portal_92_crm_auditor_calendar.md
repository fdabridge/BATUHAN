# Portal 92 — CRM Auditor Calendar

## Goal

Add an auditor availability calendar to the CRM module. The CRM user selects an
auditor from a dropdown, then sees a month-view calendar. Every day that the
auditor is assigned to an audit stage is shown as blocked (highlighted). Clicking
a blocked day opens a detail card showing which client / stage that auditor is at.

**Zero changes to the existing technical system.** This is read-only — two new
endpoints appended to the existing CRM router, one new frontend page, and one
added nav item.

---

## Backend — `backend/audit_set/crm_router.py`

Append two new endpoints. Do **not** touch any existing endpoint.

### Imports to add at the top of crm_router.py

```python
from audit_set.db_models import AuditSetStage   # already imported indirectly — add explicitly
from auditors.models import Auditor, get_db as get_auditors_db
```

`AuditSetStage` lives in `audit_set.db_models`.
`Auditor` and `get_auditors_db` live in `auditors/models.py` (separate SQLAlchemy session
for the auditors database — import exactly as done in other routers like `api/routes/auditors.py`).

---

### Endpoint 1 — `GET /crm/auditors`

Returns all active auditors (id + name only — enough for the dropdown).

```python
class CRMAuditorRow(BaseModel):
    id:    str
    name:  str
    email: Optional[str]
    role:  Optional[str]

@router.get("/crm/auditors", response_model=list[CRMAuditorRow])
def crm_auditors(
    auditors_db: Session = Depends(get_auditors_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        raise HTTPException(403, "Not authorized")
    try:
        rows = (
            auditors_db.query(Auditor)
            .filter(Auditor.is_active == True)
            .order_by(Auditor.name)
            .all()
        )
        return [CRMAuditorRow(id=r.id, name=r.name, email=r.email, role=r.role) for r in rows]
    except Exception as exc:
        logger.error("[CRM] auditors DB error: %s", exc)
        return []
```

---

### Endpoint 2 — `GET /crm/auditors/{auditor_id}/calendar`

Returns every audit stage (with date range) that the given auditor is assigned to,
as lead auditor or as a team auditor.

```python
class CRMCalendarEntry(BaseModel):
    audit_set_id:  str
    plan_number:   int
    company_name:  str
    stage_type:    str          # e.g. "Stage 1", "Stage 2", "Surveillance"
    date_start:    str          # ISO "YYYY-MM-DD"
    date_end:      str          # ISO "YYYY-MM-DD" (same as start if single-day)
    auditor_role:  str          # "Lead Auditor" | "Team Auditor"

@router.get("/crm/auditors/{auditor_id}/calendar", response_model=list[CRMCalendarEntry])
def crm_auditor_calendar(
    auditor_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CRM_ROLES:
        raise HTTPException(403, "Not authorized")
    try:
        # Fetch all stages that have dates set
        stages = (
            db.query(AuditSetStage)
            .join(AuditSet, AuditSetStage.audit_set_id == AuditSet.id)
            .filter(AuditSetStage.audit_date_start.isnot(None))
            .all()
        )
    except Exception as exc:
        logger.error("[CRM] calendar DB error: %s", exc)
        return []

    result: list[CRMCalendarEntry] = []
    for stage in stages:
        # Check if this auditor is the lead
        is_lead = stage.lead_auditor_id == auditor_id
        # Check if auditor appears in the team JSON array
        team: list[dict] = stage.auditors or []
        is_team = any(str(m.get("id", "")) == auditor_id for m in team if isinstance(m, dict))
        if not (is_lead or is_team):
            continue

        audit_set = stage.audit_set  # use the relationship
        if not audit_set:
            continue

        date_start = stage.audit_date_start
        date_end   = stage.audit_date_end or date_start  # single-day if no end

        # Human-readable stage label
        stype = (stage.stage_type or "").lower()
        if "stage_1" in stype or stype == "stage1" or stype == "1":
            label = "Stage 1"
        elif "stage_2" in stype or stype == "stage2" or stype == "2":
            label = "Stage 2"
        elif "surveillance" in stype:
            label = "Surveillance"
        elif "recert" in stype:
            label = "Recertification"
        else:
            label = stage.stage_type or "Audit"

        result.append(CRMCalendarEntry(
            audit_set_id  = audit_set.id,
            plan_number   = audit_set.plan_number,
            company_name  = audit_set.company_name or "",
            stage_type    = label,
            date_start    = date_start.isoformat(),
            date_end      = date_end.isoformat(),
            auditor_role  = "Lead Auditor" if is_lead else "Team Auditor",
        ))

    result.sort(key=lambda r: r.date_start)
    return result
```

**Important:** `AuditSetStage` must have the `audit_set` relationship defined in
`db_models.py`. If it is not already there, add:
```python
# inside class AuditSetStage:
audit_set = relationship("AuditSet", back_populates="stages")
# inside class AuditSet:
stages = relationship("AuditSetStage", back_populates="audit_set", cascade="all, delete-orphan")
```
Check whether these relationships already exist before adding — do not duplicate.

---

## Frontend — new page `frontend/src/app/(app)/crm/calendar/page.tsx`

A self-contained month-view calendar page. No external calendar library — pure
Tailwind grid. Use `useState`, `useEffect`, and `api` (from `@/lib/api`) for
data fetching.

### Data types

```typescript
interface CRMAuditorRow {
  id:    string
  name:  string
  email: string | null
  role:  string | null
}

interface CRMCalendarEntry {
  audit_set_id:  string
  plan_number:   number
  company_name:  string
  stage_type:    string
  date_start:    string   // "YYYY-MM-DD"
  date_end:      string   // "YYYY-MM-DD"
  auditor_role:  string   // "Lead Auditor" | "Team Auditor"
}
```

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Auditor Calendar                                   │
│  Select auditor: [dropdown ▾]                       │
├─────────────────────────────────────────────────────┤
│  ← June 2026  →                                    │
│  Mon  Tue  Wed  Thu  Fri  Sat  Sun                 │
│  [ 1] [ 2] [ 3] [ 4] [ 5] [ 6] [ 7]               │
│  ...                                                │
│  blocked days shown with Certiva green background  │
│  click → popover shows assignment details          │
└─────────────────────────────────────────────────────┘
```

### Behaviour

1. On mount, fetch `GET /crm/auditors` and populate the dropdown.
2. When an auditor is selected, fetch `GET /crm/auditors/{id}/calendar`.
3. Build a Set of ISO date strings that fall within any entry's `date_start`..`date_end`
   range. A day is blocked if `date_start <= day <= date_end`.
4. Render a 7-column CSS grid (Mon–Sun). Pad leading empty cells for the first
   week of the month. Show 6 rows maximum (standard month grid).
5. Blocked days: `bg-[#1A4731] text-white rounded-lg cursor-pointer hover:bg-[#1A4731]/80`
6. Non-blocked days: `text-gray-700 rounded-lg hover:bg-gray-100 cursor-default`
7. Today: add a bottom-border ring even if not blocked.
8. **Click on a blocked day** — show a popover or inline detail card (not a modal)
   anchored below the cell. If multiple assignments cover that day, list all of them.
   Each entry shows:
   - Company name (bold)
   - `Stage 1 Audit · Lead Auditor` (or Team Auditor)
   - `#1234` plan number
   - Two action links: none needed (CRM is read-only)
   - Close button (×) or click outside to dismiss.

### State

```typescript
const [auditors, setAuditors]           = useState<CRMAuditorRow[]>([])
const [selectedId, setSelectedId]       = useState<string>('')
const [entries, setEntries]             = useState<CRMCalendarEntry[]>([])
const [loadingAuditors, setLoadingA]    = useState(true)
const [loadingEntries, setLoadingE]     = useState(false)
const [year, setYear]                   = useState(() => new Date().getFullYear())
const [month, setMonth]                 = useState(() => new Date().getMonth())  // 0-indexed
const [activeDay, setActiveDay]         = useState<string | null>(null)           // "YYYY-MM-DD"
```

### Helper: build calendar grid

```typescript
function buildGrid(year: number, month: number): (Date | null)[] {
  const first = new Date(year, month, 1)
  // Monday = 0 offset: (getDay() + 6) % 7
  const startPad = (first.getDay() + 6) % 7
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: (Date | null)[] = Array(startPad).fill(null)
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(new Date(year, month, d))
  }
  // Pad to multiple of 7
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
}
```

### Helper: which entries cover a given ISO date string

```typescript
function entriesForDay(day: string): CRMCalendarEntry[] {
  return entries.filter(e => e.date_start <= day && day <= e.date_end)
}
```

### Prev / Next month navigation

```typescript
function prevMonth() {
  if (month === 0) { setYear(y => y - 1); setMonth(11) }
  else setMonth(m => m - 1)
  setActiveDay(null)
}
function nextMonth() {
  if (month === 11) { setYear(y => y + 1); setMonth(0) }
  else setMonth(m => m + 1)
  setActiveDay(null)
}
```

---

## Frontend — Sidebar CRM nav item

In `frontend/src/components/layout/Sidebar.tsx`, add `CalendarDays` to the
lucide-react import and add a third entry to `CRM_NAV`:

```tsx
import {
  ...,
  CalendarDays,
} from 'lucide-react'

const CRM_NAV: NavItemProps[] = [
  { icon: BarChart3,   label: 'CRM Dashboard',     href: '/crm',          active: false },
  { icon: RefreshCw,   label: 'Clients',            href: '/crm/clients',  active: false },
  { icon: CalendarDays,label: 'Auditor Calendar',   href: '/crm/calendar', active: false },
]
```

---

## Checklist

- [ ] `GET /crm/auditors` works and returns active auditors sorted by name
- [ ] `GET /crm/auditors/{id}/calendar` returns entries for lead AND team assignments
- [ ] Both endpoints return 403 for non-CRM roles and empty array on DB error
- [ ] Calendar page loads auditor list on mount
- [ ] Selecting an auditor triggers calendar data fetch
- [ ] Blocked days highlighted correctly across multi-day ranges
- [ ] Clicking a blocked day shows assignment detail (company, stage, role, plan #)
- [ ] Multiple assignments on the same day all appear in the popover
- [ ] Prev/Next month navigation works; popover closes on navigation
- [ ] `CalendarDays` icon added to Sidebar CRM_NAV
- [ ] No changes to any non-CRM file except Sidebar.tsx (CRM_NAV addition only)
