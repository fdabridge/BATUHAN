# AUGMENT PROMPT — Portal 47: Full Pipeline State Machine
## Ordered Document Release · FR.218 Phase · Blank Set Delivery · Per-Auditor Documents · Stage Completion Triggers

---

## The Core Problem

The portal has documents, signatures, and a status bar — but no enforced pipeline. A planner can release documents in any order. FR.218 (Application Review) is never triggered after the agreement is signed, and the Certification Manager cannot see or sign it. When Stage 1 begins there is no blank set sent to the auditor, no per-auditor FR.224 instances, and nothing that automatically starts Stage 2 when Stage 1 completes.

This prompt rebuilds the workflow as a proper state machine: each phase has defined prerequisites, automatic side effects on entry, and automatic completion triggers. Documents are released only when the audit is at the right phase. Parties join the chat automatically. No phase can be skipped.

---

## A — Extended Status Machine

### A1 — New statuses

Add two new statuses between `agreement_signed` and `stage1_scheduled`:

```
agreement_signed → fr218_in_progress → fr218_complete → stage1_scheduled → ...
```

In `backend/audit_set/db_models.py` update the `workflow_status` comment:

```python
# Valid values:
#   pending_review      client submitted, CB reviewing
#   in_planning         CB approved, building the set
#   quotation_sent      FR.220 released to client
#   agreement_signed    FR.220 + FR.221 both fully signed
#   fr218_in_progress   Application review underway (FR.218 open)
#   fr218_complete      FR.218 fully signed by all parties — INTERNAL ONLY
#
#   --- Initial certification only ---
#   stage1_scheduled    Stage 1 auditors notified + blank set released
#   stage1_in_progress  Stage 1 audit underway
#   stage1_complete     Stage 1 done, gate to Stage 2
#   stage2_scheduled    Stage 2 auditors notified + blank set released
#   stage2_in_progress  Stage 2 audit underway
#
#   --- Surveillance / Recertification only ---
#   audit_scheduled     audit dates confirmed
#   audit_in_progress   audit underway
#
#   --- Shared closing ---
#   under_review        docs uploaded, committee reviewing
#   certified           certificate issued
```

### A2 — New VALID_TRANSITIONS in `backend/audit_set/workflow_router.py`

Add these entries (keep all existing entries):

```python
# Phase 2 — Application Review
("agreement_signed",   "fr218_in_progress"): {"admin"},          # auto-only, see B1
("fr218_in_progress",  "fr218_complete"):    {"admin"},          # auto-only, see B3
("fr218_complete",     "stage1_scheduled"):  {"admin", "planner"},
```

The `admin`-only on the first two is intentional — these transitions are fired automatically by the backend, not by a human clicking a button. Mark them clearly with a comment in code.

### A3 — Update `WorkflowStatusBar` INITIAL_STEPS

Insert the two new steps in `frontend/src/components/ui/WorkflowStatusBar.tsx`:

```typescript
const INITIAL_STEPS = [
  { key: 'pending_review',     label: 'Pending'     },
  { key: 'in_planning',        label: 'Planning'    },
  { key: 'quotation_sent',     label: 'Quotation'   },
  { key: 'agreement_signed',   label: 'Agreement'   },
  { key: 'fr218_in_progress',  label: 'App Review'  },
  { key: 'fr218_complete',     label: 'Review Done' },
  { key: 'stage1_scheduled',   label: 'Stage 1'     },
  { key: 'stage1_in_progress', label: 'S1 Audit'    },
  { key: 'stage1_complete',    label: 'S1 Done'     },
  { key: 'stage2_scheduled',   label: 'Stage 2'     },
  { key: 'stage2_in_progress', label: 'S2 Audit'    },
  { key: 'under_review',       label: 'Review'      },
  { key: 'certified',          label: 'Certified'   },
]
```

Update `INITIAL_PANELS` accordingly:

```typescript
fr218_in_progress: {
  heading: 'Application Review in Progress (FR.218)',
  body: 'The internal application review is underway. The Planning Officer prepares FR.218, then the Certification Manager signs off. This document is not visible to the client.',
},
fr218_complete: {
  heading: 'Application Review Complete ✓',
  body: 'FR.218 has been signed. Stage 1 can now be started. Auditors will be notified and blank stage documents will be sent automatically.',
  cta: { label: 'Start Stage 1', nextStatus: 'stage1_scheduled', allowedRoles: ['admin', 'planner'] },
},
```

