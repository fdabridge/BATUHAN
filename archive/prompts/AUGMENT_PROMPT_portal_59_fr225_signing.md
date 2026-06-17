# Portal 59 — FR.225 Signing: Audit Team + Org Employee Slots

## What was wrong and what was actually fixed in the templates

The FR.225 Opening/Closing Meeting Form had four audit-team rows (Lead Auditor,
Auditor[0], Auditor[1], Technical Expert[0]) with **completely empty** Opening Signature
and Closing Signature cells. The cells existed in the table but contained nothing —
so pdfplumber detected no sig markers there, and the viewer showed those columns blank.

The DOCX templates (all 9 files — 3 standards × Stage 1 / Stage 2 / Surveillance)
have now been patched directly. Each audit-team row now has these markers:

| Row | Opening Signature cell | Closing Signature cell |
|-----|----------------------|----------------------|
| Lead Auditor | `[SIG:ORG_OPENING_LEAD_AUDITOR]` | `[SIG:ORG_CLOSING_LEAD_AUDITOR]` |
| Auditor[0] | `[SIG:ORG_OPENING_AUDITOR_0]` | `[SIG:ORG_CLOSING_AUDITOR_0]` |
| Auditor[1] | `[SIG:ORG_OPENING_AUDITOR_1]` | `[SIG:ORG_CLOSING_AUDITOR_1]` |
| Technical Expert[0] | `[SIG:ORG_OPENING_TE_0]` | `[SIG:ORG_CLOSING_TE_0]` |

The org-employee rows already had correct dynamic markers:
`[SIG:ORG_OPENING_{{ emp.sig_key }}]` / `[SIG:ORG_CLOSING_{{ emp.sig_key }}]`
(rendered as `[SIG:ORG_OPENING_ORG_EMP_{uuid}]` after docxtpl, already handled by
the existing `ORG_SIG_RE` branch in `viewer_router.py`).

This prompt wires the **new static audit-team markers** into the backend so they are
seeded and signable.

---

## Fix 1 — Seed audit-team slots when FR.225 is uploaded

**File:** `backend/audit_set/documents_router.py`

When a `meeting_form` document is uploaded, the existing `_seed_signature_slots` seeds
slots from `DOC_SIG_SLOTS["meeting_form"]`. But the audit-team slots are dynamic (the
number depends on how many auditors/TEs are on the stage). Extend the seeding logic
for `meeting_form` to also seed audit-team slots based on the stage.

After the standard `DOC_SIG_SLOTS` seeding, add:

```python
if document_type == "meeting_form":
    # Seed audit team signing slots based on stage team
    stage = db.query(AuditSetStage).filter_by(
        audit_set_id=doc.audit_set_id,
        stage_type=doc.stage_type,  # "stage_1" or "stage_2"
    ).first()
    
    if stage:
        # Determine which slots exist in this stage's team
        team_slots = []
        if stage.lead_auditor_id:
            team_slots += ["ORG_OPENING_LEAD_AUDITOR", "ORG_CLOSING_LEAD_AUDITOR"]
        auditors_list = stage.auditors or []
        for i, _ in enumerate(auditors_list):
            team_slots += [f"ORG_OPENING_AUDITOR_{i}", f"ORG_CLOSING_AUDITOR_{i}"]
        te_list = stage.technical_experts or []
        for i, _ in enumerate(te_list):
            team_slots += [f"ORG_OPENING_TE_{i}", f"ORG_CLOSING_TE_{i}"]
        
        # Seed each slot (avoid duplicates if re-uploading)
        existing = {
            vsp.sig_key
            for vsp in db.query(AuditDocumentSignature)
            .filter_by(document_id=doc.id).all()
        }
        for order_i, slot_key in enumerate(team_slots):
            if slot_key not in existing:
                db.add(AuditDocumentSignature(
                    id=str(uuid4()),
                    document_id=doc.id,
                    sig_key=slot_key,
                    role_label=slot_key.lower(),
                    order_index=100 + order_i,  # after org_rep slots
                    signed_at=None,
                ))
        db.commit()
```

---

## Fix 2 — viewer_router: handle audit-team sig keys

**File:** `backend/audit_set/viewer_router.py`

### 2a — Add regex for audit-team keys

Near the top of the file (next to the existing `ORG_SIG_RE`):

