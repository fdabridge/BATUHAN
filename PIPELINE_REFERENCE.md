# Certiva — Complete Audit Pipeline Reference
*Last updated: 2026-06-12*

---

## Special Accounts / Roles

| Role | Description | What they sign |
|------|-------------|----------------|
| **Planner / Planning Officer** | Creates and manages audit sets. Always present in chat from the beginning. | FR.218 (preparer), FR.222 |
| **General Manager (IFC Global)** | Special account. One person. Only duty: sign FR.220 and FR.221 on behalf of IFC Global. | FR.220 (Quotation), FR.221 (Agreement) |
| **Certification Manager** | One person, system-wide special profile. Joins chat at Phase 2 (when FR.218 is ready). Makes final certification decision after Stage 2. | FR.218 (final approval), certification decision record |
| **Auditor / Lead Auditor / TE** | Assigned per stage at audit set creation. Join chat when their stage begins. | FR.224, FR.225, FR.230, FR.231/232/229 |
| **Certification Committee** | Appointed after Stage 2. EA/category coverage required. Must not be on audit team. | FR.218 (reviewer slot — FSMS/ISMS only), FR.231/232/229 (reviewed & approved by) |
| **Client Representative** | Existing portal account. | FR.220, FR.221, FR.223, FR.225 (via guest token or portal), FR.230, FR.211 |
| **Guest Attendees (meeting)** | No account, no OTP, no token. Names and titles are pre-filled by the auditor in the filled FR.225 document they upload. On the client portal, attendees see their name already there, click their row, and choose/draw a signature. They sign through the organisation's portal session — no separate login. | FR.225 (opening + closing columns) |

---

## Full Pipeline — Stage by Stage

### Phase 0 — Audit Set Creation
- Planner creates the audit set: company, standards, scope, EA codes, dates
- Auditors assigned to stages at this point (not later)
- Planner joins the chat immediately — always present

---

### Phase 1 — Quotation & Agreement
**Triggers automatically when audit set is created**

Documents released and signed in order:
1. **FR.220 (Quotation)** → Released to client portal
   - GM of IFC Global signs (CB side)
   - Client representative signs (client portal)
2. **FR.221 (Agreement)** → Released to client portal after quotation signed
   - GM of IFC Global signs (CB side)
   - Client representative signs (client portal)

**Phase 1 complete trigger:** Both FR.220 and FR.221 fully signed by both parties.

---

### Phase 2 — Internal Application Review (FR.218)
**Triggers after Phase 1 complete**
**Certification Manager joins the chat at this point**

FR.218 is an internal CB document — client never sees it.

Signers:
- Planning Officer (always)
- Reviewer Auditor/TE (only if standards include ISO 22000 or ISO 27001 — must have EA code coverage, must NOT be on the audit team)
- Certification Manager (always, final sign)

---

### Phase 3 — Stage 1

**Trigger:** FR.218 fully signed → Stage 1 auditors/TEs/observers join the chat

**Step 3a — Blank set exchange (client does NOT see this)**
- System packages all blank Stage 1 documents and shares them with the assigned auditor(s) in the chat
- Auditor downloads, fills offline, reuploads the completed set
- This exchange is hidden from the client portal entirely

**Step 3b — Filled documents released to client (client now sees them)**
- Filled documents become visible to client because client must sign some of them

**Documents in Stage 1 and who signs:**

| Document | Signed by |
|----------|-----------|
| FR.222 — Audit Programme | Planner + Certification Manager (internal) |
| FR.223 — Audit Plan | Client representative (acknowledges/signs) |
| FR.224 — Impartiality Declaration | Every auditor/TE/observer on the Stage 1 team individually |
| FR.225 — Opening Meeting | Audit team (from auditor portal) + guest attendees (guest token) |
| FR.225 — Closing Meeting | Audit team (from auditor portal) + guest attendees (guest token) |
| FR.230 — NC Notification (if any NCs) | Lead auditor + client representative |
| FR.231 — Stage 1 Report | Lead auditor signs; committee reviewer signs "reviewed and approved by" |

**Step 3c — Auditor Assessment (FR.211) — SOLO to client**
- Shared with client ONLY — auditors do NOT see FR.211 (auditor does not know they are being assessed)
- Client downloads FR.211, fills it offline (rating of each auditor)
- Client uploads and signs on the portal
- This is the LAST action of Stage 1 from the client side

**Phase 3 complete trigger:** FR.231 signed + FR.211 submitted and signed by client

---

### Phase 4 — Stage 2

**Trigger:** Stage 1 complete → Stage 2 auditors/TEs/observers join the chat
(Stage 2 team may be different people from Stage 1 team)