---

## B — Phase Transition Side Effects (Auto-Triggers)

Create a new module `backend/audit_set/pipeline_triggers.py` with a function `fire_phase_triggers(audit_set_id: int, new_status: str, db: Session)`. Call this function at the end of `update_workflow_status` in `workflow_router.py`, after saving the new status.

```python
def fire_phase_triggers(audit_set_id: int, new_status: str, db: Session):
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        return

    if new_status == "agreement_signed":
        _trigger_fr218_phase(audit_set, db)

    elif new_status == "fr218_complete":
        # Nothing to auto-do here; planner clicks "Start Stage 1"
        pass

    elif new_status == "stage1_scheduled":
        _trigger_stage_start(audit_set, stage_number=1, db=db)

    elif new_status == "stage2_scheduled":
        _trigger_stage_start(audit_set, stage_number=2, db=db)

    elif new_status == "stage1_complete":
        _close_stage(audit_set, stage_number=1, db=db)

    db.commit()
```

### B1 — `_trigger_fr218_phase`

Fires when `agreement_signed` is reached. Auto-advances status to `fr218_in_progress` and creates the FR.218 document instance.

```python
def _trigger_fr218_phase(audit_set, db):
    # Auto-advance status to fr218_in_progress
    audit_set.workflow_status = "fr218_in_progress"

    # Create the FR.218 document instance if it doesn't already exist
    existing = db.query(AuditDocument).filter_by(
        audit_set_id=audit_set.id,
        document_type="fr218"
    ).first()

    if not existing:
        doc = AuditDocument(
            audit_set_id   = audit_set.id,
            document_type  = "fr218",
            display_name   = "FR.218 — Application Review Decision",
            phase          = "fr218",
            visible_to_client  = False,
            visible_to_auditor = False,
            status         = "pending",
            created_at     = datetime.utcnow(),
        )
        db.add(doc)

    # Add Certification Manager to the audit set chat
    _add_role_to_chat(audit_set, role="certification_manager", db=db)
    
    # Notify planner: FR.218 is ready to be prepared
    _notify(audit_set, role="planner", message="Agreement signed. Please prepare and sign FR.218 Application Review.")
    _notify(audit_set, role="certification_manager", message="A new application review (FR.218) requires your signature.")
```

### B2 — Signing triggers on FR.218 completion

The existing signature-completion logic already fires when all slots on a document are signed. Add a hook there:

In `backend/audit_set/documents_router.py` (or wherever signature completion is detected), when a document's last required signature is recorded, check if it is FR.218 and all required signers have signed. If yes:

```python
if document.document_type == "fr218" and _all_required_signed(document, db):
    audit_set.workflow_status = "fr218_complete"
    fire_phase_triggers(audit_set.id, "fr218_complete", db)
    _notify(audit_set, role="planner", message="FR.218 is fully signed. You can now start Stage 1.")
```

### B3 — `_trigger_stage_start(audit_set, stage_number, db)`

Fires when `stage1_scheduled` or `stage2_scheduled` is reached.

```python
def _trigger_stage_start(audit_set, stage_number: int, db):
    stage_type = f"stage_{stage_number}"
    
    # Get the AuditSetStage row for this stage
    stage = db.query(AuditSetStage).filter_by(
        audit_set_id=audit_set.id,
        stage_type=stage_type,
    ).first()
    if not stage:
        return

    # 1. Add auditors, TEs, observers to the chat
    for member in _get_stage_team(stage, db):
        _add_user_to_chat(audit_set, user_id=member.user_id, db=db)

    # 2. Create per-person FR.224 instances
    _create_per_auditor_fr224(audit_set, stage, stage_number, db)

    # 3. Release blank stage document package to auditors (hidden from client)
    _release_blank_set(audit_set, stage, stage_number, db)

    # 4. Notify each auditor
    for member in _get_stage_team(stage, db):
        _notify_user(member.user_id, f"Stage {stage_number} has begun. Check your portal for documents to fill and sign.")
```

---

## C — Document Gate System

