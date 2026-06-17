# Portal 76 — Report Reviewer from Auditor Pool (FR.231 / FR.232)

## Goal

Replace the Certification Manager as the party-2 signer of FR.231 and FR.232
with a designated **Report Reviewer** who is selected from the auditor pool.
The reviewer must cover at least one of the audit's standards.  After the Lead
Auditor signs, the assigned reviewer gets a dashboard notification, opens the
report from their auditor portal, and signs it via OTP.  A CM/admin bypass
remains for exceptional cases.

---

## Root cause / design

`AuditSetAuditReport` has `reviewer_signed_at` but no pointer to *who* the
reviewer is.  The current code in `report_router.py` allows any CB staff who
has an `AuditSetCommitteeMember` row with `role="reviewer"`, or any
`certification_manager` / `admin` / `executive` directly.

The new design:

1. Add `reviewer_auditor_id` (FK → auditors.id) + `reviewer_auditor_name`
   (denormalized) to `AuditSetAuditReport`.
2. Planner assigns a reviewer auditor per report via a new endpoint.
3. The reviewer is an auditor who has `AuditorStandardQualification` rows that
   overlap with `AuditSet.standards` (using the same `_STD_CODE_TO_ISO` map
   already in `committee_router.py`).
4. `_check_reviewer_auth` is extended to accept the assigned auditor.
5. After LA signs, notify the auditor reviewer via the existing
   `send_audit_report_review_request` email.
6. Auditor portal "Reports" tab shows a "Sign as Reviewer" button when the
   logged-in auditor is the designated reviewer and the report is
   `pending_review`.
7. Planner's `AuditReportSection` gains an "Assign Reviewer" control.

---

## Files to change

| File | What changes |
|------|-------------|
| `backend/audit_set/db_models.py` | 2 new columns on `AuditSetAuditReport` |
| `backend/audit_set/report_router.py` | New assign endpoint, extended auth, reviewer notification |
| `frontend/src/components/ui/AuditReportSection.tsx` | Assign-reviewer UI for planner |
| `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Sign-as-reviewer UI in auditor Reports tab |

No migration file needed — add the columns with `server_default=None` and
`nullable=True`; Railway's Alembic auto-apply will pick them up.

---

## Change 1 — `backend/audit_set/db_models.py`

### Edit 1 — add two columns to `AuditSetAuditReport` (after `uploaded_by`)

**BEFORE:**
```python
    uploaded_by  = Column(String, nullable=True)   # PlatformUser.id of uploader
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
```

**AFTER:**
```python
    uploaded_by  = Column(String, nullable=True)   # PlatformUser.id of uploader

    # ── Assigned Report Reviewer (Portal 76) ──────────────────────────────────
    # Auditor assigned by the planner to review this report.
    # Must cover at least one of the audit's standards.
    reviewer_auditor_id   = Column(String, nullable=True)   # Auditor.id (auditors DB)
    reviewer_auditor_name = Column(String, nullable=True)   # denormalized full name

    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
```

---

## Change 2 — `backend/audit_set/report_router.py`

### Edit 1 — extend imports (top of file, after existing imports)

Add to the existing `from audit_set.db_models import (...)` block:
```python
from audit_set.db_models import (
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember,
    AuditSetStage, AuditSetStatusEvent, get_db,
)
```
Also add after that block:
```python
from auditors.models import Auditor, AuditorStandardQualification
```

---

### Edit 2 — add `_STD_CODE_TO_ISO` constant (after the `VALID_FORMS` line)

**BEFORE:**
```python
VALID_FORMS = {"FR.231", "FR.229", "FR.232"}
```

**AFTER:**
```python
VALID_FORMS = {"FR.231", "FR.229", "FR.232"}

