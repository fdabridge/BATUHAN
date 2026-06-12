# AUGMENT PROMPT — Portal 49b: Full Certification Pipeline Rebuild

## Already Shipped — DO NOT Rebuild or Revert

The following was delivered in commit **c9e5cb6** (Portal 49a Parts 1–3). Treat
this as baseline. Do not recreate, replace, or undo any of it:

| Feature | Files | Status |
|---|---|---|
| `ClientOrgEmployee` model + CRUD API | `db_models.py`, `employee_router.py` | ✅ shipped |
| Client portal `/client/employees` roster page | `frontend/.../client/employees/page.tsx` | ✅ shipped |
| FR.225 org-attendee docxtpl loop in all 9 templates | `update_fr225_org_attendee_rows.py` + all FR.225 `.docx` | ✅ shipped |
| `_build_org_attendees()` in `filler.py` + packager | `filler.py`, `packager.py` | ✅ shipped |
| `ORG_OPENING_*` / `ORG_CLOSING_*` sig key handling | `viewer_router.py` | ✅ shipped |
| `AuditSetFR233Record` model | `db_models.py` | ✅ shipped |
| FR.233 generate + GET endpoints | `committee_router.py`, `fr233_generator.py` | ✅ shipped |
| Committee signing `[SIG:COMMITTEE_CHAIR/MEMBER_1/MEMBER_2]` | `viewer_router.py` | ✅ shipped |
| CM signs `[SIG:CERT_MANAGER_FR233]` → `workflow_status="certified"` | `viewer_router.py` | ✅ shipped |
| Auto-certify shortcut **removed** (no longer triggers on CB_REVIEWER sign) | `viewer_router.py` | ✅ shipped |
| `FR233Panel` frontend component | `components/ui/FR233Panel.tsx` | ✅ shipped |
| FR.233 panel mounted on audit set detail page | `app/(app)/clients/[id]/page.tsx` | ✅ shipped |
| `field_maps.py` `FR233_MAP` + `FR225_MAP` | `field_maps.py` | ✅ shipped |
| `resolver.py` FR.233 in Stage_2 + Surveillance | `resolver.py` | ✅ shipped |

---

## Purpose

This prompt rebuilds the **remaining** Certiva ISO audit certification workflow phases
to match the definitive 14-phase flowchart confirmed on 2026-06-12. Phases 13 (FR.233
committee) and the org-employee FR.225 signing are complete. Every other phase,
every other signing party, and every other visibility rule is specified below. Treat
this as the single source of truth. Where existing code contradicts this prompt, update
the code.

---

## Integrated Flow: Gate Chain, Access, and Signing Keys

This is the authoritative single-page reference. The phase descriptions below expand
on each row. Implement the gates as hard checks — not UI hints.

### Gate Chain (nothing proceeds until the prior gate is met)

```
STATUS                   GATE TO ENTER                                           WHO TRIGGERS
─────────────────────────────────────────────────────────────────────────────────────────────
in_planning              CB creates audit set                                    Planner
quotation_sent           [SIG:CLIENT] placed on FR.220                          auto on sign
                         ↳ gate: [SIG:GM] must be placed first
agreement_signed         [SIG:CLIENT] placed on FR.221                          auto on sign
                         ↳ gate: [SIG:GM] must be placed first
                         ↳ gate: FR.220 must be fully signed (both GM + Client)
fr218_in_progress        auto-seeded when agreement_signed                      pipeline_triggers
fr218_complete           ALL required FR.218 slots signed                       auto on last sign
                         ↳ slots: CB_PLANNER + CB_CERT_MANAGER (+ CB_REVIEWER if FSMS/ISMS)
stage1_in_progress       CB Planner advances manually after:                    Planner button
                         ↳ FR.222 signed by CB_PLANNER + CB_CERT_MANAGER
                         ↳ ALL Stage 1 FR.224s signed by their assigned auditors
                         ↳ FR.223 (Stage 1) signed by ORG_REP
stage1_complete          FR.231 signed (+ REVIEWER if FSMS/ISMS)               auto on last sign
stage2_in_progress       CM clicks "Stage 1 appropriate" after:                 Cert Manager button
                         ↳ ALL Stage 2 FR.224s signed by their assigned auditors
                         ↳ FR.223 (Stage 2) signed by ORG_REP
stage2_complete          FR.232 (or FR.229 for ISMS) signed (+ REVIEWER)       auto on last sign
                         ↳ does NOT auto-advance to certified (committee must happen)
committee_review         Planner generates FR.233                               auto on generate
certified                [SIG:CERT_MANAGER_FR233] placed on FR.233             auto on sign
                         ↳ gate: all [SIG:COMMITTEE_*] slots must be placed first
```