Every document type has a minimum required workflow status. If a planner tries to release a document before the audit set has reached that status, the backend must reject it with a clear error.

Add a `DOCUMENT_GATES` dict in `backend/audit_set/documents_router.py`:

```python
DOCUMENT_GATES = {
    # Phase 1
    "fr220": ["in_planning", "quotation_sent", "agreement_signed",
               "fr218_in_progress", "fr218_complete",
               "stage1_scheduled", "stage1_in_progress", "stage1_complete",
               "stage2_scheduled", "stage2_in_progress", "under_review", "certified"],
    "fr221": None,  # gated dynamically: FR.220 must be fully signed first
    
    # Phase 2
    "fr218": ["fr218_in_progress", "fr218_complete",
               "stage1_scheduled", "stage1_in_progress", "stage1_complete",
               "stage2_scheduled", "stage2_in_progress", "under_review", "certified"],
    
    # Stage 1
    "fr222": ["stage1_scheduled", "stage1_in_progress", "stage1_complete",
               "stage2_scheduled", "stage2_in_progress", "under_review", "certified"],
    "fr223": ["stage1_scheduled", "stage1_in_progress", "stage1_complete",
               "stage2_scheduled", "stage2_in_progress", "under_review", "certified"],
    "fr224": ["stage1_scheduled", "stage1_in_progress", "stage1_complete",
               "stage2_scheduled", "stage2_in_progress", "under_review", "certified"],
    "fr225": ["stage1_in_progress", "stage1_complete",
               "stage2_in_progress", "under_review", "certified"],
    "fr230": ["stage1_in_progress", "stage1_complete",
               "stage2_in_progress", "under_review", "certified"],
    "fr231": ["stage1_in_progress", "stage1_complete", "under_review", "certified"],
    "fr211": ["stage1_in_progress", "stage1_complete",
               "stage2_in_progress", "under_review", "certified"],
    
    # Stage 2
    "fr232": ["stage2_in_progress", "under_review", "certified"],
    "fr229": ["stage2_in_progress", "under_review", "certified"],
}
```

In the "release document" endpoint, before creating the release:

```python
gate = DOCUMENT_GATES.get(document_type)
if gate and audit_set.workflow_status not in gate:
    raise HTTPException(
        status_code=400,
        detail=f"{document_type.upper()} cannot be released at this stage. "
               f"Current status: {audit_set.workflow_status}."
    )
```

Special case for FR.221: check that FR.220 is fully signed (both signers), not just that the status is right.

```python
if document_type == "fr221":
    fr220 = db.query(AuditDocument).filter_by(
        audit_set_id=audit_set_id, document_type="fr220"
    ).first()
    if not fr220 or not _all_required_signed(fr220, db):
        raise HTTPException(400, detail="FR.221 cannot be released until FR.220 is fully signed by both parties.")
```

**Frontend:** The document release buttons should visually indicate gates. If the current status doesn't satisfy the gate, show the button as disabled with a tooltip like "Available after agreement is signed" or "Available after FR.218 is approved". Do not just hide the button — show it greyed out with an explanation.

---

## D — FR.218 Phase: Auto-creation and CM Visibility

### D1 — FR.218 signature slots

FR.218 has the following signing sequence:

| Slot key | Role | Condition |
|----------|------|-----------|
| `fr218_planner` | `planner` | Always (prepares the review) |
| `fr218_reviewer` | `auditor` or `certification_manager` | Only if audit includes ISO 22000 or ISO 27001 — must NOT be on the audit team |
| `fr218_cm` | `certification_manager` | Always (final decision) |

When FR.218 is auto-created (in `_trigger_fr218_phase`), create these signature slots in `AuditDocumentSignature`:
- Slot 1: `signer_role_label = "fr218_planner"`, eligible roles: `["planner", "admin"]`
- Slot 2 (conditional): `signer_role_label = "fr218_reviewer"`, eligible roles: `["auditor", "certification_manager", "admin"]` — only create if audit standards include ISO 22000 or ISO 27001
- Last slot: `signer_role_label = "fr218_cm"`, eligible roles: `["certification_manager", "admin"]`

Slot 2 is blocked (not yet clickable) until Slot 1 is signed. Slot 3 is blocked until all previous slots are signed.

### D2 — Certification Manager portal — FR.218 visibility

