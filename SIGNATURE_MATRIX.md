# Certiva — Complete Signature Matrix
*Extracted from all UAF blank set documents, June 2026*

---

## Every Document & Who Signs It

### FR.218 — Application Review Form
**When:** Pre-audit, after application is accepted (in_planning stage)
**Internal CB doc — 2 or 3 signers (conditional):**
| Slot | Who | Role in system | When required |
|---|---|---|---|
| Planning Officer | The planner who reviewed the application | role: planner/officer | Always |
| Reviewer Auditor/Technical Expert* | EA-code-matched, NOT on audit team | role: auditor (committee pool) | **FSMS (ISO 22000) + ISMS (ISO 27001) only** |
| Certification Manager | Final internal approval | role: executive/admin | Always |

*The Reviewer Auditor/TE slot is only required when the standards include ISO 22000 or ISO 27001. For QMS (9001), OHSMS (45001), ENMS (50001), MD (13485) it is skipped — only Planning Officer + Certification Manager sign.*

---

### FR.220 — Certification Quotation
**When:** Released to client portal (quotation_sent stage)
**2 signers — one each side:**
| Slot | Who |
|---|---|
| Signed on behalf of IFC GLOBAL LLC | **Planning Officer (Planner)** |
| Signed on behalf of the Organization | Client representative |

---

### FR.221 — Certification Agreement
**When:** Released to client portal after quotation accepted
**2 signers — one each side:**
| Slot | Who |
|---|---|
| Signed on behalf of IFC GLOBAL LLC | **Planning Officer (Planner)** |
| Signed on behalf of the Organization | Client representative |

---

### FR.222 — Audit Programme
**When:** After stages planned, before audit
**Internal CB doc — 2 CB signers:**
| Slot | Who |
|---|---|
| Planning Officer | The planner |
| Certification Manager | Approval |

---

### FR.223 — Audit Plan
**When:** Sent to client before each stage
**1 signer (client acknowledges):**
| Slot | Who |
|---|---|
| Organization Representative | Client representative (portal) |

*(CB creates it; client signs to confirm receipt and agreement)*

---

### FR.224 — Audit Team Information Form (Impartiality Declaration)
**When:** Before each audit stage — every team member signs individually
**Variable CB signers — every person on the audit team:**
| Slot | Who |
|---|---|
| Lead Auditor | Name + Signature + Date |
| Auditor (×n) | Name + Signature + Date |
| Technical Expert (×n) | Name + Signature + Date |
| Observer (×n) | Name + Signature + Date |

*Each person declares: no commercial relations with client in past 2 years, will not have any in next 2 years, not acting as consultant.*

---

### FR.225 — Opening & Closing Meeting Form
**When:** At the start and end of each audit stage
**Two signature columns (Opening + Closing) per person. Two groups:**

**Group 1 — Client Organization Personnel (variable, guest signing):**
| Slot | Who |
|---|---|
| Participant 1 | Name + Role (e.g. General Manager) + Opening Sig + Closing Sig |
| Participant 2 | Name + Role (e.g. Quality Engineer) + Opening Sig + Closing Sig |
| … | No fixed number — as many as attend |

**Group 2 — Audit Team (CB, existing accounts):**
| Slot | Who |
|---|---|
| Lead Auditor | Opening + Closing signature |
| Auditor(s) | Opening + Closing signature |
| Technical Expert(s) | Opening + Closing signature |

---

### FR.230 — Nonconformity Notification Form
**When:** During/after audit, when NCs are raised
**2 signers:**
| Slot | Who |
|---|---|
| Organisation Representative (Date & Sign) | Client representative (portal) |
| Auditor/Sign | Lead Auditor |

---

### FR.231 / FR.231-1 — Stage 1 Report
**When:** After Stage 1 audit
**2 signers:**
| Slot | Who |
|---|---|
| Lead Auditor | Signs the report |
| Reviewed and approved by | Certification committee reviewer (EA-code-matched, not audit team) |

---

### FR.229 — ISMS/PIMS Audit Report
### FR.232 / FR.232-1 — Audit Report (Stage 2, Surveillance, Recertification)
**When:** After each audit stage
**2 signers:**
| Slot | Who |
|---|---|
| Lead Auditor | Signs the report |
| Accepting and Approving / Reviewed and approved by | Certification committee reviewer |