### Portal Access Matrix (who can see and act at each status)

```
PORTAL           CAN SEE AUDIT SET?  DOCUMENTS VISIBLE
───────────────────────────────────────────────────────────────────────────────
CB (any role)    Always              All document types
Auditor          From assignment     audit_plan (FR.223), meeting_form (FR.225),
                 (Phase 1 onward)    nc_form (FR.230), stage1_report (FR.231),
                                     stage2_report (FR.232/FR.229),
                                     team_info (FR.224) — OWN ONLY
                                     NEVER: quotation, agreement, audit_programme,
                                            fr218, assessment (FR.211), review_decision (FR.233)
Client           Always              quotation (FR.220), agreement (FR.221),
                                     audit_plan (FR.223), meeting_form (FR.225),
                                     nc_form (FR.230), assessment (FR.211 — own uploads),
                                     certificate
                                     NEVER: audit_programme (FR.222), fr218, team_info (FR.224),
                                            stage1_report, stage2_report, review_decision (FR.233)
```

### Signing Key → Role Resolution

Every sig key in the viewer must resolve to EXACTLY one authorised user. Reject with
403 if the requester does not match. Order-gating (slot A must be signed before slot B
can be signed) must be enforced server-side.

```
SIG KEY                  WHO CAN SIGN                        ORDER GATE
─────────────────────────────────────────────────────────────────────────────────────────
[SIG:GM]                 role == "gm"                        none (first)
[SIG:CLIENT]             role == "client" AND                after [SIG:GM] on same doc
                         client_user_id == audit_set.client_user_id
[SIG:CB_PLANNER]         role == "planner"                   none (first)
[SIG:CB_REVIEWER]        role == "reviewer"                  after [SIG:CB_PLANNER]
[SIG:CB_CERT_MANAGER]    role == "cert_manager"              after [SIG:CB_PLANNER]
[SIG:ORG_REP]            role == "client"                    none (first on FR.223/FR.230)
                         AND client_user_id == audit_set.client_user_id
[SIG:ASSIGNED_AUDITOR]   auditor_id in stage team            none; auditor's own FR.224 only
                         AND doc.assigned_auditor_id == current_user.auditor_id
[SIG:LEAD_AUDITOR]       auditor_id == stage.lead_auditor_id none (first)
[SIG:REVIEWER]           role == "reviewer"                  after [SIG:LEAD_AUDITOR]
                         AND reviewer is appointed for this audit
ORG_OPENING_ORG_EMP_*   role == "client"                    none; employee belongs to client
ORG_CLOSING_ORG_EMP_*   (already shipped — do not change)
[SIG:COMMITTEE_CHAIR]    AuditSetCommitteeMember.role ==     none
                         "decision_maker" AND user_id match  (already shipped — do not change)
[SIG:COMMITTEE_MEMBER_1] AuditSetCommitteeMember (2nd row)  none
[SIG:COMMITTEE_MEMBER_2] AuditSetCommitteeMember (3rd row)  none
[SIG:CERT_MANAGER_FR233] role == "cert_manager"             after ALL COMMITTEE_* slots signed
                         (already shipped — do not change)
```

### Document → Sig Slots → Gate Summary

