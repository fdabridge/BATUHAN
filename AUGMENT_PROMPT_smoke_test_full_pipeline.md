# Smoke Test — Full 14-Phase Initial Certification Pipeline

**Target:** `https://compassionate-miracle-production.up.railway.app`  
**Scope:** ISO 9001 initial certification (one standard, no FSMS/ISMS reviewer, simplest path)  
**Goal:** Walk every phase from blank audit set to certificate, verifying each document uploads, routes to the right viewer, shows the correct signing parties, and advances workflow status on completion.

---

## Accounts

Use the accounts below. All passwords are `Certiva2026!`.

| Role | Login | Notes |
|------|-------|-------|
| CB Planner / Planning Officer | `egeertogrul` (or email) | Creates audit set, uploads CB-side docs, signs as CB_PLANNER |
| GM (General Manager) | `alya@ifcglobal.com.tr` | Signs quotation and agreement on CB side first |
| Certification Manager | [find a user with role `certification_manager`] | Signs FR.218, FR.222, FR.233 |
| Lead Auditor | [find a user with role `auditor` who has Stage 1 assignment] | Uploads and signs audit-side docs |
| Committee Member | [find a second auditor not on the audit team] | Signs FR.233 in their portal |
| Client / Org Rep | [find a user with role `client`] | Signs quotation, agreement, FR.223, FR.225, FR.230 counter |

> **Tip:** Admin panel is at `/admin/users`. Each user shows their role. Certification Manager role is `certification_manager`. If any role account is missing, create one via `/admin/users/new`.

---

## Before Starting