The Certification Manager must see FR.218 prominently in their portal. Currently CM likely sees nothing specific — this must be fixed.

In the `frontend/src/app/(app)/clients/[id]/page.tsx` (and/or the CM-specific portal page if it exists), add a section `<Fr218Section>` that renders when:
- `audit_set.workflow_status` is in `["fr218_in_progress", "fr218_complete"]`
- AND the current user's role is `certification_manager`, `admin`, or `planner`

```tsx
<Fr218Section
  auditSetId={auditSet.id}
  currentUserRole={currentUser.role}
  document={auditSet.fr218_document}   // or fetched separately
/>
```

The section shows:
- Document title: "FR.218 — Application Review Decision"
- Download button for the FR.218 template
- Upload slot if planner hasn't uploaded the filled form yet
- Signature slots with the same click-to-sign UI as other documents
- Status: "Awaiting Planning Officer" / "Awaiting Certification Manager" / "Fully Signed ✓"

Do NOT show this section to clients or auditors (`visible_to_client = False`, `visible_to_auditor = False`).

### D3 — CM dashboard: pending signatures

Create a new component `<PendingSignaturesCard>` that the Certification Manager sees at the top of any audit set they're in. It lists every document waiting for their signature with a direct "Sign" button. Priority order:
1. FR.218 (if in fr218_in_progress phase and planner has signed)
2. FR.222 (if Stage 1 has started)

---

## E — Stage Entry: Blank Set + Per-Auditor FR.224

### E1 — Per-auditor FR.224

When `_trigger_stage_start` runs for Stage 1 (and again separately for Stage 2), create one FR.224 instance per team member:

```python
def _create_per_auditor_fr224(audit_set, stage, stage_number: int, db):
    team = _get_stage_team(stage, db)  # list of: lead_auditor + auditors + TEs + observers
    
    for member in team:
        # Check if FR.224 for this person already exists (idempotent)
        existing = db.query(AuditDocument).filter_by(
            audit_set_id   = audit_set.id,
            document_type  = "fr224",
            assignee_user_id = member.user_id,
            stage_number   = stage_number,
        ).first()
        if existing:
            continue

        doc = AuditDocument(
            audit_set_id      = audit_set.id,
            document_type     = "fr224",
            display_name      = f"FR.224 — Impartiality Declaration ({member.full_name})",
            phase             = f"stage{stage_number}",
            stage_number      = stage_number,
            assignee_user_id  = member.user_id,
            visible_to_client = False,
            visible_to_auditor= True,
            status            = "pending",
        )
        db.add(doc)
        db.flush()

        # One signature slot: the assigned team member signs their own FR.224
        slot = AuditDocumentSignature(
            document_id       = doc.id,
            slot_order        = 1,
            signer_role_label = "auditor_self",
            signer_user_id    = member.user_id,  # pre-assigned to the specific person
            eligible_roles    = json.dumps(["auditor", "lead_auditor", "admin"]),
        )
        db.add(slot)
```

**UI (Auditor Portal):** Each auditor sees only their own FR.224 instance. They click "Sign FR.224", the impartiality declaration opens, they fill in any required fields and sign. They do NOT see other auditors' FR.224 instances.

**Planner/Admin view:** Shows a FR.224 status table for the stage:
```
FR.224 Impartiality Declarations — Stage 1
  ✓ Hasan Eryılmaz (Lead Auditor)   — Signed 10 Jun 2026
  ✗ Aslan Aslan (Auditor)           — Pending
  ✗ Mehmet Yılmaz (Technical Expert)— Pending
```

### E2 — Blank set release

When a stage starts, the system automatically packages the blank template files for that stage and makes them visible to the stage's auditors and TEs (but NOT to the client).

```python
def _release_blank_set(audit_set, stage, stage_number: int, db):
    # Determine which blank templates belong to this stage
    stage1_templates = ["fr223", "fr225_opening", "fr225_closing", "fr231"]
    stage2_templates = ["fr223", "fr225_opening", "fr225_closing", "fr232", "fr229"]
    templates = stage1_templates if stage_number == 1 else stage2_templates

    for doc_type in templates:
        # Get the blank template file path from the template store
        template_path = _get_blank_template_path(doc_type, audit_set.accreditation_body)
        if not template_path:
            continue

        doc = AuditDocument(
            audit_set_id       = audit_set.id,
            document_type      = doc_type,
            display_name       = _get_template_display_name(doc_type),
            phase              = f"stage{stage_number}",
            stage_number       = stage_number,
            is_blank_template  = True,        # ← new flag: this is the blank version
            visible_to_client  = False,       # ← hidden from client
            visible_to_auditor = True,
            file_path          = template_path,
            status             = "released",
        )
        db.add(doc)
```

