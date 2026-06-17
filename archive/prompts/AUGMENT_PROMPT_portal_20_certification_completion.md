# Prompt 20 — Certification Completion: Closing the Lifecycle Loop

## Context

This is the Certiva CB (certification body) portal. The backend is FastAPI + SQLAlchemy; the frontend is Next.js 14 App Router. Everything is deployed on Railway from a single mono-repo.

Prompts 11–19 built the full ISO 17021-1 signing layer. Prompt 19 landed `AuditSetAuditReport` + `report_router.py`: the Lead Auditor (party 1) signs the audit report, then the appointed committee reviewer (party 2) approves it via OTP.

**The problem:** when the reviewer's `review_verify_otp` endpoint sets `report.status = "approved"`, it stops there. The `AuditSet.workflow_status` is never advanced to `"certified"`. `cert_issued_date` is never set. The client receives no notification. The CB portal shows no "what to do next" signal.

This prompt wires those pieces together. Two files change; no new tables, no new routes.

---

## Confirmed existing state

- `AuditSet.workflow_status` valid values end at `"under_review"` → `"certified"` (already documented in `db_models.py` lines 151–163).
- `AuditSet.cert_issued_date` is a `Column(Date, nullable=True)` already on the model (line 146).
- `AuditSetStatusEvent` is the correct status-history table (fields: `audit_set_id`, `from_status`, `to_status`, `triggered_by`, `triggered_at`, `notes`).
- `send_client_status_update(to, full_name, new_status, notes="")` already handles `"certified"` with a 🎉 label (email_service.py line 74).
- Client `PlatformUser` rows are found via `auth_db.query(PlatformUser).filter_by(audit_set_id=..., role="client").first()` — this is the established pattern.
- `get_auth_db` is already imported in `report_router.py` (line 29) but is NOT yet a parameter of `review_verify_otp`.
- `AuditSetStatusEvent` is NOT yet imported in `report_router.py` (current imports line 26–28 only pull `AuditSet`, `AuditSetAuditReport`, `AuditSetCommitteeMember`, `AuditSetStage`, `get_db`).

---

## Change 1 of 2 — `backend/audit_set/report_router.py`

### 1a. Add imports

Replace the existing import block at the top of the file:

```python
from audit_set.db_models import (
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember, AuditSetStage, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from email_service import send_audit_report_review_request, send_otp_code
```

with:

```python
from datetime import date as date_type

from audit_set.db_models import (
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember,
    AuditSetStage, AuditSetStatusEvent, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from email_service import (
    send_audit_report_review_request,
    send_client_status_update,
    send_otp_code,
)
```

Note: `datetime` is already imported earlier (`from datetime import datetime, timedelta`). Add `date as date_type` to that same import line instead of a second import if preferred — either way is fine. The key thing is that `date_type` (or `date`) is available for setting `cert_issued_date`.

### 1b. Add `auth_db` parameter to `review_verify_otp`

Current signature (line 356–363):

```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/verify")
def review_verify_otp(
    audit_set_id: str,
    rid: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
```

Replace with:

```python
@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/verify")
def review_verify_otp(
    audit_set_id: str,
    rid: str,
    otp: str,
    request: Request,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
```

### 1c. Auto-advance workflow after approval

The current end of `review_verify_otp` (lines 379–391) is:

```python
    report.reviewer_user_id      = current_user.id
    report.reviewer_signed_at    = datetime.utcnow()
    report.reviewer_signed_ip    = request.client.host if request.client else None
    report.reviewer_otp_hash     = None
    report.reviewer_otp_expires  = None
    report.status                = "approved"
    db.commit()

    return {
        "approved": True,
        "status": "approved",
        "reviewer_signed_at": report.reviewer_signed_at.isoformat(),
    }
```

Replace with:

```python
    report.reviewer_user_id      = current_user.id
    report.reviewer_signed_at    = datetime.utcnow()
    report.reviewer_signed_ip    = request.client.host if request.client else None
    report.reviewer_otp_hash     = None
    report.reviewer_otp_expires  = None
    report.status                = "approved"
    db.commit()

    # ── Auto-advance workflow: under_review → certified ───────────────────────
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if audit_set and audit_set.workflow_status == "under_review":
        audit_set.workflow_status  = "certified"
        audit_set.cert_issued_date = datetime.utcnow().date()
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id,
            from_status="under_review",
            to_status="certified",
            triggered_by=current_user.id,
            notes=f"Audit report '{report.report_form} — {report.label}' approved by committee reviewer.",
        ))
        db.commit()

        # Notify the linked client account (silent failure — best-effort)
        try:
            client_user = auth_db.query(PlatformUser).filter_by(
                audit_set_id=audit_set_id, role="client",
            ).first()
            if client_user:
                send_client_status_update(
                    to=client_user.email,
                    full_name=client_user.full_name,
                    new_status="certified",
                    notes="Your audit report has been reviewed and approved by the certification committee.",
                )
        except Exception:
            pass

    return {
        "approved": True,
        "status": "approved",
        "reviewer_signed_at": report.reviewer_signed_at.isoformat(),
        "workflow_advanced": audit_set.workflow_status == "certified" if audit_set else False,
    }
```

**Why `under_review` guard?** A single audit set can have multiple audit reports across stages (FR.231 initial + FR.229/FR.232 surveillance). Approving a surveillance report should NOT re-trigger the `certified` transition on an already-certified set. The guard ensures the transition happens exactly once.

---

## Change 2 of 2 — `frontend/src/app/(app)/clients/[id]/page.tsx`

### Add certification callout banner before SharedDocumentsSection

Find this block in the JSX (currently line ~1486–1487):

```tsx
      {/* Shared Documents — Prompt 07 (additive, bottom of page) */}
      <SharedDocumentsSection auditSetId={id} />
```

Replace with:

```tsx
      {/* Certification complete callout — Prompt 20 */}
      {data.workflow_status === 'certified' && (
        <div className="flex items-start gap-4 rounded-xl border border-emerald-300 bg-emerald-50 p-5">
          <span className="mt-0.5 text-2xl leading-none select-none">🎉</span>
          <div>
            <p className="font-semibold text-emerald-900 text-sm">
              Certification Issued
            </p>
            <p className="mt-1 text-sm text-emerald-800">
              The committee has approved the audit report and the workflow has advanced to{' '}
              <strong>Certified</strong>. Upload the signed certificate document using the{' '}
              <strong>Shared Documents</strong> section below — select{' '}
              <em>Certificate</em> as the document type. It will be released to the client
              portal automatically.
            </p>
            {data.cert_issued_date && (
              <p className="mt-2 text-xs text-emerald-700">
                Certificate issued: {formatDate(data.cert_issued_date)}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Shared Documents — Prompt 07 (additive, bottom of page) */}
      <SharedDocumentsSection auditSetId={id} />
```

The `data` object already has `cert_issued_date` typed and returned by `/audit-sets/{id}` (confirmed in `AuditSetResponse`). The `formatDate` helper is already defined at the top of the file (converts `YYYY-MM-DD` → `DD/MM/YYYY`).

---

## What is NOT changing

- No new database tables — `cert_issued_date` and `cert_issued_date` already exist as Column fields on `AuditSet`.
- No new API routes.
- No new emails — `send_client_status_update` already handles `"certified"` with the correct label and template.
- No changes to the client portal — `client/overview/page.tsx` already has a `certified` banner ("Your certificate has been issued. Download it from the Documents section") and already displays `cert_expiry_date`. The `cert_issued_date` is already in the interface and will now have a real value.
- No changes to `WorkflowStatusBar` — it already shows `certified` as the terminal step.
- No nav items.
- No `_safe_add_column` migration needed — `cert_issued_date` is a Column on the model body.

---

## Verification checklist

After implementing, confirm:

1. `npx tsc --noEmit` passes with no new errors.
2. `report_router.py` — `review_verify_otp` now has `auth_db` in its parameter list.
3. `report_router.py` — `AuditSetStatusEvent` is in the `from audit_set.db_models import (...)` block.
4. `report_router.py` — `send_client_status_update` is in the `from email_service import (...)` block.
5. `clients/[id]/page.tsx` — the `🎉` banner block sits immediately before `<SharedDocumentsSection auditSetId={id} />`.
6. No other files changed.

---

## Commit message

```
feat(portal): auto-advance to certified when committee approves audit report (Prompt 20)

- report_router.py: review_verify_otp adds auth_db dep; after report.status="approved",
  if workflow_status=="under_review" → advances to "certified", sets cert_issued_date,
  writes AuditSetStatusEvent, emails client via send_client_status_update
- clients/[id]/page.tsx: adds "Certification Issued" callout banner when
  workflow_status=="certified", placed directly above SharedDocumentsSection with
  instruction to upload certificate document
- No new tables, routes, or nav items
```