1. Log in as Planner. Go to **Clients** → create or pick an existing client with a company name.
2. Create a new **Audit Set** for that client: standard = ISO 9001, scope = anything, EA code = EA 25 (Manufacturing).
3. Note the audit set ID from the URL (you'll use it to verify API state).
4. Assign Stage 1 team: Lead Auditor + date range (use dates 2–3 weeks out).
5. Assign Stage 2 team: same Lead Auditor (or different) + date range 4–6 weeks out.

Expected state after setup: `audit_set.workflow_status = "pending_review"` (or similar initial state).

---

## Phase 1 — Quotation (FR.220)

**Who acts:** GM first, then Client

1. Log in as **Planner**. Open the audit set → Documents section. Generate / upload the **Quotation** document (FR.220). The system should produce a PDF via the template.
2. Confirm quotation appears in `Documents` with status = uploaded.
3. Log in as **GM** (`alya@ifcglobal.com.tr`). Go to Dashboard → Pending Signatures.
   - Expect: card for Quotation with button **"Open to Sign"** (routes to `/viewer/shared_doc/{id}`)
   - Open viewer. Confirm GM signature slot is highlighted green (your turn). Sign it.
   - Expect: GM slot flips to ✅ Signed.
4. Log in as **Client**. Go to their portal. Expect Quotation in pending documents.
   - Open viewer. Confirm Client slot is now active (GM signed first). Sign it.
   - Expect: both slots signed → document fully signed.
5. Verify: `workflow_status` advances to `quotation_sent`.

---

## Phase 2 — Agreement (FR.221)

**Who acts:** GM first, then Client  
**Prerequisite:** Quotation fully signed

1. As **Planner**, generate/upload **Agreement** (FR.221).
2. As **GM**: Dashboard → Pending Signatures → Agreement → Open to Sign → sign.
3. As **Client**: Portal → sign Agreement.
4. Verify: `workflow_status` advances to `agreement_signed`.
5. Verify: FR.218 phase is unlocked (document type `fr218_review` appears in Documents or workflow next step shows).

---

## Phase 3 — FR.218 Application Review

**Who acts:** CB Planner + Certification Manager  
**Visibility:** CB-only — client and auditors must NOT see this document

1. As **Planner**, upload **FR.218 Application Review** (`fr218_review` document type). Use the UAF blank set template.
   - The backend generates the PDF from DOCX, pdfplumber runs, and `DocumentSignatureField` rows are created.
2. Log in as **Planner**. Dashboard → Pending Signatures.
   - Expect: FR.218 card with **"Open to Sign"** button (NOT an OTP modal — that's the bug we fixed in Portal 52).
   - Open viewer. Confirm the legend shows:
     - **Planning Officer** → "Your signature" (green highlight)
     - **Committee Reviewer** → "Not required" (gray / not_applicable — ISO 9001 has no reviewer)
     - **Certification Manager** → "Waiting for prior signer" (pending)
   - Confirm `[SIG:CB_PLANNER]` renders as an **overlay in the table cell** (not as raw text visible in the PDF). If you see literal `[SIG:CB_PLANNER]` text in the document, the DOCX template fix hasn't deployed yet.
   - Sign as Planning Officer. Expect: overlay turns green with signature image.
3. Log in as **Certification Manager**. Dashboard → Pending Signatures.
   - Expect: FR.218 card → "Open to Sign".
   - Open viewer. Confirm CB_CERT_MANAGER slot is now active (Planner signed first).
   - Sign. Expect: both slots signed → document fully signed.
4. Verify: `workflow_status` advances to `fr218_complete`.

---

## Phase 4 — Audit Programme (FR.222)

**Who acts:** CB Planner + Certification Manager  
**Visibility:** CB-only — client and auditors must NOT see this

1. As **Planner**, upload **FR.222 Audit Programme** (`audit_programme` document type).
2. As **Planner**: Dashboard → Pending Signatures → Audit Programme → Open to Sign → sign (CB_PLANNER slot).
3. As **Certification Manager**: Dashboard → Pending Signatures → Audit Programme → Open to Sign → sign (CB_CERT_MANAGER slot).
4. Verify: both slots signed. Workflow advances.

---

## Phase 5 — FR.224 Team Information Forms (Stage 1)

**Who acts:** Each assigned auditor/TE signs their own form  
**Visibility:** Private — each person sees only their own form

1. As **Planner**, upload a **FR.224 Team Info** form for the Lead Auditor.
2. Log in as **Lead Auditor**. Go to Auditor Portal.
   - Expect: FR.224 in their document list (only theirs — other team members' FR.224s not visible).
   - Sign their FR.224.
3. Verify: Lead Auditor's FR.224 shows as signed.

---

## Phase 6 — FR.223 Audit Plan — Stage 1

**Who acts:** Lead Auditor uploads → Org Rep signs  
**Prerequisite:** FR.224 signed by that auditor

1. As **Lead Auditor**: Download blank set ZIP for Stage 1 from their portal (or from `/admin/blank-sets`). Fill in FR.223 Audit Plan. Upload it.
2. Log in as **Client (Org Rep)**. Portal → Documents → FR.223 Audit Plan.
   - Expect: document visible; Org Rep signature slot active.
   - Sign it.
3. Verify: FR.223 Stage 1 fully signed. Workflow status: `stage1_in_progress` (or equivalent).

---

## Phase 7 — Stage 1 Audit Execution

### FR.225 Opening/Closing Meeting Record

1. As **Lead Auditor**, upload FR.225.
2. All assigned auditors/TEs sign in their portals.
3. Org employees (if any are linked) sign from client portal.
4. Verify: FR.225 all slots signed.

### FR.230 NC Form (Optional — include at least one NC)

1. As **Lead Auditor**, upload FR.230 NC Form (with at least one NC entry).
2. Lead Auditor signs.
3. Log in as **Client (Org Rep)**: portal → FR.230 → counter-sign.
4. Verify: FR.230 fully signed.

### FR.231 Stage 1 Audit Report

1. As **Lead Auditor**, upload FR.231 Audit Report.
2. Lead Auditor signs (CB_LEAD_AUDITOR slot).
   - For ISO 9001: no reviewer needed. Confirm CB_REVIEWER shows as "Not required" in legend.
3. Verify: FR.231 signed. Workflow: `stage1_complete` (pending Cert Manager approval).

---

## Phase 8 — Stage 1 Gate: Certification Manager Review

**Who acts:** Certification Manager (no signature — decision gate)

1. Log in as **Certification Manager**. Go to the audit set.
2. Review Stage 1 documents. Find the **"Stage 1 appropriate → proceed to Stage 2"** button (or equivalent action).
3. Click it. Confirm a success message.
4. Verify: `workflow_status` = `stage2_in_progress` (or pre-stage2 planning state).

---

## Phase 9 — FR.224 Team Info Forms (Stage 2)

Same as Phase 5 but for Stage 2 team. If team is the same, a new set of FR.224s still needs to be uploaded and signed for Stage 2.

---

## Phase 10 — FR.223 Audit Plan — Stage 2

Same as Phase 6 but for Stage 2. Lead Auditor uploads, Org Rep signs.

---

## Phase 11 — Stage 2 Audit Execution

### FR.225 Opening/Closing Meeting (Stage 2)

Same as Phase 7 FR.225.

### FR.232 Stage 2 Audit Report

1. As **Lead Auditor**, upload **FR.232 Stage 2 Report**.
2. Lead Auditor signs.
3. For ISO 9001: no reviewer. Confirm CB_REVIEWER = Not required.
4. Verify: FR.232 signed. Workflow: `stage2_complete`.

---

## Phase 12 — Certification Committee (FR.233)

**Who acts:** Planner appoints committee → each member signs → Cert Manager signs last  
**Visibility:** CB-only — client must NOT see FR.233

1. As **Planner**: Go to audit set → Committee section. Appoint 2–3 committee members (must be non-audit-team members who have auditor accounts covering the EA codes used).
2. Upload **FR.233 Review & Decision Form**.
3. Log in as each **Committee Member** in turn. Go to their portal.
   - Expect: FR.233 in their pending signatures.
   - Open viewer. Sign their slot.
4. Log in as **Certification Manager**.
   - Expect: FR.233 in pending signatures only after ALL committee members have signed.
   - Sign (CB_CERT_MANAGER slot — final approver).
5. Verify: FR.233 fully signed. Workflow: `committee_review` complete → ready for certificate.

---

## Phase 13 — Certificate

**Who acts:** Planner uploads, no signing required

1. As **Planner**, upload the **Certificate** document.
2. Verify: Certificate is visible to the Client in their portal.
3. Verify: `workflow_status` = `certified` (or final terminal state).
4. Verify: certificate shows in the audit set summary with issue date and expiry (issue + 3 years).

---

## What to Check Throughout

For every document+viewer interaction:

- [ ] Dashboard "Sign" button routes to **viewer** (`/viewer/shared_doc/{id}`), never to OTP modal
- [ ] Signature legend is accurate: green = your turn, gray = not your turn, ✅ = signed, "Not required" for inapplicable roles
- [ ] `[SIG:XXX]` markers are **overlaid** in the table cell, not visible as raw text
- [ ] After signing, the signature image appears at the correct table cell (not below the PDF in the fallback panel)
- [ ] Document visibility gates are respected: CB-only docs (FR.218, FR.222, FR.233) must not appear in client portal
- [ ] Auditor-only docs (FR.224) must not appear cross-visible between different auditors
- [ ] `workflow_status` advances correctly at each gate

---

## Known Issues / Exceptions to Note

1. **FR.218 CB_PLANNER fallback panel** — If the DOCX template fix hasn't deployed yet, the Planning Officer signature will appear in a green dashed panel *below* the PDF instead of in the table cell. This is functional for the smoke test (you can still sign) but should be flagged as "template not yet deployed."

2. **"Client not found" on CM dashboard** — Audit sets created internally without a linked client user account will show this. Workaround: ensure the test client has a user account linked.

3. **CB_REVIEWER for ISO 9001** — Should display as "Not required" in the viewer legend. If it shows as "Waiting for prior signer" or prompts to appoint a reviewer, that's a regression from Portal 51.

---

## Pass Criteria

The smoke test passes if:
- All 14 phases complete without errors
- `workflow_status` reaches `certified`
- All viewer-based documents route correctly (no OTP modals for viewer types)
- No signature slot shows the wrong state relative to signing order
- Certificate is visible to client after upload