**Auditor portal:** Shows a "Stage 1 Documents" section with two tabs:
- **To Fill** — blank templates: FR.223, FR.225 (opening + closing), FR.231. Each has a "Download" button.
- **To Sign** — FR.224 (their own instance). Shows "Sign" button.

**Upload flow:** Auditor fills the documents offline, then returns to the portal and uploads the completed set. Each filled document replaces the blank:

```python
# When auditor uploads a filled document:
blank_doc = db.query(AuditDocument).filter_by(
    audit_set_id=audit_set.id,
    document_type=doc_type,
    is_blank_template=True,
    stage_number=stage_number,
).first()
if blank_doc:
    blank_doc.is_blank_template = False
    blank_doc.file_path = uploaded_file_path
    blank_doc.status = "filled"
    blank_doc.uploaded_by = current_user.id
    blank_doc.uploaded_at = upload_date or date.today()
```

After the auditor uploads, the system:
1. Marks the document as `filled`
2. Creates the appropriate signature slots (see Section F)
3. Makes the document visible to the client if the client must sign it (FR.223, FR.225)
4. Keeps it invisible to the client if it is auditor-only

---

## F — Document Signing Logic After Auditor Upload

When the auditor uploads a filled document, create the following signature slots automatically:

### FR.223 (Audit Plan)
- Slot 1: Lead auditor (if not already signed during preparation) — `lead_auditor`
- Slot 2: Client representative — `client_representative` (document becomes visible to client)

### FR.225 Opening Meeting
- One slot per named attendee in the form (see Section G)

### FR.225 Closing Meeting
- Same per-attendee slots

### FR.231 (Stage 1 Report)
- Slot 1: Lead auditor — `lead_auditor`
- Slot 2 (conditional): Certification committee reviewer — `committee_reviewer` — only if audit includes ISO 22000 or ISO 27001

### FR.232 / FR.229 (Stage 2 Report)
- Same as FR.231 but for Stage 2

### FR.230 (NC Notification — if any NCs)
- Slot 1: Lead auditor — `lead_auditor`
- Slot 2: Client representative — `client_representative`

---

## G — FR.225 Meeting Attendees and Guest Signatures

FR.225 (Opening + Closing Meeting) includes a list of attendees who must sign. Attendees are a mix of audit team and client-side guests.

### How it works:

1. **Auditor fills the FR.225** form offline with the full attendee list (names and titles pre-filled in the document).

2. **Auditor uploads** the filled FR.225 to the portal.

3. **System parses the uploaded document** to extract the attendee rows, OR (simpler): after the auditor uploads, a UI step asks the lead auditor to confirm the attendee list in the portal by entering names one by one. This creates the signature slots.

4. **Auditor team members** (who have accounts) sign directly via their own portal sessions using the existing click-to-sign flow.