```
DOCUMENT         TYPE              SLOTS (ordered)                         VISIBILITY
──────────────────────────────────────────────────────────────────────────────────────────
FR.220           quotation         GM → CLIENT                             CB + Client
FR.221           agreement         GM → CLIENT (gate: FR.220 complete)     CB + Client
FR.218           fr218             CB_PLANNER → CB_REVIEWER* → CB_CERT_MANAGER   CB only
FR.222           audit_programme   CB_PLANNER → CB_CERT_MANAGER           CB only
FR.224           team_info         ASSIGNED_AUDITOR (one per auditor doc)  CB + that auditor only
FR.223           audit_plan        ORG_REP                                 CB + Client + Auditors
FR.225           meeting_form      LEAD_AUDITOR + auditor rows +           Everyone
                                   ORG_OPENING/CLOSING per emp (c9e5cb6)
FR.230           nc_form           LEAD_AUDITOR → ORG_REP                  Everyone
FR.231/FR.231-1  stage1_report     LEAD_AUDITOR → REVIEWER*               CB + Auditors
FR.232/FR.229    stage2_report     LEAD_AUDITOR → REVIEWER*               CB + Auditors
FR.211           assessment        CLIENT (client uploads + signs)         CB + Client only
FR.233           review_decision   COMMITTEE_* → CERT_MANAGER (c9e5cb6)   CB only
Certificate      certificate       (no signature)                          Everyone
```
*REVIEWER slot only present when standards include ISO 22000 / FSSC 22000 / ISO 27001

---

## Critical Global Rules (apply everywhere)

1. **No OTP anywhere.** Remove all OTP-based signing from the document workflow.
   All document signatures use the visual signature system (`POST /viewer/sign/confirm`
   with a saved signature image). This includes FR.224, FR.225, FR.230, FR.231, FR.232,
   FR.229, and FR.233 — every document in the system uses visual signing only.
2. **Source of truth for templates:** `uaf_blank_set copy/` is the canonical template
   folder. After any template change, sync its contents to `backend/uaf_blank_set/`
   so the Docker image stays current. Run:
   ```bash
   rsync -av --delete "uaf_blank_set copy/" "backend/uaf_blank_set/"
   ```
3. **Blank set path:** `settings.py` default `blank_set_path` must point to
   `./uaf_blank_set` (used in Docker). Locally override with
   `BLANK_SET_PATH=/Users/batuhan/BATUHAN/uaf_blank_set copy`.
4. `field_maps.py` and `resolver.py` have already been updated with `FR233_MAP` and
   FR.233 added to `_build_stage_2` / `_build_surveillance`. Do NOT revert these changes.

---

## Definitive 14-Phase Workflow

### Phase 1 — Setup & Planning
**Who:** CB (Planner)
**Status transition:** `pending_review → in_planning`
**Actions:**
- CB creates the audit set: company info, EA code, scope, standards.
- Assigns **Stage 1 and Stage 2 teams** at the same time (lead auditor, auditors, TEs,
  observers). Both stages have their dates set here.
- Both stage teams are connected to this audit task in their auditor portal accounts
  immediately upon assignment (i.e., `_get_auditor_assignments` returns this audit set
  for all assigned auditors from this point on — not just after scheduling).

**Implementation note:** Currently, auditor visibility triggers on `stage1_scheduled` /
`stage2_scheduled`. Change this: an auditor should see an audit set in their portal as
soon as they are assigned to any stage, regardless of workflow status.

---

### Phase 2 — Quotation (FR.220)
**Who uploads:** CB Planner
**Who signs:** GM (visual) → then Client (visual)
**Status transition:** When client signs → `quotation_sent`
**Rules:**
- Planner uploads FR.220 (`document_type="quotation"`) via Shared Documents panel.
- System creates **two** signature slots: `signer_role_label="gm"` (order 0) and
  `signer_role_label="client"` (order 1).
- GM signs first via visual signature in the document viewer (`[SIG:GM]`).
- Client signs after GM (`[SIG:CLIENT]`). Gate: client cannot sign until GM has signed.
- When client signs → doc released → `workflow_status → "quotation_sent"`.
- Fix: currently only ONE GM slot is created for FR.220. Add the client slot.

---

### Phase 3 — Agreement (FR.221)
**Who uploads:** CB Planner
**Who signs:** GM (visual) → then Client (visual)
**Status transition:** When client signs → `agreement_signed` → auto `fr218_in_progress`
**Rules:**
- Same two-slot pattern as FR.220 (GM then Client).
- Gate: FR.221 cannot be released until FR.220 is fully signed by both GM and Client.
- When client signs → `_commit_existing_signing_record` → `agreement_signed` →
  `fire_phase_triggers` → auto-seed FR.218 slots + advance to `fr218_in_progress`.