```python
ORG_EMP_RE   = re.compile(r'^ORG_(OPENING|CLOSING)_ORG_EMP_(.+)$')
ORG_TEAM_RE  = re.compile(r'^ORG_(OPENING|CLOSING)_(LEAD_AUDITOR|AUDITOR_(\d+)|TE_(\d+))$')
```

### 2b — In `_shared_slot_eligible` (eligibility check)

Add a block for `ORG_TEAM_RE` matches, after the existing `ORG_EMP_RE` block:

```python
m = ORG_TEAM_RE.match(sig_key)
if m:
    role_part = m.group(2)  # e.g. "LEAD_AUDITOR", "AUDITOR_0", "TE_1"
    # Current user must be an auditor with a linked profile
    if current_user.role != "auditor" or not current_user.auditor_id:
        return False
    
    # Load stage for this document
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=doc.audit_set_id, stage_type=doc.stage_type)
        .first()
    )
    if not stage:
        return False
    
    if role_part == "LEAD_AUDITOR":
        return current_user.auditor_id == stage.lead_auditor_id
    
    if role_part.startswith("AUDITOR_"):
        idx = int(role_part.split("_")[1])
        auditors = stage.auditors or []
        if idx >= len(auditors):
            return False
        return current_user.auditor_id == auditors[idx].get("id")
    
    if role_part.startswith("TE_"):
        idx = int(role_part.split("_")[1])
        tes = stage.technical_experts or []
        if idx >= len(tes):
            return False
        return current_user.auditor_id == tes[idx].get("id")
    
    return False
```

### 2c — In `_get_field_status` (status resolution)

Add a block for `ORG_TEAM_RE` matches, alongside the existing `ORG_EMP_RE` block:

```python
m = ORG_TEAM_RE.match(sig_key)
if m:
    # Check if already signed
    if vsp and vsp.signed_at:
        return _result("signed", vsp.signature_image)
    
    # Is this the current user's slot?
    if _shared_slot_eligible(sig_key, doc, current_user, db):
        return _result("current_user")
    
    # Determine display name for the legend
    role_part = m.group(2)
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=doc.audit_set_id, stage_type=doc.stage_type)
        .first()
    )
    label = sig_key  # fallback
    if stage:
        if role_part == "LEAD_AUDITOR":
            label = stage.lead_auditor_name or "Lead Auditor"
        elif role_part.startswith("AUDITOR_"):
            idx = int(role_part.split("_")[1])
            auditors = stage.auditors or []
            label = auditors[idx].get("name", f"Auditor {idx}") if idx < len(auditors) else sig_key
        elif role_part.startswith("TE_"):
            idx = int(role_part.split("_")[1])
            tes = stage.technical_experts or []
            label = tes[idx].get("name", f"Technical Expert {idx}") if idx < len(tes) else sig_key
    
    return _result("pending", label=label)
```

### 2d — Signing action for audit-team keys

In `sign_confirm`, the existing signing flow for non-org_rep slots uses the user's own
`UserSignature`. Audit-team slots (`ORG_TEAM_RE` matches) follow the same path — the
auditor signs with their own stored signature. No change needed to the signing action
itself; just ensure the `_assert_can_sign` gate reaches `_shared_slot_eligible` for
these keys (it should already, if the `ORG_TEAM_RE` block is added before the generic
fallthrough).

---

## Fix 3 — `DOC_SIG_SLOTS["meeting_form"]` base definition

**File:** `backend/audit_set/documents_router.py`

The base `DOC_SIG_SLOTS["meeting_form"]` should only define the org-employee org_rep
slot. The audit-team slots are seeded dynamically in Fix 1.

```python
"meeting_form": ["org_rep"],
```

If it currently lists something else, update it. The `org_rep` slot covers the org
employee rows (the `{%tr for emp in org_attendees %}` loop). The audit team slots are
seeded separately in Fix 1.

Note: the org-employee loop rows generate sig keys dynamically from `emp.sig_key`
(which is the `ClientOrgEmployee.id` UUID). These are handled by the existing
`ORG_EMP_RE` branch — no change needed there. The "fallback 3 blank rows" from
Portal 57 use `sig_key=""` and won't generate signable markers, which is correct —
blank rows are just visual placeholders until the client registers employees.

---

## Signing order for FR.225

