# Portal 84 — FR.233: Fix committee member rendering + certification gate

## Root-cause summary

Two separate bugs prevent FR.233 from working correctly:

### Bug 1 — Committee names never rendered in the DOCX

`fr233_generator.py` currently does a two-pass render:

**Pass 1 (docxtpl):** calls `DocxTemplate.render({"committee_members": ctx})` expecting a `{%tr for member in committee_members %}` Jinja2 loop in the template DOCX. But the actual template at `uaf_blank_set/9-14-45-22-5001/İlk Belgelendirme/Aşama 2/FR.233 Review And Decision Form R5&09.10.2025.docx` has **zero docxtpl tags**. The XML was never patched with the loop syntax. Result: `tpl.render(...)` is a no-op; the template comes out unchanged with empty name/EA-code cells.

**Pass 2 (python-docx):** fills Table 0 metadata only (project number, company name, dates, etc.). It never touches Table 3.

Table 3 structure (confirmed by inspection):
- Row 0: header — `['', Name Surname(merged 1-2), EA Code(merged 3-4), Sign(5)]`
- Row 1: `['Chairperson', '', '', '', '', '  ']` — name at col 1, EA at col 3, sign at col 5
- Row 2: `['Member', '', '', '', '', '  ']` — same layout
- Row 3: `['Member', '', '', '', '', '  ']` — same layout
- Row 6: `['Certification Manager Approval'(merged 0-1), ''(merged 2-3), Sign(merged 4-5)]`

Additionally, **no `[SIG:COMMITTEE_CHAIR]` / `[SIG:COMMITTEE_MEMBER_1]` / `[SIG:COMMITTEE_MEMBER_2]` / `[SIG:CERT_MANAGER_FR233]` markers are written anywhere**. Without those markers in the rendered DOCX, the viewer's lazy field-extraction pipeline creates zero `DocumentSignatureField` rows, so:
- `committee_total = 0` (query returns 0 sig fields)
- The `committee_total > 0` guard in `viewer_router.py` is never satisfied
- CM signing never advances the status to `certified` via the viewer path

### Bug 2 — Certification can proceed without any FR.233 signatures

`WorkflowStatusBar.tsx` SURVEILLANCE_PANELS `under_review` CTA fires `PATCH /audit-sets/{id}/workflow-status` with `{workflow_status: "certified"}`. The `update_workflow_status` endpoint in `workflow_router.py` validates the transition `("under_review", "certified")` — it's in `VALID_TRANSITIONS` — and then advances immediately with no FR.233 gate. An admin/executive can mark an audit as certified without any committee or CM signature.

---

## Change 1 — `backend/audit_set/fr233_generator.py`

### 1a. Replace Pass 1 (docxtpl no-op) with a direct python-docx fill of Table 3

**Remove** the docxtpl pass entirely. The `render_fr233_bytes` function becomes a **single-pass** python-docx render.

Replace the entire `render_fr233_bytes` function with:

```python
def render_fr233_bytes(audit_set, db: Session) -> bytes:
    """Render FR.233 bytes.

    Single-pass python-docx render:
      - Table 0: project metadata (plan number, company, dates, audit team).
      - Table 3: committee member names, EA codes, and [SIG:...] markers so the
        viewer's lazy field-extraction pipeline can place signatures.

    The docxtpl pass has been removed: the template has no Jinja2 tags.
    """
    template_path = _resolve_fr233_template(audit_set)
    if template_path is None:
        raise RuntimeError("FR.233 template not found for this audit set")

    doc = Document(str(template_path))

    stages = {s.stage_type: s for s in (audit_set.stages or [])}
    stage1 = stages.get("stage_1")
    stage2 = stages.get("stage_2")
    auditors = [p for p in (audit_set.personnel or {}).get("auditors", []) if p.get("name")]
    team_str = ", ".join(
        f"{a['name']} (Lead Auditor)" if a.get("is_lead") else a["name"]
        for a in auditors
    )

    if len(doc.tables) >= 1:
        _safe_fill_table0(doc.tables[0], audit_set, team_str, stage1, stage2)

    if len(doc.tables) >= 4:
        members_ctx = _build_committee_context(audit_set)
        _fill_table3_committee(doc.tables[3], members_ctx)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

### 1b. Add `_fill_table3_committee` function

Add this new function **before** `render_fr233_bytes` (i.e., after `_safe_fill_table0`):

```python
def _fill_table3_committee(t3, members_ctx: list[dict]) -> None:
    """Fill Table 3 committee rows with member names, EA codes, and [SIG:...] markers.

    Table 3 layout (confirmed):
      Row 0: headers
      Row 1: Chairperson — col 1 = name (merged 1-2), col 3 = EA codes (merged 3-4), col 5 = sign
      Row 2: Member 1   — same column layout
      Row 3: Member 2   — same column layout
      Row 6: Certification Manager — col 4 = sign (merged 4-5)

    Sig keys assigned positionally:
      members_ctx[0] (chairperson) → COMMITTEE_CHAIR
      members_ctx[1]               → COMMITTEE_MEMBER_1
      members_ctx[2]               → COMMITTEE_MEMBER_2
    """
    _SIG_KEYS = ["COMMITTEE_CHAIR", "COMMITTEE_MEMBER_1", "COMMITTEE_MEMBER_2"]
    _COMMITTEE_ROWS = [1, 2, 3]  # row indices in Table 3

    for slot_idx, member in enumerate(members_ctx[:3]):
        row_idx = _COMMITTEE_ROWS[slot_idx]
        if row_idx >= len(t3.rows):
            break
        row = t3.rows[row_idx]
        cells = row.cells
        if len(cells) < 6:
            continue

        name = member.get("name") or ""
        ea_codes = member.get("ea_codes_str") or ""
        sig_key = _SIG_KEYS[slot_idx]

        # col 1 — name (merged with col 2 in the template; writing col 1 _tc is sufficient)
        _set_cell_text(cells[1]._tc, name)
        # col 3 — EA codes (merged with col 4; writing col 3 _tc is sufficient)
        _set_cell_text(cells[3]._tc, ea_codes)
        # col 5 — signature marker
        _set_cell_text(cells[5]._tc, f"[SIG:{sig_key}]")

    # Row 6 — Certification Manager sign cell (col 4, merged with col 5)
    if len(t3.rows) > 6:
        cm_row = t3.rows[6]
        if len(cm_row.cells) > 4:
            _set_cell_text(cm_row.cells[4]._tc, "[SIG:CERT_MANAGER_FR233]")
```

### 1c. Remove the `docxtpl` import

The `DocxTemplate` import is no longer needed. Remove this line from the imports at the top of the file:

```python
from docxtpl import DocxTemplate
```

The final import block should be:

```python
from __future__ import annotations

import copy
from datetime import date
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from sqlalchemy.orm import Session

from audit_set.resolver import resolve_document_set
```

---

## Change 2 — `backend/audit_set/workflow_router.py`

### 2a. Add `_assert_fr233_signed_gate` function

Add this new function **after** `_assert_stage1_complete_gate` (before the `WorkflowUpdateSchema` class definition, around line 194):

```python
def _assert_fr233_signed_gate(db: Session, audit_set_id: str) -> None:
    """
    Gate for any transition → certified via the manual workflow button.
    Blocks certification until the FR.233 Review & Decision Form has been
    fully signed by all committee members and the Certification Manager.

    The FR.233 record is created when the document is generated; its status
    advances: "pending" → "signing" (first committee member signs) → "complete"
    (CM signs after all committee members have signed, in viewer_router).

    This gate is intentionally skipped for the jump endpoint (retroactive
    corrections by admin) — only the normal PATCH transition checks it.
    """
    from audit_set.db_models import AuditSetFR233Record
    record = db.query(AuditSetFR233Record).filter_by(audit_set_id=audit_set_id).first()
    if not record:
        raise HTTPException(
            409,
            "Gate not met: FR.233 Review & Decision Form has not been generated. "
            "Generate FR.233 and collect all committee and Certification Manager "
            "signatures before issuing a certificate.",
        )
    if record.status != "complete":
        raise HTTPException(
            409,
            f"Gate not met: FR.233 Review & Decision Form is not fully signed "
            f"(current status: '{record.status}'). All committee members and the "
            "Certification Manager must sign FR.233 before certification can be issued.",
        )
```

### 2b. Call the gate in `update_workflow_status`

In `update_workflow_status`, the current gate block is:

```python
    if to_status == "stage1_in_progress":
        _assert_stage_entry_gate(db, audit_set_id, "stage_1")
    elif to_status == "stage2_in_progress":
        _assert_stage1_complete_gate(db, audit_set_id)
```

Add the FR.233 gate as a third branch:

```python
    if to_status == "stage1_in_progress":
        _assert_stage_entry_gate(db, audit_set_id, "stage_1")
    elif to_status == "stage2_in_progress":
        _assert_stage1_complete_gate(db, audit_set_id)
    elif to_status == "certified":
        _assert_fr233_signed_gate(db, audit_set_id)