- Fix: currently only GM slot created for FR.221. Add the client slot.

---

### Phase 4 — FR.218 Application Review
**Who signs:** CB Planner (visual `[SIG:CB_PLANNER]`) + Cert Manager (visual `[SIG:CB_CERT_MANAGER]`)
**FSMS/ISMS only:** Independent Reviewer also signs (`[SIG:CB_REVIEWER]`)
**Status transition:** All slots signed → auto `fr218_complete`
**Visibility:** CB only. Client cannot see. Auditors cannot see.
**No change needed here** — existing `pipeline_triggers.py` `seed_fr218_slots` and
`check_fr218_completion` are correct.

---

### Phase 5 — Audit Programme (FR.222)
**Who uploads:** CB Planner
**Who signs:** CB Planner (visual) + Cert Manager (visual)
**Status transition:** no workflow status change at this step
**Visibility:** CB only. Client cannot see. Auditors cannot see.
**Implementation:** FR.222 is a `document_type="audit_programme"` (add this type if
it doesn't exist). Two signature slots: `cb_planner` (order 0) + `cb_cert_manager` (order 1).
The document is gated: cannot be uploaded until `fr218_complete`.
Both CB parties sign in the viewer. No client or auditor visibility.

---

### Phase 6 — FR.224 Audit Team Information Forms (Stage 1)
**Who uploads:** CB Planner (one per auditor/TE)
**Who signs:** Each auditor/TE signs **only their own** form (visual signature in auditor portal)
**Visibility:** PRIVATE — each auditor sees only their own FR.224. Other auditors and
the client cannot see any FR.224.
**Implementation:**
- `document_type="fr224"` (or existing `audit_team_info`)
- Each document is tagged with `assigned_auditor_id` (FK to auditors record)
- When an auditor opens their portal, they see only FR.224 documents where
  `assigned_auditor_id == current_user.auditor_id`
- Signature slot: `signer_role_label="assigned_auditor"`, linked to that specific auditor
- Gate: FR.224 cannot be uploaded until `fr218_complete`

---

### Phase 7 — Audit Plan FR.223 (Stage 1)
**Who downloads:** Lead Auditor downloads the blank set ZIP
**Who uploads:** Lead Auditor uploads filled FR.223
**Who signs:** Organisation Representative (visual `[SIG:ORG_REP]`)
**Visibility:** CB and Organisation (client) can see. Auditors other than the Lead Auditor
can see (it's the audit plan, shared with the team).
**Gate:** Org Rep must sign FR.223 before Stage 1 can begin.
**Status transition:** Org Rep signs → gate cleared → Stage 1 can proceed to `stage1_in_progress`

---

### Phase 8 — Stage 1 Audit (Document Review)
**Status:** `stage1_in_progress`
**Gate to enter:** FR.223 org rep signature complete, all FR.224s signed by their auditors.

Documents in order:

#### 8a — FR.225 Opening/Closing Meeting Form
- Lead Auditor uploads FR.225
- **Audit team signs:** Lead Auditor + all Auditors + TEs each sign their own row
  in the Audit Team section of Table 2 (visual signature, existing `lead_auditor_name` row
  and auditor loop rows)
- **Organisation signs:** Client selects employees from their roster; each employee's
  signature is placed in their row via the org employee picker (see Portal 49a)
- Visibility: everyone (CB, auditors, client)

#### 8b — FR.230 Nonconformity Notification Form (optional — only if NCs found)
- Lead Auditor uploads FR.230
- **Lead Auditor signs** (`[SIG:LEAD_AUDITOR]`) — visual signature
- **Organisation Rep counter-signs** (`[SIG:ORG_REP]`) — visual signature in client portal
- Visibility: everyone (CB, auditors, client)
- Two-step signing: Lead Auditor signs first, then client counter-signs

#### 8c — FSMS/ISMS Reviewer Appointment (conditional)
- Applies when audit standards include ISO 22000, FSSC 22000, or ISO 27001
- CB (Planner or Admin) appoints a reviewer from CB staff who is NOT on the audit team
  and whose EA codes cover the relevant standard
- This reviewer's account is connected to this audit task
- This reviewer will later sign FR.231 in their own portal

#### 8d — FR.231 Stage 1 Report (or FR.231-1 for MDQMS, or both for integrated)
- Lead Auditor uploads FR.231 (standard QMS) and/or FR.231-1 (MDQMS)
- Lead Auditor signs (`[SIG:LEAD_AUDITOR]`) — visual signature
- Document status → `pending_review`
- **If FSMS/ISMS:** the appointed reviewer sees FR.231 in their portal and signs
  (`[SIG:REVIEWER]`) — visual signature → document status → `approved`
- **If NOT FSMS/ISMS:** Lead Auditor signature alone completes it
- After report approved/complete: system notifies CB Planner that Stage 1 audit is done
- **Status transition:** `stage1_in_progress → stage1_complete` (manual CB action
  or auto when FR.231 is signed/approved)

---

### Phase 9 — Certification Manager Stage 1 Review
**Who:** Certification Manager
**Action:** Reviews all Stage 1 work (reads FR.218, FR.222, FR.224s, FR.223, FR.225,
FR.230 if any, FR.231) — **no signing required**
**UI:** A "Stage 1 Review" card appears in the CM's portal for any audit set with
`workflow_status == "stage1_complete"`. Shows a checklist of all Stage 1 documents and
their signing status. Single action button: **"Stage 1 appropriate — proceed to Stage 2"**
**Status transition:** CM clicks → `stage1_complete → stage2_scheduled`
(or `stage2_ready` — see note below on stage 2 setup)

#### Phase 9.5 — FR.211 Auditor Assessment (Stage 1 batch)
**Who uploads:** CLIENT (not system, not auditor)
**When:** After CM clicks "Stage 1 appropriate" (i.e., after `stage1_complete`)
**What:** Client fills and uploads one `FR.211` per auditor/TE who participated in Stage 1
**Who signs:** Client only (visual signature `[SIG:CLIENT]`)
**Visibility:** CB can see. **Auditors CANNOT see FR.211.** Auditors must never see their
own assessment forms.
**Implementation:**
- `document_type="fr211"`, tagged with `auditor_ref_id` and `stage_type="stage_1"`
- Client portal shows a "Submit Auditor Assessments" section for Stage 1 after
  `stage1_complete`. For each Stage 1 auditor/TE, a file upload field appears.
- Client uploads the filled form → client signs it → done
- FR.211 is already in the blank set ZIP the client received — they have the blank form
- No auto-generation needed; the client fills it manually from the blank

---

### Phase 10 — FR.224 Audit Team Information Forms (Stage 2)
Same as Phase 6 but for Stage 2.
- Stage 2 team was already assigned in Phase 1. Stage 2 auditors/TEs may differ from Stage 1.
- Even if the same person is on both stages, a new FR.224 record is created for Stage 2
  (new document, new signature, new task link for that auditor)
- Gate: cannot proceed until all Stage 2 FR.224s are signed

---

### Phase 11 — Audit Plan FR.223 (Stage 2)
Same as Phase 7 but for Stage 2.
- Lead Auditor downloads blank set ZIP (Stage 2 folder)
- Lead Auditor uploads filled FR.223 for Stage 2
- Organisation Rep signs (`[SIG:ORG_REP]`) — visual
- Gate: Org Rep must sign before Stage 2 can begin

---

### Phase 12 — Stage 2 Audit (On-Site)
**Status:** `stage2_in_progress`
Same document sequence as Stage 1 (phases 8a–8d) but with Stage 2 variants:
- **FR.225** — same process (org employees + audit team all sign)
- **FR.230** — same (optional, if NCs found)
- **FSMS/ISMS reviewer** — CB appoints (may be same or different from Stage 1 reviewer)
- **FR.232 Stage 2 Report** (standard QMS) and/or **FR.229** (ISMS/PIMS):
  - Lead Auditor uploads + signs (`[SIG:LEAD_AUDITOR]`) — visual
  - If FSMS/ISMS: reviewer signs (`[SIG:REVIEWER]`) — visual → `approved`
  - On upload: `workflow_status → "under_review"` (existing auto-advance)
  - On reviewer sign + `under_review`: do NOT auto-advance to `certified` yet
    (certification committee step must happen first — remove the current auto-certify)
- After FR.232/FR.229 signed: system notifies all parties Stage 2 audit complete
- **Status transition:** `stage2_in_progress → stage2_complete`

---

### Phase 13 — Certification Committee (FR.233)
**Status:** `stage2_complete → committee_review → certified`

#### 13a — Committee Appointment
- Planner appoints committee members (existing `committee_router.py` logic)
- Members must NOT have participated in the audit
- Collectively must cover all EA codes of all standards being certified
- Each member's CB user account is connected to this audit task

#### 13b — FR.233 Generation and Upload
- Planner (or system auto-generates) the FR.233 Review & Decision Form
- FR.233 is pre-filled from audit set data using `FR233_MAP` (coordinates confirmed)
- Uploaded as `document_type="fr233"` — visible to CB only (not client, not auditors)

#### 13c — Committee Member Signing
- Each committee member (CB users) sees FR.233 in their portal
- They sign their slot: Chairperson → `[SIG:COMMITTEE_CHAIR]`, Members → `[SIG:COMMITTEE_MEMBER_1]`, `[SIG:COMMITTEE_MEMBER_2]`
- All visual signatures. One by one, in any order.
- Visibility: each member sees only their own signing task; they cannot see other members' portals

#### 13d — Certification Manager Approval
- After all committee members have signed FR.233:
- CM sees a "Certify" action in their portal
- CM signs FR.233 final slot (`[SIG:CERT_MANAGER]`) — visual
- **Status transition:** CM signs → `committee_review → certified`
- `cert_issued_date` set to today. `cert_expiry_date` set to today + 3 years.

#### Phase 13.5 — FR.211 Auditor Assessment (Stage 2 batch)
**Who uploads:** CLIENT
**When:** After CM approves certification (after `certified`)
**What:** Client uploads one filled FR.211 per auditor/TE from Stage 2
**Who signs:** Client only (visual `[SIG:CLIENT]`)
**Visibility:** CB can see. **Auditors CANNOT see.**
Same implementation as Phase 9.5 but tagged `stage_type="stage_2"`.

---

### Phase 14 — Certificate Issued
**Who uploads:** CB Planner
**Action:** Planner uploads the certificate document (`document_type="certificate"`)
**Visibility:** Everyone — CB, client, auditors can all see and download the certificate
**Status:** `certified` (already set in Phase 13d). Certificate upload does not change status.
**No signature required on the certificate document itself.**

---

## Status Machine — Complete Correct Sequence

```
pending_review
  → in_planning           (CB creates audit set)
  → quotation_sent        (client signs FR.220)
  → agreement_signed      (client signs FR.221)
  → fr218_in_progress     (auto, pipeline_triggers)
  → fr218_complete        (auto, all FR.218 slots signed)
  → stage1_in_progress    (CB advances; gates: FR.222 signed, FR.224s signed, FR.223 signed)
  → stage1_complete       (FR.231 signed/approved)
  → stage2_in_progress    (CM clicks "Stage 1 appropriate"; gates: FR.224s signed, FR.223 signed)
  → stage2_complete       (FR.232/FR.229 signed/approved)
  → committee_review      (Planner starts committee phase)
  → certified             (CM signs FR.233)
```

Remove `stage1_scheduled`, `stage2_scheduled` as intermediate status values if they
currently block the flow — the team is assigned during planning and does not need a
separate "scheduling" transition.

---

## Document Type Reference

Add these `document_type` values if they don't exist:

| document_type    | Description                        | Visibility               |
|------------------|------------------------------------|--------------------------|
| quotation        | FR.220 Quotation                   | CB, Client               |
| agreement        | FR.221 Agreement                   | CB, Client               |
| audit_programme  | FR.222 Audit Programme             | CB only                  |
| audit_plan       | FR.223 Audit Plan                  | CB, Client, Auditors     |
| team_info        | FR.224 Team Info (per auditor)     | CB, assigned auditor only |
| meeting_form     | FR.225 Opening/Closing Meeting     | Everyone                 |
| nc_form          | FR.230 NC Form                     | Everyone                 |
| stage1_report    | FR.231 Stage 1 Report              | CB, Auditors             |
| stage2_report    | FR.232 / FR.229 Stage 2 Report     | CB, Auditors             |
| assessment       | FR.211 Auditor Assessment          | CB, Client only (NOT auditors) |
| review_decision  | FR.233 Review & Decision           | CB only                  |
| certificate      | Certificate                        | Everyone                 |

---

## Visibility Enforcement

In every query that returns documents to a portal:

```python
# CB (admin/planner/officer/executive/gm/cert_manager): sees all document types
# Auditor portal: sees audit_plan, meeting_form, nc_form, stage1_report, stage2_report
#                 sees team_info only for documents where assigned_auditor_id == current_user.auditor_id
#                 CANNOT see: quotation, agreement, audit_programme, fr218, assessment, review_decision
# Client portal:  sees quotation, agreement, audit_plan, meeting_form, nc_form, assessment, certificate
#                 CANNOT see: audit_programme, fr218, team_info, stage1_report, stage2_report, review_decision
```

Enforce this in `documents_router.py` `list_documents` and wherever documents are returned.

---

## Signing Slot Rules per Document

| Document        | Slots (in order)                                          |
|-----------------|-----------------------------------------------------------|
| FR.220          | [SIG:GM] order 0 → [SIG:CLIENT] order 1                  |
| FR.221          | [SIG:GM] order 0 → [SIG:CLIENT] order 1                  |
| FR.218          | [SIG:CB_PLANNER] → [SIG:CB_REVIEWER]* → [SIG:CB_CERT_MANAGER] |
| FR.222          | [SIG:CB_PLANNER] → [SIG:CB_CERT_MANAGER]                 |
| FR.224          | [SIG:ASSIGNED_AUDITOR] (one slot, per-auditor doc)        |
| FR.223          | [SIG:ORG_REP]                                             |
| FR.225          | [SIG:LEAD_AUDITOR] + auditor/TE rows + org employee rows  |
| FR.230          | [SIG:LEAD_AUDITOR] → [SIG:ORG_REP]                       |
| FR.231/FR.232   | [SIG:LEAD_AUDITOR] → [SIG:REVIEWER]* (* FSMS/ISMS only)  |
| FR.229          | [SIG:LEAD_AUDITOR] → [SIG:REVIEWER] (ISMS always)        |
| FR.211          | [SIG:CLIENT]                                              |
| FR.233          | [SIG:COMMITTEE_CHAIR] → [SIG:COMMITTEE_MEMBER_1] → [SIG:COMMITTEE_MEMBER_2] → [SIG:CERT_MANAGER] |

---

## Auto-Certify Fix

Currently in `viewer_router.py` `_commit_existing_signing_record`, when CB_REVIEWER signs
an `audit_report` and `workflow_status == "under_review"` → auto-advances to `"certified"`.

**Remove this auto-certify.** After Stage 2 report is approved, status must stop at
`stage2_complete` and wait for the certification committee (Phase 13). Only after the
CM signs FR.233 does the workflow advance to `certified`.

---

## FR.211 Upload Portal (Client Side)

In the client portal, add two "Auditor Assessment" sections:

**Section A — Stage 1 Assessments** (appears after `stage1_complete`):
```
For each auditor/TE in Stage 1 team:
  - Auditor name (read-only label)
  - File upload field: "Upload FR.211 for [name]"
  - Once uploaded: [Sign] button
  - Once signed: green checkmark
```

**Section B — Stage 2 Assessments** (appears after `certified`):
Same structure for Stage 2 team.

Both sections source their auditor list from `AuditSetStage` for that stage type.
Documents are stored with `assigned_auditor_id` and `stage_type` tags.
Auditors fetching their own documents must NEVER receive FR.211 documents.

---

## Files to Touch (Comprehensive List)

| File | Change |
|---|---|
| `backend/audit_set/db_models.py` | Add `audit_programme`, `team_info`, `assessment`, `review_decision` to `document_type` enum (if missing). Add `stage_type` and `assigned_auditor_id` columns to `AuditSetSharedDocument`. (`AuditSetFR233Record` + `ClientOrgEmployee` already exist — do NOT add again.) |
| `backend/audit_set/documents_router.py` | Add CLIENT slot to quotation/agreement `release_document`. Enforce visibility by role. Add FR.211 client upload endpoint. |
| `backend/audit_set/viewer_router.py` | ~~Remove auto-certify~~ (done c9e5cb6). Add remaining sig key handlers: `[SIG:ORG_REP]`, `[SIG:ASSIGNED_AUDITOR]`. Remove all OTP paths. (`[SIG:COMMITTEE_*]` and `[SIG:CERT_MANAGER_FR233]` already handled — do NOT rewrite.) |
| `backend/audit_set/pipeline_triggers.py` | Remove `stage1_scheduled` / `stage2_scheduled` triggers if team is assigned at planning time. Add `stage2_complete → committee_review` trigger. |
| `backend/audit_set/workflow_router.py` | Add `stage1_complete → stage2_in_progress` transition gated on: all Stage 2 FR.224s signed + FR.223 signed by Org Rep. |
| `backend/audit_set/committee_router.py` | ~~FR.233 generate + GET~~ (done c9e5cb6). No changes needed here unless adding appointment gates. |
| `backend/audit_set/auditor_router.py` | Change assignment visibility: return audits where auditor is on any stage, not just after scheduling status. |
| `backend/audit_set/resolver.py` | **Already updated with FR.233. Do not revert.** |
| `backend/audit_set/field_maps.py` | **Already updated with FR233_MAP and FR225_MAP. Do not revert.** |
| `frontend/src/app/(app)/admin/audit-sets/[id]/page.tsx` | Add FR.222 upload section. "Stage 1 appropriate" CM button. (`FR233Panel` already mounted — do NOT remove.) |
| `frontend/src/app/(app)/client/audit-sets/[id]/page.tsx` | Add FR.211 upload sections (Stage 1 + Stage 2). Show FR.220 + FR.221 for client signing. |
| `frontend/src/app/(app)/auditor/audit-sets/[id]/page.tsx` | Show audit from planning assignment. Show FR.224 (own only). |

---

## Sync Command (run after any template change)

```bash
cd /Users/batuhan/BATUHAN
rsync -av --delete "uaf_blank_set copy/" "backend/uaf_blank_set/"
```

Then commit `backend/uaf_blank_set/` so Railway picks up the updated templates.

---

## Verification Checklist

1. Create audit set → assign Stage 1 + Stage 2 teams → auditor sees it in their portal immediately
2. Upload FR.220 → GM signs → client signs → `quotation_sent`
3. Upload FR.221 → GM signs → client signs → `agreement_signed` → auto `fr218_in_progress`
4. CB Planner + CM sign FR.218 → `fr218_complete`
5. Planner uploads FR.222 → CB Planner + CM sign → visible to CB only
6. Planner uploads FR.224 for each Stage 1 auditor → each auditor signs their own in auditor portal → other auditors and client cannot see
7. Lead auditor downloads blank ZIP → uploads filled FR.223 → org rep signs in client portal
8. Lead auditor uploads FR.225 → all team members sign + org employees sign via roster
9. (If NCs) FR.230 uploaded → lead auditor signs → client counter-signs
10. Lead auditor uploads FR.231 → signs → (if FSMS/ISMS: reviewer signs) → `stage1_complete`
11. Client uploads FR.211 × (# Stage 1 auditors) → signs each → auditors cannot see them
12. CM opens Stage 1 review → no signing → clicks "Stage 1 appropriate" → Stage 2 begins
13. Same flow for Stage 2 with FR.224 (Stage 2), FR.223 (Stage 2), FR.225, FR.230, FR.232/FR.229
14. Status reaches `stage2_complete` — does NOT auto-advance to `certified`
15. Planner generates FR.233 → committee members sign one by one → CM signs → `certified`
16. Client uploads FR.211 × (# Stage 2 auditors) → signs each → auditors cannot see
17. Planner uploads certificate → visible to all