# Portal 76 — maps AuditSet.standards abbreviations to ISO standard names
# (same mapping as committee_router._STD_CODE_TO_ISO).
_STD_CODE_TO_ISO: dict[str, str] = {
    "QMS":   "ISO 9001",
    "EMS":   "ISO 14001",
    "OHSMS": "ISO 45001",
    "FSMS":  "ISO 22000",
    "ISMS":  "ISO 27001",
    "MDQMS": "ISO 13485",
    "ENMS":  "ISO 50001",
    "ABMS":  "ISO 37001",
}
```

---

### Edit 3 — extend `_report_dict` to include reviewer info

**BEFORE:**
```python
def _report_dict(r: AuditSetAuditReport, can_review: bool = False) -> dict:
    return {
        "id":                 r.id,
        "audit_set_id":       r.audit_set_id,
        "stage_type":         r.stage_type,
        "report_form":        r.report_form,
        "label":              r.label,
        "file_name":          r.file_name,
        "status":             r.status,
        "la_signed_at":       r.la_signed_at.isoformat() if r.la_signed_at else None,
        "reviewer_signed_at": r.reviewer_signed_at.isoformat() if r.reviewer_signed_at else None,
        "created_at":         r.created_at.isoformat() if r.created_at else None,
        "can_review":         can_review,
    }
```

**AFTER:**
```python
def _report_dict(r: AuditSetAuditReport, can_review: bool = False) -> dict:
    return {
        "id":                     r.id,
        "audit_set_id":           r.audit_set_id,
        "stage_type":             r.stage_type,
        "report_form":            r.report_form,
        "label":                  r.label,
        "file_name":              r.file_name,
        "status":                 r.status,
        "la_signed_at":           r.la_signed_at.isoformat() if r.la_signed_at else None,
        "reviewer_signed_at":     r.reviewer_signed_at.isoformat() if r.reviewer_signed_at else None,
        "created_at":             r.created_at.isoformat() if r.created_at else None,
        "can_review":             can_review,
        # Portal 76 — reviewer assignment
        "reviewer_auditor_id":    r.reviewer_auditor_id,
        "reviewer_auditor_name":  r.reviewer_auditor_name,
    }
```

---

### Edit 4 — replace `_check_reviewer_auth` (currently ~line 349)

**BEFORE:**
```python
def _check_reviewer_auth(
    report: AuditSetAuditReport,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetCommitteeMember:
    """Verify current user is the appointed committee reviewer for this audit set."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "CB access only")

    member = _get_committee_reviewer(report.audit_set_id, current_user, db)
    if not member:
        raise HTTPException(
            403,
            "You are not the appointed committee reviewer for this audit set. "
            "Contact an admin to assign or reassign the reviewer role.",
        )
    return member
```

**AFTER:**
```python
def _check_reviewer_auth(
    report: AuditSetAuditReport,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Verify current user may sign the reviewer slot.

    Priority order:
    1. Admin / certification_manager / executive — always allowed (bypass).
    2. Auditor whose auditor_id matches report.reviewer_auditor_id.
    3. CB staff member who is the appointed AuditSetCommitteeMember reviewer
       (backward-compat fallback).
    """
    # 1. Admin/CM bypass
    if current_user.role in ("admin", "certification_manager", "executive"):
        return

    # 2. Assigned auditor reviewer
    if current_user.role == "auditor":
        if not report.reviewer_auditor_id:
            raise HTTPException(
                403,
                "No reviewer has been assigned to this report yet. "
                "Ask a planner to assign a reviewer.",
            )
        if current_user.auditor_id != report.reviewer_auditor_id:
            raise HTTPException(
                403, "You are not the assigned reviewer for this report."
            )
        return

    # 3. Legacy CB committee reviewer fallback
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorised to review this report.")
    member = _get_committee_reviewer(report.audit_set_id, current_user, db)
    if not member:
        raise HTTPException(
            403,
            "You are not the appointed committee reviewer for this audit set. "
            "Contact an admin to assign or reassign the reviewer role.",
        )
```

---

### Edit 5 — replace `review_sign_direct` auth check (currently ~line 492)

**BEFORE:**
```python
    # Portal 75 — Certification Manager, admin and executive can approve directly.
    # Other CB roles must be a registered Committee Reviewer for this audit set.
    if current_user.role not in ("admin", "executive", "certification_manager"):
        reviewer = _get_committee_reviewer(audit_set_id, current_user, db)
        if not reviewer:
            raise HTTPException(403, "You are not a registered reviewer for this audit set")
```

**AFTER:**
```python
    # Portal 76 — use unified auth: admin/CM bypass, assigned auditor, or
    # legacy committee-reviewer fallback.
    if current_user.role not in ("admin", "executive", "certification_manager"):
        report_pre = db.query(AuditSetAuditReport).filter_by(
            id=rid, audit_set_id=audit_set_id
        ).first()
        if report_pre:
            _check_reviewer_auth(report_pre, current_user, db)
```

---

### Edit 6 — update LA-sign notification to use assigned reviewer (in `la_verify_otp`, ~line 292)

**BEFORE:**
```python
    # Notify the appointed committee reviewer
    reviewer = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, role="reviewer"
    ).first()
    if reviewer:
        try:
            audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
            send_audit_report_review_request(
                to=reviewer.user_email,
                full_name=reviewer.user_name,
                company_name=audit_set.company_name if audit_set else audit_set_id,
                stage_label=report.stage_type.replace("_", " ").title(),
                report_form=report.report_form,
                label=report.label,
            )
        except Exception:
            pass