---

### FR.211 — Lead Auditor/Auditor Assessment Form
**When:** After audit — client evaluates each auditor
**1 signer (client):**
| Slot | Who |
|---|---|
| Customer Establishment Officer | Client representative (portal) |

---

### FR.234 — Surveillance/Recertification Notification Form
**When:** Planning the next cycle
**Not a signature document** — it's a scheduling/notification form where the client fills in their requested audit date and contact details. No formal signature slot detected.

---

## Summary by Signer Type

### Type A — Certification Manager (CB internal, role: executive/admin)
Signs: FR.218 (final approver), FR.222 (approver)

### Type B — Planning Officer (CB internal, role: planner/officer)
Signs: FR.218 (preparer), FR.220 (IFC Global side), FR.221 (IFC Global side), FR.222 (preparer)

### Type C — Lead Auditor (assigned to stage, CB internal)
Signs: FR.224, FR.225 (opening + closing), FR.230, FR.231/229/232

### Type D — Additional Auditors & Technical Experts (CB internal)
Sign: FR.224, FR.225 (opening + closing)

### Type E — Certification Committee Reviewer (CB internal, special constraint)
Signs: FR.218 (reviewer slot — **FSMS/ISMS standards only**), FR.231/229/232 ("Reviewed and approved by")
**Constraint:** Must have EA code coverage for ALL standards in scope. Must NOT be any person assigned to the audit stages (Lead Auditor, Auditor, TE, Observer) for this plan.

### Type F — Client Representative (existing portal account)
Signs: FR.220, FR.221 (already built), FR.223, FR.230, FR.211

### Type G — External Meeting Attendees (guest tokens, no account)
Signs: FR.225 — both Opening and Closing signature columns
Variable number — CB enters their name, role/title, email before the meeting; system emails them a token link.

---

## Build Plan (Prompts 12–16)

### Prompt 12 — CB Internal Signing Queue
Add signature workflow for Certification Manager and Planning Officer.
- New `document_cb_signatures` table: doc_id, user_id, role_label, signed_at, signed_ip, otp_hash, otp_expires_at
- CB portal "Pending Signatures" widget on dashboard
- Covers: FR.218 (planner + cert_manager slots), FR.220 (cert_manager CB slot), FR.221 (cert_manager CB slot), FR.222 (planner + cert_manager slots)
- OTP signing same as client — but triggered from CB portal dashboard

### Prompt 13 — Audit Team Signatures (Auditor Portal)
- FR.224: Impartiality declaration — each assigned auditor/TE signs from their portal
- FR.225: Opening and closing — Lead Auditor + auditors/TEs sign from their portal (two separate signature events per person)
- FR.230: Lead Auditor signs NC form from auditor portal
- FR.231/229/232: Lead Auditor signs report from auditor portal
- Signing queue on auditor portal dashboard

### Prompt 14 — Certification Committee: Appointment + Review Signature
- New `audit_set_committee_members` table: audit_set_id, user_id, role (reviewer/decision_maker), appointed_by, ea_codes_at_appointment, appointed_at
- Appointment UI: admin/planner picks from a filtered list of CB staff (auditors/TEs):
  - Filter 1: EA codes must cover ALL standards in scope for this plan
  - Filter 2: Must not be assigned to any audit stage on this plan (Lead Auditor, Auditor, TE, Observer)
- Committee members get signing queue for: FR.218 (reviewer slot), reports ("Reviewed and approved by")

### Prompt 15 — Guest Token Signing (Opening/Closing Meeting Attendees)
- New `audit_set_meeting_attendees` table: stage_id, name, title, email, token (UUID), opening_signed_at, opening_signed_ip, closing_signed_at, closing_signed_ip, token_expires_at
- CB enters attendees (name, role, email) in FR.225 section of auditor portal
- System generates a token, emails a link: `/sign/meeting/{token}`
- Attendee opens link → sees what they're signing → enters OTP sent to their email → signs opening and/or closing (two separate OTP events)
- No account creation, link expires 72h or on completion

### Prompt 16 — Client Signatures on Additional Forms
- FR.223 (Audit Plan): Client portal gets "Sign Audit Plan" section — OTP signing
- FR.230 (NC Form): Client portal gets NC list with signature pending indicator
- FR.211 (Auditor Assessment): Client fills in rating + signs after each stage