```

This gate fires for **all** `→ certified` transitions in VALID_TRANSITIONS:
- `("under_review", "certified")` — surveillance and legacy initial
- *(No `committee_review → certified` transition exists in VALID_TRANSITIONS; initial certification reaches `certified` only via the viewer CM-sign path, which has its own committee_total > 0 gate — that path is unaffected)*

The `jump_workflow_status` endpoint does **not** call this gate (intentional — retroactive admin corrections should not be blocked by FR.233 status).

---

## What does NOT change

- `_safe_fill_table0` — unchanged; still fills Table 0 metadata exactly as before.
- `_build_committee_context` — unchanged; still reads `audit_set.committee_members` JSON snapshot, sorts chairperson first, and falls back to 3 blank rows.
- `committee_router.py` — unchanged; `generate_fr233` / `get_fr233_status` logic untouched.
- `viewer_router.py` — unchanged; the CM-sign gate (`committee_total > 0 and committee_signed >= committee_total`) is the correct guard for the viewer path. With Bug 1 fixed, the template will now contain `[SIG:COMMITTEE_CHAIR]` etc., the viewer will extract them as `DocumentSignatureField` rows, `committee_total` will be > 0, and the guard will work correctly.
- `FR233Panel.tsx` — unchanged; already shows at `under_review` and surfaces the "Sign as Certification Manager" link correctly once `allSigned` is true.
- `WorkflowStatusBar.tsx` — unchanged; the "Issue Continuation Certificate" CTA still exists as a fallback, but the backend gate added in Change 2 will now reject it with HTTP 409 if FR.233 is incomplete. The frontend will surface this as an error toast.
- All surveillance pipeline changes (Portal 82/83) — unchanged.
- Template DOCX files — **not modified**; the python-docx generator writes directly into the rendered output bytes, it does not modify the blank templates on disk.

---

## Why this approach is safe

**No docxtpl dependency for FR.233 going forward.** The template has never had Jinja2 tags and we are not adding them. Direct python-docx cell filling (the same technique used for Table 0 via `_safe_fill_table0`) is deterministic, doesn't depend on undocumented OOXML loop expansion, and leaves the source template files untouched.

**`_set_cell_text` handles merged cells correctly.** When two adjacent cells are merged in DOCX XML (they share a `<w:tc>` element), `cells[1]._tc` and `cells[2]._tc` return the same underlying XML element. Writing to `cells[1]._tc` is sufficient — `cells[2]` reflects the same write.

**The gate is additive.** The new `_assert_fr233_signed_gate` function raises HTTP 409 only; it does not change any database state. The jump endpoint remains ungated so retroactive admin corrections are unaffected.

---

## Verification checklist (post-deploy)

1. Create a surveillance audit set, save a committee (≥ 1 person).
2. Advance to `under_review`. Click "Generate FR.233" in the FR233 panel.
3. Open the generated FR.233 in the viewer.
   - Confirm the committee member's name and EA codes appear in Table 3.
   - Confirm clickable `[SIG:COMMITTEE_CHAIR]` slot is visible.
4. Sign as committee member (COMMITTEE_CHAIR slot).
5. Confirm FR233Panel shows `allSigned: true` → "Sign as Certification Manager" link appears.
6. Sign as Certification Manager (CERT_MANAGER_FR233 slot).
7. Confirm workflow_status advances to `certified` automatically (via viewer_router path).
8. **Gate test:** create a second audit set, reach `under_review`, do NOT sign FR.233, click "Issue Continuation Certificate" → confirm HTTP 409 error toast: "FR.233 Review & Decision Form has not been generated."
9. Generate FR.233 for that set but do NOT sign it → click "Issue Continuation Certificate" again → confirm 409: "FR.233 is not fully signed (current status: 'pending')".

---

## Commit message suggestion

```
Portal 84: fix FR.233 committee rendering + gate certification on FR.233 completion

- fr233_generator: drop no-op docxtpl pass (template has no Jinja2 tags);
  add _fill_table3_committee() — writes member names, EA codes, and
  [SIG:COMMITTEE_CHAIR/MEMBER_1/MEMBER_2/CERT_MANAGER_FR233] markers
  directly into Table 3 via python-docx; remove docxtpl import
- workflow_router: add _assert_fr233_signed_gate(); call it on any
  → certified transition in update_workflow_status (jump endpoint
  remains ungated for retroactive admin corrections)
```