```

**AFTER:**
```python
    # Portal 76 — notify the assigned reviewer auditor (preferred) or the
    # legacy AuditSetCommitteeMember reviewer (fallback).
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    _notify_reviewer(db, report, audit_set)
```

And add this helper function **before** `la_request_otp` (i.e. after the
`_check_la_auth` function, ~line 212):

```python
def _notify_reviewer(
    db: Session,
    report: AuditSetAuditReport,
    audit_set,
) -> None:
    """Send review-request email to the assigned reviewer (auditor or committee member)."""
    company = (audit_set.company_name if audit_set else report.audit_set_id) or ""
    stage   = report.stage_type.replace("_", " ").title()

    # Prefer assigned auditor reviewer (Portal 76)
    if report.reviewer_auditor_id:
        from auditors.models import Auditor as _Auditor
        auditor = db.query(_Auditor).filter_by(id=report.reviewer_auditor_id).first()
        if auditor and auditor.email:
            try:
                send_audit_report_review_request(
                    to=auditor.email,
                    full_name=auditor.name,
                    company_name=company,
                    stage_label=stage,
                    report_form=report.report_form,
                    label=report.label,
                )
            except Exception:
                pass
            return

    # Fallback: legacy committee reviewer
    reviewer = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=report.audit_set_id, role="reviewer"
    ).first()
    if reviewer:
        try:
            send_audit_report_review_request(
                to=reviewer.user_email,
                full_name=reviewer.user_name,
                company_name=company,
                stage_label=stage,
                report_form=report.report_form,
                label=report.label,
            )
        except Exception:
            pass
```

---

### Edit 7 — also remove the inline `audit_set = db.query(AuditSet)...` in `la_verify_otp` that is now handled by `_notify_reviewer`

In `la_verify_otp`, remove these lines (they are being replaced by the `_notify_reviewer` call in Edit 6):

**BEFORE (lines to remove):**
```python
    # Notify the appointed committee reviewer
    reviewer = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, role="reviewer"
    ).first()
    if reviewer:
        try:
            audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
            send_audit_report_review_request(
                to=reviewer.user_email,
                full_name=reviewer.user_name,
                company_name=audit_set.company_name if audit_set else audit_set_id,
                stage_label=report.stage_type.replace("_", " ").title(),
                report_form=report.report_form,
                label=report.label,
            )
        except Exception:
            pass
```

**AFTER:**
```python
    # Portal 76 — notify the assigned reviewer auditor (or legacy committee reviewer).
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    _notify_reviewer(db, report, audit_set)
```

---

### Edit 8 — add `list_audit_reports` logic to expose `can_review` to assigned auditor reviewer

**BEFORE:**
```python
    # Portal 75 — CM and admin/executive can review directly; other CB roles
    # need a committee-reviewer appointment to see the approve button.
    is_cm = current_user.role in ("certification_manager", "admin", "executive")
    is_reviewer = is_cm or (_get_committee_reviewer(audit_set_id, current_user, db) is not None)
```

**AFTER:**
```python
    # Portal 76 — CM/admin bypass, assigned auditor reviewer, or legacy committee reviewer.
    is_cm = current_user.role in ("certification_manager", "admin", "executive")
    is_assigned_reviewer = (
        current_user.role == "auditor"
        and current_user.auditor_id is not None
    )
    is_reviewer = (
        is_cm
        or is_assigned_reviewer  # can_review per-report determined below
        or (_get_committee_reviewer(audit_set_id, current_user, db) is not None)
    )