Same flow as Stage 1:

| Document | Signed by |
|----------|-----------|
| FR.223 — Audit Plan (Stage 2) | Client representative |
| FR.224 — Impartiality Declaration | Every Stage 2 auditor/TE/observer individually |
| FR.225 — Opening Meeting | Audit team (auditor portal) + meeting attendees (client portal — names pre-filled by auditor, each person clicks their row and signs, no account/OTP needed) |
| FR.225 — Closing Meeting | Same document, second signature column — same logic |
| FR.230 — NC Notification (if any NCs) | Lead auditor + client representative |
| FR.232 / FR.229 — Stage 2 Report | Lead auditor signs; committee reviewer signs |

**Step 4c — Auditor Assessment (FR.211) — SOLO to client again**
- Same as Stage 1: client only, auditor does not see it, client downloads/fills/uploads/signs

**Phase 4 complete trigger:** FR.232/229 signed + FR.211 submitted and signed by client

---

### Phase 5 — Certification Committee & Decision

**Trigger:** Stage 2 complete → system automatically prompts to appoint the Certification Committee
(Certification Manager is already in the chat since Phase 2)

**Committee Appointment UI:**
- Shows a filtered list of CB staff (auditors/TEs) — same UI style as auditor stage assignment
- Filter 1: each candidate must cover at least one required EA code / food chain category / TA across the standards in this audit set
- Filter 2: must NOT be assigned to any stage on this audit (as Lead Auditor, Auditor, TE, or Observer)
- Collectively the committee must cover ALL required codes/categories/standards before appointment can be saved
- Coverage panel shows same ✓/✗ display as stage planner

**Signing order after committee is appointed:**
1. Client signs any remaining items
2. Auditors/Lead auditor sign remaining items (FR.232/229 if not yet signed)
3. Committee signs: FR.218 reviewer slot (FSMS/ISMS only) + "Reviewed and approved by" on reports
4. Certification Manager signs: FR.218 final approval + certification decision record

**All triggers and signing reminders are automatic** — the system sends notifications and queues each party's pending signatures automatically. No manual chasing.

---

### Phase 6 — Certificate Issuance

**Trigger:** All signatures complete + certification decision recorded

- Admin/Planner enters the certificate issue date
- Certificate is generated by the system
- Certificate is released and visible on the **client portal (Planner section)**

---

## Document Visibility Rules

| Document | Client sees? | Auditor sees? | Notes |
|----------|-------------|---------------|-------|
| FR.218 | ❌ No | ❌ No | Internal CB only |
| FR.220 / FR.221 | ✅ Yes | ❌ No | Quotation/Agreement |
| FR.222 | ❌ No | ❌ No | Internal CB only |
| FR.223 | ✅ Yes | ✅ Yes | Audit plan — client signs |
| FR.224 | ❌ No | ✅ Yes | Each auditor signs their own |
| FR.225 | ✅ Yes (via guest token) | ✅ Yes | Meeting attendances |
| Blank set (stage docs) | ❌ No | ✅ Yes | Hidden exchange |
| Filled set (stage docs) | ✅ Yes | ✅ Yes | Released after auditor uploads |
| FR.230 | ✅ Yes | ✅ Yes | NC form — both sign |
| FR.231 / FR.232 / FR.229 | ✅ Yes | ✅ Yes | Reports |
| FR.211 | ✅ Yes ONLY | ❌ No | Auditor assessment — client solo |
| Certificate | ✅ Yes | ❌ No | Final delivery |

---

## Chat / Circulation Trigger Logic

| Who | Joins when |
|-----|-----------|
| Planner | Immediately — audit set created |
| GM of IFC Global | When FR.220 is ready for signing |
| Client representative | When FR.220 is released (quotation phase) |
| **Certification Manager** | **Phase 2 — when FR.218 is ready for signing** |
| Stage 1 auditors/TEs/observers | Phase 1 complete (both FR.220 + FR.221 signed) |
| Stage 2 auditors/TEs/observers | Stage 1 complete |
| Committee members | After Stage 2 complete and appointment confirmed |

---

## Key Rules (Do Not Deviate)

1. Auditor does NOT see FR.211 (auditor assessment form) at any point
2. Blank set exchange (blank → auditor → filled) is invisible to client
3. FR.211 is shared with client SOLO and is the last action of each stage
4. GM only signs FR.220 and FR.221 — nothing else
5. Certification Manager is one system-wide person — not picked per audit
6. Committee must collectively cover all codes/categories — same logic as auditor team coverage
7. Committee members cannot be on the audit team for that audit
8. All triggers, releases, and signing reminders are automatic — no manual steps
9. Certificate is released to client Planner section after all signatures complete