FR.225 has no strict ordering requirement. All parties can sign in parallel:
- Lead auditor can sign `ORG_OPENING_LEAD_AUDITOR` / `ORG_CLOSING_LEAD_AUDITOR` anytime
- Auditor[0] can sign their slots anytime
- Technical Expert[0] can sign their slots anytime
- Client org employees sign their rows via the employee picker (existing ORG_EMP flow)

Do NOT apply the `_prior_slots_unsigned` blocking logic to FR.225 audit-team slots.
All slots should show as `current_user` immediately for the eligible signer.

---

---

## Fix 4 — Sig key migration aliases (fixes existing documents with renamed markers)

**File:** `backend/audit_set/viewer_router.py` (or wherever pdfplumber scan results
are stored as `VisualSignaturePlacement` records)

Several marker names were renamed in template fixes. Existing documents on Railway
still contain the OLD marker names. When pdfplumber scans them, it finds the old name
but the system now looks for the new name — no match — signature falls back to the
bottom of the page instead of the correct cell.

Add a normalization map that is applied when storing `VisualSignaturePlacement` records
after pdfplumber scan:

```python
# In viewer_router.py or wherever scan results are processed:
SIG_KEY_ALIASES = {
    "AUDITOR_MEMBER":   "ASSIGNED_AUDITOR",   # FR.224: renamed in template fix
    "CLIENT":           "ORG_REP",             # FR.223: renamed in template fix
    "CB_REVIEWER":      "APPOINTED_REVIEWER",  # FR.231/232: renamed in template fix
}

def normalize_sig_key(raw_key: str) -> str:
    """Normalize legacy sig key names to current names."""
    return SIG_KEY_ALIASES.get(raw_key, raw_key)
```

Apply `normalize_sig_key()` when pdfplumber returns a detected sig key before it is
stored in `VisualSignaturePlacement.sig_key`. This way old documents transparently
use the new key names without requiring re-upload.

Also apply when READING `VisualSignaturePlacement` records — if an existing record
already has an old key name (stored before this fix), normalize on read too:

```python
# When looking up visual placement for a sig_key:
placement = db.query(VisualSignaturePlacement).filter(
    VisualSignaturePlacement.document_id == doc_id,
    VisualSignaturePlacement.sig_key.in_([sig_key, *[k for k, v in SIG_KEY_ALIASES.items() if v == sig_key]])
).first()
```

This handles both directions: old records with old names, and new lookups for new names.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/documents_router.py` | After standard slot seeding for `meeting_form`, add dynamic team-slot seeding based on `AuditSetStage` team |
| `backend/audit_set/viewer_router.py` | Add `ORG_TEAM_RE`; add eligibility + status blocks for audit-team sig keys; add `SIG_KEY_ALIASES` normalization on scan store and lookup |

---

## Commit message

```
Portal 59: FR.225 audit team signing + sig key migration aliases

Templates were already patched (commit f5a0ade) to add:
  [SIG:ORG_OPENING_LEAD_AUDITOR] / [SIG:ORG_CLOSING_LEAD_AUDITOR]
  [SIG:ORG_OPENING_AUDITOR_N]   / [SIG:ORG_CLOSING_AUDITOR_N]
  [SIG:ORG_OPENING_TE_N]        / [SIG:ORG_CLOSING_TE_N]
to the previously-empty Opening/Closing Signature cells in audit team rows.

This commit wires them into the backend:
- documents_router: seed dynamic audit-team slots on meeting_form upload,
  based on the stage's lead_auditor_id / auditors / technical_experts
- viewer_router: ORG_TEAM_RE branch in _shared_slot_eligible and
  _get_field_status so each auditor can sign their own Opening/Closing slot;
  display name shown in legend from stage team data
- No ordering gate -- all FR.225 slots are independently signable

Fix 4 -- SIG_KEY_ALIASES migration (fixes signatures landing at page bottom):
Several sig markers were renamed in template fixes but existing Railway documents
still contain old names. pdfplumber finds old name, viewer looks for new name,
no VisualSignaturePlacement match, signature falls to page bottom.
- viewer_router: SIG_KEY_ALIASES map + normalize_sig_key() applied on pdfplumber
  scan store AND on VisualSignaturePlacement lookup (check both old+new key names)
- Aliases covered: AUDITOR_MEMBER->ASSIGNED_AUDITOR (FR.224),
  CLIENT->ORG_REP (FR.223/FR.211), CB_REVIEWER->APPOINTED_REVIEWER (FR.231/232)
- No re-upload required; old documents resolve transparently
```