```

And update the return statement to pass the correct `can_review` per report:

**BEFORE:**
```python
    return [
        _report_dict(r, can_review=is_reviewer and r.status == "pending_review")
        for r in rows
    ]
```

**AFTER:**
```python
    def _can_review(r: AuditSetAuditReport) -> bool:
        if r.status != "pending_review":
            return False
        if is_cm:
            return True
        if is_assigned_reviewer:
            return (r.reviewer_auditor_id is not None
                    and current_user.auditor_id == r.reviewer_auditor_id)
        return is_reviewer  # legacy committee reviewer

    return [_report_dict(r, can_review=_can_review(r)) for r in rows]
```

---

### Edit 9 — add reviewer-assignment endpoint + eligible-auditors endpoint

Add these two new routes **after** the `download_audit_report` route (~line 182):

```python
# ── Reviewer assignment (Portal 76) ──────────────────────────────────────────

class AssignReviewerBody(BaseModel):
    auditor_id: str


@router.put("/audit-sets/{audit_set_id}/audit-reports/{rid}/reviewer")
def assign_reviewer(
    audit_set_id: str,
    rid:          str,
    body:         AssignReviewerBody,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Assign or re-assign a reviewer auditor to this report.

    The auditor must have at least one standard qualification overlapping with
    the audit set's standards.  Planner/admin only.
    """
    if current_user.role not in ("admin", "planner", "certification_manager", "executive"):
        raise HTTPException(403, "Planner or admin access required")

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from auditors.models import Auditor as _Auditor, AuditorStandardQualification as _ASQ
    auditor = db.query(_Auditor).filter_by(id=body.auditor_id).first()
    if not auditor:
        raise HTTPException(404, "Auditor not found")

    # Eligibility: auditor must cover at least one audit standard
    audit_iso = {_STD_CODE_TO_ISO.get(s, s) for s in (audit_set.standards or [])}
    if audit_iso:
        qualified_isos = {
            q.standard_code
            for q in db.query(_ASQ).filter_by(
                auditor_id=body.auditor_id, is_qualified=True
            ).all()
            if q.standard_code
        }
        # Normalise: strip "ISO " prefix and spaces for loose matching
        def _norm(s: str) -> str:
            return s.lower().replace("iso ", "").replace(" ", "").replace("/iec", "")
        audit_norms    = {_norm(s) for s in audit_iso}
        qualified_norms = {_norm(s) for s in qualified_isos}
        if not audit_norms.intersection(qualified_norms):
            raise HTTPException(
                400,
                f"Auditor '{auditor.name}' does not cover any of the required standards: "
                f"{', '.join(sorted(audit_set.standards or []))}."
            )

    report.reviewer_auditor_id   = auditor.id
    report.reviewer_auditor_name = auditor.name
    db.commit()
    db.refresh(report)
    return _report_dict(report)


@router.get("/audit-sets/{audit_set_id}/audit-reports/reviewer-candidates")
def get_reviewer_candidates(
    audit_set_id: str,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """List auditors eligible to be assigned as reviewer for this audit set.

    An auditor is eligible if they cover at least one standard of the audit.
    Auditors who already audit this set (lead or team) are still included —
    the planner can choose to exclude them manually.
    """
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "CB access only")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from auditors.models import Auditor as _Auditor, AuditorStandardQualification as _ASQ

    audit_iso = {_STD_CODE_TO_ISO.get(s, s) for s in (audit_set.standards or [])}

    def _norm(s: str) -> str:
        return s.lower().replace("iso ", "").replace(" ", "").replace("/iec", "")

    audit_norms = {_norm(s) for s in audit_iso}

    all_auditors = db.query(_Auditor).filter_by(is_active=True).all()
    results = []
    for a in all_auditors:
        qualifications = db.query(_ASQ).filter_by(
            auditor_id=a.id, is_qualified=True
        ).all()
        qualified_norms = {_norm(q.standard_code) for q in qualifications if q.standard_code}
        covers = not audit_norms or bool(audit_norms.intersection(qualified_norms))
        if covers:
            results.append({
                "id":             a.id,
                "name":           a.name,
                "email":          a.email,
                "standards":      [q.standard_code for q in qualifications if q.standard_code],
                "covers_audit":   covers,
            })
    results.sort(key=lambda x: x["name"] or "")
    return results
```

---

## Change 3 — `frontend/src/components/ui/AuditReportSection.tsx`

Full replacement of the file.  Key additions:
- `reviewer_auditor_id` / `reviewer_auditor_name` in the `AuditReport` interface
- "Assign Reviewer" button that opens an inline dropdown of eligible auditors
- Fetch `reviewer-candidates` on demand
- Update STATUS_CONFIG label: `pending_review` → "Awaiting Reviewer" (not CM)

**FULL FILE REPLACEMENT:**

```tsx
'use client'

import { useEffect, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import api from '@/lib/api'

interface AuditReport {
  id:                    string
  stage_type:            string
  report_form:           string
  label:                 string
  file_name:             string | null
  status:                string
  la_signed_at:          string | null
  reviewer_signed_at:    string | null
  can_review:            boolean
  created_at:            string
  reviewer_auditor_id:   string | null
  reviewer_auditor_name: string | null
}

interface ReviewerCandidate {
  id:          string
  name:        string
  email:       string
  standards:   string[]
  covers_audit: boolean
}

const STAGE_LABELS: Record<string, string> = {
  stage_1: 'Stage 1', stage_2: 'Stage 2',
  surveillance: 'Surveillance', recertification: 'Recertification',
}

const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
  pending_la:     { label: 'Awaiting Lead Auditor', chip: 'bg-amber-100 text-amber-700' },
  pending_review: { label: 'Awaiting Reviewer',     chip: 'bg-blue-100 text-blue-700' },
  approved:       { label: 'Approved',              chip: 'bg-green-100 text-green-700' },
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function AuditReportSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [reports, setReports]     = useState<AuditReport[]>([])
  const [loading, setLoading]     = useState(true)
  const [approving, setApproving] = useState<Record<string, boolean>>({})
  const [errors,    setErrors]    = useState<Record<string, string>>({})
  const [approveDates, setApproveDates] = useState<Record<string, string>>({})

  // Reviewer assignment state
  const [assigningFor,   setAssigningFor]   = useState<string | null>(null)  // report id
  const [candidates,     setCandidates]     = useState<ReviewerCandidate[]>([])
  const [loadingCands,   setLoadingCands]   = useState(false)
  const [selectedCand,   setSelectedCand]   = useState('')
  const [assigning,      setAssigning]      = useState(false)
  const [assignErr,      setAssignErr]      = useState('')

  const relevantStatuses = new Set([
    'stage1_in_progress', 'stage1_complete',
    'stage2_scheduled', 'stage2_in_progress',
    'audit_in_progress', 'under_review', 'certified',
  ])

  useEffect(() => {
    if (!workflowStatus || !relevantStatuses.has(workflowStatus)) {
      setLoading(false)
      return
    }
    api.get<AuditReport[]>(`/audit-sets/${auditSetId}/audit-reports`)
      .then(r => setReports(r.data))
      .finally(() => setLoading(false))
  }, [auditSetId, workflowStatus])

  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/audit-reports/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'report.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function handleApprove(id: string) {
    setApproving(a => ({ ...a, [id]: true }))
    setErrors(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = approveDates[id] || new Date().toISOString().slice(0, 10)
      const r = await api.post<AuditReport>(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/direct`,
        { signed_date }
      )
      setReports(prev =>
        prev.map(rpt => (rpt.id === id ? { ...rpt, ...r.data, can_review: false } : rpt))
      )
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErrors(e => ({ ...e, [id]: detail || 'Approval failed' }))
    } finally {
      setApproving(a => ({ ...a, [id]: false }))
    }
  }

  async function openAssignPanel(reportId: string) {
    if (assigningFor === reportId) { setAssigningFor(null); return }
    setAssigningFor(reportId)
    setSelectedCand('')
    setAssignErr('')
    setLoadingCands(true)
    try {
      const r = await api.get<ReviewerCandidate[]>(
        `/audit-sets/${auditSetId}/audit-reports/reviewer-candidates`
      )
      setCandidates(r.data)
    } catch {
      setCandidates([])
    } finally {
      setLoadingCands(false)
    }
  }

  async function handleAssign(reportId: string) {
    if (!selectedCand) return
    setAssigning(true)
    setAssignErr('')
    try {
      const r = await api.put<AuditReport>(
        `/audit-sets/${auditSetId}/audit-reports/${reportId}/reviewer`,
        { auditor_id: selectedCand }
      )
      setReports(prev => prev.map(rpt => rpt.id === reportId ? { ...rpt, ...r.data } : rpt))
      setAssigningFor(null)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAssignErr(detail || 'Assignment failed')
    } finally {
      setAssigning(false)
    }
  }

  return (
    <div className="mt-6">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
        Audit Reports (FR.231 / FR.229 / FR.232)
      </h2>

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : reports.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No reports uploaded yet. Lead Auditors upload from the Reports tab in their portal.
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map(r => {
            const cfg = STATUS_CONFIG[r.status] ?? { label: r.status, chip: 'bg-gray-100 text-gray-500' }
            const isPanelOpen = assigningFor === r.id

            return (
              <div
                key={r.id}
                className={`rounded-xl border bg-white p-4 ${r.can_review && r.status === 'pending_review' ? 'border-blue-200' : ''}`}
              >
                {/* Header row */}
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium text-gray-800 truncate">{r.label}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                      {r.la_signed_at && ` · LA signed ${fmtDate(r.la_signed_at)}`}
                      {r.reviewer_signed_at && ` · Reviewer approved ${fmtDate(r.reviewer_signed_at)}`}
                    </p>
                    {/* Reviewer assignment badge */}
                    <p className="mt-0.5 text-xs text-gray-500">
                      {r.reviewer_auditor_name
                        ? <>Reviewer: <span className="font-medium text-gray-700">{r.reviewer_auditor_name}</span></>
                        : <span className="text-amber-600">No reviewer assigned</span>
                      }
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                      {cfg.label}
                    </span>
                    <a
                      href={`/viewer/audit_report/${r.id}`}
                      className="flex items-center gap-1 text-xs text-[#1A4731] underline"
                    >
                      <ExternalLink size={11} />
                      View
                    </a>
                    <button type="button" onClick={() => download(r.id, r.file_name)}
                      className="text-xs text-[#1A4731] underline">
                      Download
                    </button>
                    {/* Assign Reviewer button — only before approval */}
                    {r.status !== 'approved' && (
                      <button
                        type="button"
                        onClick={() => openAssignPanel(r.id)}
                        className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                          isPanelOpen
                            ? 'border-gray-400 bg-gray-100 text-gray-700'
                            : 'border-[#1A4731] text-[#1A4731] hover:bg-green-50'
                        }`}
                      >
                        {r.reviewer_auditor_name ? 'Change Reviewer' : 'Assign Reviewer'}
                      </button>
                    )}
                  </div>
                </div>

                {/* Assign reviewer panel */}
                {isPanelOpen && (
                  <div className="mt-3 rounded-lg border border-dashed border-gray-300 bg-gray-50 p-3">
                    <p className="mb-2 text-xs font-medium text-gray-600">
                      Select reviewer from eligible auditors:
                    </p>
                    {loadingCands ? (
                      <p className="text-xs text-gray-400">Loading candidates…</p>
                    ) : candidates.length === 0 ? (
                      <p className="text-xs text-red-500">
                        No eligible auditors found for this audit's standards.
                      </p>
                    ) : (
                      <div className="flex items-center gap-2">
                        <select
                          value={selectedCand}
                          onChange={e => setSelectedCand(e.target.value)}
                          className="flex-1 rounded-lg border bg-white px-2 py-1.5 text-sm"
                        >
                          <option value="">— choose auditor —</option>
                          {candidates.map(c => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                        <button
                          type="button"
                          disabled={!selectedCand || assigning}
                          onClick={() => handleAssign(r.id)}
                          className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40 hover:bg-[#143828]"
                        >
                          {assigning ? 'Saving…' : 'Assign'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setAssigningFor(null)}
                          className="text-xs text-gray-400 hover:text-gray-600"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                    {assignErr && <p className="mt-1 text-xs text-red-500">{assignErr}</p>}
                  </div>
                )}

                {/* CM/reviewer direct-approve (existing — only for CB staff) */}
                {r.can_review && r.status === 'pending_review' && (
                  <div className="mt-2 flex items-end gap-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Approval date</label>
                      <input
                        type="date"
                        value={approveDates[r.id] || new Date().toISOString().slice(0, 10)}
                        onChange={e => setApproveDates(prev => ({ ...prev, [r.id]: e.target.value }))}
                        className="rounded-lg border px-2 py-1 text-sm"
                      />
                    </div>
                    <div>
                      <button
                        type="button"
                        onClick={() => handleApprove(r.id)}
                        disabled={approving[r.id]}
                        className="flex items-center gap-1.5 rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
                      >
                        {approving[r.id] && <span className="animate-spin text-sm">⟳</span>}
                        {approving[r.id] ? 'Approving…' : 'Approve Report'}
                      </button>
                      {errors[r.id] && (
                        <p className="mt-1 text-xs text-red-500">{errors[r.id]}</p>
                      )}
                    </div>
                  </div>
                )}
                {r.status === 'approved' && (
                  <p className="mt-1 text-sm font-medium text-green-600">Report approved ✓</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

---

## Change 4 — `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`

### What changes

In `AuditorReportsView`, the auditor must be able to see when they are the
designated reviewer and sign the report via OTP.

#### Edit 1 — extend the `reports` state type

**BEFORE:**
```tsx
  const [reports, setReports] = useState<{
    id: string; stage_type: string; report_form: string; label: string
    file_name: string | null; status: string
    la_signed_at: string | null; reviewer_signed_at: string | null
  }[]>([])
```

**AFTER:**
```tsx
  const [reports, setReports] = useState<{
    id: string; stage_type: string; report_form: string; label: string
    file_name: string | null; status: string
    la_signed_at: string | null; reviewer_signed_at: string | null
    can_review: boolean
    reviewer_auditor_id: string | null; reviewer_auditor_name: string | null
  }[]>([])
```

#### Edit 2 — add OTP signing state variables (after the `uploadMsg` state)

Add these state variables inside `AuditorReportsView`, after `const [uploadMsg, setUploadMsg] = useState('')`:

```tsx
  // Reviewer OTP signing state (Portal 76)
  const [reviewOtpStep,    setReviewOtpStep]    = useState<Record<string, 'idle'|'sent'|'signing'>>({})
  const [reviewOtp,        setReviewOtp]        = useState<Record<string, string>>({})
  const [reviewSignDate,   setReviewSignDate]   = useState<Record<string, string>>({})
  const [reviewErr,        setReviewErr]        = useState<Record<string, string>>({})
```

#### Edit 3 — add OTP signing handlers (after the `handleUpload` function)

Add these two functions inside `AuditorReportsView`, after `handleUpload`:

```tsx
  async function handleReviewRequestOtp(id: string) {
    setReviewOtpStep(s => ({ ...s, [id]: 'signing' }))
    setReviewErr(e => ({ ...e, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/request-otp`)
      setReviewOtpStep(s => ({ ...s, [id]: 'sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setReviewErr(e => ({ ...e, [id]: detail || 'Failed to send OTP' }))
      setReviewOtpStep(s => ({ ...s, [id]: 'idle' }))
    }
  }

  async function handleReviewVerifyOtp(id: string) {
    setReviewOtpStep(s => ({ ...s, [id]: 'signing' }))
    setReviewErr(e => ({ ...e, [id]: '' }))
    try {
      const signed_date = reviewSignDate[id] || new Date().toISOString().slice(0, 10)
      const r = await api.post(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/verify?otp=${encodeURIComponent(reviewOtp[id] || '')}`,
        { signed_date }
      )
      setReports(prev => prev.map(rpt => rpt.id === id ? { ...rpt, ...(r.data as object), can_review: false } : rpt))
      setReviewOtpStep(s => ({ ...s, [id]: 'idle' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setReviewErr(e => ({ ...e, [id]: detail || 'Verification failed' }))
      setReviewOtpStep(s => ({ ...s, [id]: 'sent' }))
    }
  }
```

#### Edit 4 — update the report card JSX to show reviewer signing UI

In the report card rendering for `uploaded` reports, find the section that renders each report card.  After the download button and before the closing `</div>` of each card, add the reviewer signing panel.

Find this pattern inside the `uploaded.map(...)` section:

```tsx
                    <button
                      type="button"
                      onClick={() => download(r.id, r.file_name)}
                      className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
                    >
                      Download
                    </button>
```

After that button (still inside the same card `<div>`), add:

```tsx
                    {/* Portal 76 — Reviewer signing panel */}
                    {r.can_review && r.status === 'pending_review' && (() => {
                      const step = reviewOtpStep[r.id] || 'idle'
                      return (
                        <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
                          <p className="mb-2 text-xs font-medium text-blue-800">
                            You are assigned as the reviewer for this report.
                          </p>
                          {step === 'idle' && (
                            <button
                              type="button"
                              onClick={() => handleReviewRequestOtp(r.id)}
                              className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white hover:bg-[#143828]"
                            >
                              Sign as Reviewer — Send OTP
                            </button>
                          )}
                          {step === 'sent' && (
                            <div className="space-y-2">
                              <p className="text-xs text-blue-700">
                                A verification code was sent to your email. Enter it below.
                              </p>
                              <div className="flex flex-wrap items-center gap-2">
                                <input
                                  type="text"
                                  placeholder="6-digit code"
                                  value={reviewOtp[r.id] || ''}
                                  onChange={e => setReviewOtp(ot => ({ ...ot, [r.id]: e.target.value }))}
                                  className="w-32 rounded-lg border px-2 py-1.5 text-sm"
                                />
                                <input
                                  type="date"
                                  value={reviewSignDate[r.id] || new Date().toISOString().slice(0, 10)}
                                  onChange={e => setReviewSignDate(d => ({ ...d, [r.id]: e.target.value }))}
                                  className="rounded-lg border px-2 py-1.5 text-sm"
                                />
                                <button
                                  type="button"
                                  onClick={() => handleReviewVerifyOtp(r.id)}
                                  disabled={!reviewOtp[r.id]}
                                  className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40 hover:bg-[#143828]"
                                >
                                  Confirm Signature
                                </button>
                              </div>
                            </div>
                          )}
                          {step === 'signing' && (
                            <p className="text-xs text-gray-500">Processing…</p>
                          )}
                          {reviewErr[r.id] && (
                            <p className="mt-1 text-xs text-red-500">{reviewErr[r.id]}</p>
                          )}
                        </div>
                      )
                    })()}
```

---

## What does NOT change

- `workflow_router.py` — gate already checks `la_signed_at` and `reviewer_signed_at`; no change
- FR.231 / FR.232 DOCX templates — `[SIG:CB_CERT_MANAGER]` marker stays (used by visual viewer
  for optional visual signature stamp; the OTP-based signing is the authoritative record)
- `viewer_router.py` — visual signing eligibility for `CB_CERT_MANAGER` slot stays unchanged
  (CM can still visually stamp their signature)
- `committee_router.py` — untouched
- `AuditSetCommitteeMember` — untouched; legacy `role="reviewer"` still works as fallback
- All other routes in `report_router.py` — untouched

---

## Alembic migration

No separate Alembic file is needed. The two new nullable columns on
`AuditSetAuditReport` are added with `nullable=True` and no server default, so
the autogenerate step on Railway will produce and apply the migration
automatically on next deploy.

---

## Commit message

```
Portal 76: report reviewer from auditor pool (FR.231 / FR.232)

Replace CM-only approval of audit reports with a designated reviewer
assigned from the auditor pool.  Reviewer must cover ≥1 audit standard.

Backend:
- AuditSetAuditReport: add reviewer_auditor_id + reviewer_auditor_name cols
- report_router: new PUT .../reviewer + GET .../reviewer-candidates endpoints
- _check_reviewer_auth: extended — admin/CM bypass, assigned auditor,
  legacy committee-reviewer fallback
- _report_dict: expose reviewer_auditor_id, reviewer_auditor_name
- _notify_reviewer: helper that emails auditor reviewer or falls back to
  legacy committee member
- list_audit_reports: can_review correctly set per-report for auditor reviewers

Frontend:
- AuditReportSection: "Assign Reviewer" panel with eligible-auditor dropdown
- auditor/audit/[id]/page.tsx: reviewer OTP signing UI in Reports tab
```