5. **Guest attendees** (client-side, no account, no OTP) sign via the client organization's portal session:
   - The client portal shows a "Meeting Attendees" section listing all attendees by name and title
   - Each row has a "Sign" button
   - Any logged-in user on the client account can sign any guest row (they are signing on behalf of that person using the organization's session)
   - Guest rows do NOT require an OTP or separate login
   - Auditors do NOT see guest signature slots in their view

### Implementation:

Add a `MeetingAttendeeSignatureSection` component. When FR.225 is in status `filled`:
- The lead auditor sees a form to add attendee names: "Add attendee → Name, Title, Organization, Auditor/Client side"
- Each auditor-side attendee is linked to their user account (signer_user_id set)
- Each client-side attendee is a free-text name (no user account), signer_user_id = null, signed via client portal

```typescript
type Attendee = {
  id: string
  name: string
  title: string
  organization: string
  side: 'auditor' | 'client_guest'
  user_id: string | null      // null for guests
  signed_at: string | null
}
```

Client portal rendering:
```
Opening Meeting — Attendees

  [Auditor Team]
  ✓ Hasan Eryılmaz  (Lead Auditor)   — Signed 10 Jun 2026
  ✗ Aslan Aslan     (Auditor)        — Awaiting

  [Company Representatives]
  ✗ Ahmet Yılmaz    (Quality Manager) — [ Sign ]
  ✗ Fatma Kaya      (Production Mgr)  — [ Sign ]
```

When a guest clicks "Sign", the standard signing flow opens (draw/type signature, enter signing date). The signature is recorded against the attendee row, not against a user account. No OTP is sent.

---

## H — Stage Completion Auto-Triggers

### H1 — Stage 1 completion

Stage 1 is complete when ALL of:
1. FR.231 is fully signed (lead auditor + reviewer if applicable)
2. FR.211 (Auditor Assessment) is submitted AND signed by the client

Check after every signature save. If both conditions are met:

```python
def _check_stage1_completion(audit_set, db):
    fr231 = _get_document(audit_set.id, "fr231", db)
    fr211 = _get_document(audit_set.id, "fr211", stage_number=1, db=db)

    fr231_done = fr231 and _all_required_signed(fr231, db)
    fr211_done = fr211 and fr211.status == "submitted" and _all_required_signed(fr211, db)

    if fr231_done and fr211_done:
        audit_set.workflow_status = "stage1_complete"
        stage1_row = db.query(AuditSetStage).filter_by(
            audit_set_id=audit_set.id, stage_type="stage_1"
        ).first()
        if stage1_row:
            stage1_row.status = "complete"
        _notify(audit_set, role="planner", message="Stage 1 is complete. You can now schedule Stage 2.")
        db.commit()
```

### H2 — FR.211 (Auditor Assessment) — client-only, auditor blind

FR.211 must be released SOLO to the client. The auditor must NEVER see it.

When Stage 1 reaches `stage1_in_progress` status AND FR.231 is signed:
1. System auto-releases FR.211 blank template to the client portal
2. `visible_to_client = True`, `visible_to_auditor = False`
3. Client downloads, fills offline, uploads the filled version, then signs
4. When client signs FR.211 → system calls `_check_stage1_completion`

In the document visibility query, add a hard filter: if the requesting user's role is `auditor` or `lead_auditor`, NEVER return FR.211 documents regardless of any other visibility logic.

### H3 — Stage 2 completion

Same as Stage 1 but:
- FR.232 or FR.229 (not FR.231) must be signed
- FR.211 (Stage 2 version) must be signed by client

When complete → `stage2_complete` → system prompts planner to appoint the Certification Committee.

---

## I — Stage 2 with a Different Audit Team

Stage 2 may have completely different auditors, TEs, and observers from Stage 1.

When `stage2_scheduled` is triggered:
1. Fetch the `AuditSetStage` row with `stage_type = "stage_2"` (created at audit set creation, may have different lead_auditor_id, different team)
2. Add only Stage 2 team members to the chat (not Stage 1 team again, unless they overlap)
3. Create FR.224 instances for each Stage 2 team member separately (even if the same person was in Stage 1 — they sign a fresh declaration for Stage 2)
4. Release Stage 2 blank set: FR.223 (new audit plan for Stage 2), FR.225 opening, FR.225 closing, FR.232 or FR.229
5. Stage 1 team members remain in the chat (do not remove them) — they can still view history

---

## J — What Auditors See vs. Do NOT See

Enforce these visibility rules at the API level. All document-list endpoints must apply role-based filtering before returning results.

| Document | Auditor sees? | Client sees? | Notes |
|----------|--------------|--------------|-------|
| FR.218 | ❌ Never | ❌ Never | CB internal only |
| FR.220, FR.221 | ❌ Never | ✅ Yes | Quotation/Agreement |
| FR.222 | ❌ Never | ❌ Never | CB internal only |
| FR.211 | ❌ **Never** | ✅ Yes (solo) | Hard-block at API |
| Blank set | ✅ Yes (only their stage) | ❌ Never | Blank templates for auditor |
| Filled set (FR.223, FR.225, FR.231/232) | ✅ Yes | ✅ Yes (after upload) | Released to client after upload |
| FR.224 | ✅ Own only | ❌ Never | Each auditor sees only theirs |
| FR.230 | ✅ Yes | ✅ Yes | NC form — both see it |

**Hard-block rule for FR.211:** In every endpoint that returns documents or document content, add:

```python
if document.document_type == "fr211" and current_user.role in ("auditor", "lead_auditor", "technical_expert"):
    raise HTTPException(403, detail="Access denied.")
```

---

## K — Existing Records: Migration/Backfill

Some audit sets may already be at `agreement_signed` before this deploy. On server startup (or via a one-time migration script), scan for any audit set at `agreement_signed` that does NOT have an FR.218 document. For each one, run `_trigger_fr218_phase` to auto-create the FR.218 and advance the status to `fr218_in_progress`.

```python
# In backend startup or as a migration:
stale = db.query(AuditSet).filter_by(workflow_status="agreement_signed").all()
for audit_set in stale:
    fr218_exists = db.query(AuditDocument).filter_by(
        audit_set_id=audit_set.id, document_type="fr218"
    ).first()
    if not fr218_exists:
        _trigger_fr218_phase(audit_set, db)
db.commit()
```

---

## L — WorkflowStatusBar — Update All Gate Allowlists

All existing section components that gate on workflow status must include the new statuses. Apply the same pattern as Portal 30 Change 4, extending every `STAGES` allowlist to include `fr218_in_progress` and `fr218_complete`:

Search for any component with arrays like:
```js
const SOME_STAGES = ['agreement_signed', 'stage1_scheduled', ...]
```
And add `'fr218_in_progress'` and `'fr218_complete'` in the correct position.

---

## Verification Checklist

### Phase 1 → FR.218

- [ ] Both FR.220 and FR.221 are signed → status auto-advances to `fr218_in_progress` without any button press
- [ ] FR.218 document auto-appears in the portal for planner and CM — not visible to client or auditor
- [ ] Planner can sign FR.218 planner slot
- [ ] CM sees FR.218 in their portal with a "Pending Signatures" card
- [ ] CM can sign FR.218 CM slot
- [ ] After all FR.218 slots signed → status auto-advances to `fr218_complete`
- [ ] `fr218_complete` status shows "Start Stage 1" CTA for planner

### Stage 1 Entry

- [ ] Planner clicks "Start Stage 1" → status → `stage1_scheduled`
- [ ] Stage 1 auditors and TEs are automatically added to the chat
- [ ] Blank FR.223, FR.225 (opening + closing), FR.231 templates released to auditor portal (not visible to client)
- [ ] Per-auditor FR.224 instances created (one per team member) — each person sees only their own
- [ ] Auditor portal shows "Stage 1 Documents" with "To Fill" and "To Sign" tabs

### Auditor workflow

- [ ] Auditor downloads blank FR.223, FR.225, FR.231
- [ ] Auditor signs their FR.224
- [ ] Auditor uploads filled FR.223 → client can now see and sign FR.223
- [ ] Auditor uploads filled FR.225 → attendee signature rows appear on client portal
- [ ] Guest attendee clicks "Sign" on client portal — no OTP required — signature recorded
- [ ] Auditor uploads FR.231 → signing slots created → lead auditor signs

### FR.211

- [ ] FR.211 blank released to client ONLY after FR.231 is signed — auditors cannot see it
- [ ] Client downloads, fills, uploads, signs FR.211
- [ ] After FR.211 signed → Stage 1 auto-completes

### Stage 2 with different auditors

- [ ] Planner configures Stage 2 with a different lead auditor + team
- [ ] `stage2_scheduled` triggers: Stage 2 team added to chat
- [ ] New FR.224 instances created for Stage 2 team (separate from Stage 1 FR.224s)
- [ ] Stage 2 blank set (FR.223, FR.225, FR.232) released to Stage 2 auditors

### Document gates

- [ ] Trying to release FR.221 before FR.220 is fully signed → clear error message
- [ ] Trying to release FR.222 before `stage1_scheduled` → clear error with tooltip
- [ ] FR.211 endpoint returns 403 if called by auditor/TE regardless of audit set

### Existing audit sets

- [ ] Any audit set already at `agreement_signed` gets auto-migrated to `fr218_in_progress` on deploy
