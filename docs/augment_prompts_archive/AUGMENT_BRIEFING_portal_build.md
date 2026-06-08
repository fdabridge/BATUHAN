# Briefing: Multi-Stakeholder Portal Build

## What Certiva Is

Certiva is a certification body (CB) management platform built for IFC Global LLC. It manages the full ISO certification lifecycle: client intake, audit planning (man-day calculation, auditor assignment, EA code derivation), document package generation (FR.218–FR.232 DOCX templates filled via docxtpl), and certificate issuance.

**Tech stack:**
- Backend: FastAPI + SQLAlchemy + SQLite (migrating to PostgreSQL on Railway)
- Frontend: Next.js 14 (App Router) + Tailwind + Radix UI + React Query + Axios
- Auth: JWT-based, `platform_users` table with roles: `admin | planner | auditor | officer | executive`
- Deployment: Railway (backend + frontend as separate services)
- Email: Resend (to be added)

**Current portal structure:**
- `frontend/src/app/(app)/` — internal CB portal (all current pages live here)
- `frontend/src/app/(auth)/` — login page
- Backend routers: `audit_set/`, `auditors/`, `auth/`, `calculator/`, `pipeline/`

The existing portal is live and working. IFC Global staff use it daily.

---

## What We Are Building

A **multi-stakeholder portal extension** that adds three new portals on top of the existing system, without touching or breaking anything that already works.

### The Three Portals

**1. Client Portal (`/client/*`)**
A prospective client submits a certification application via a public form at `/apply`. They receive login credentials by email. They log in and can see their certification status (timeline from Application → Certified), documents shared with them, and a message thread with IFC Global.

**2. Internal Portal (existing `(app)/*` — extended)**
CB coordinators get a new "Applications" queue showing submissions from the client portal. They review, complete the missing fields (fees, EA codes, auditor assignment), and approve. The rest of the internal workflow is unchanged.

**3. Auditor Portal (`/auditor/*`)**
Auditors (who already have `platform_users` accounts with `auditor_id` linking to their profile) get a dedicated portal showing their assigned audits, client info, scope, audit dates, a message thread with the client, and the ability to upload completed audit documents.

### The Certification Lifecycle (workflow_status on audit_sets)

```
pending_review → in_planning → quotation_sent → agreement_signed
→ audit_scheduled → audit_in_progress → under_review → certified
```

- `pending_review`: client submitted, CB hasn't reviewed yet
- `in_planning`: CB approved application, doing planning work
- `quotation_sent`: CB released FR.220 (Quotation) to client portal for signing
- `agreement_signed`: both FR.220 + FR.221 signed by client via OTP
- `audit_scheduled`: audit dates confirmed
- `audit_in_progress`: audit underway
- `under_review`: auditor uploaded completed docs, CB reviewing
- `certified`: certificate issued

### Document Signing

Documents (quotation FR.220, agreement FR.221) are released by CB to the client portal. Client signs via OTP — they click "Sign", receive a 6-digit code by email, enter it, and the system records timestamp + IP. No DocuSign needed; this satisfies ISO 17021-1 §9.5 traceability requirements.

### Messaging

Every audit set has a threaded message log accessible by CB, client, and auditor. All messages stored with sender, role, and timestamp — replacing WhatsApp/email/phone for ISO 17021-1 §8.4 communication traceability. Implemented with 10-second polling (no WebSocket).

### New DB Tables (all additive — no existing tables modified)

- `audit_set_status_events` — log of every workflow_status transition
- `audit_set_messages` — message threads per audit set
- `audit_set_shared_documents` — documents released to client or uploaded by auditor

### New Columns (added safely via `_safe_add_column`)

- `platform_users.audit_set_id` — links client accounts to their audit set
- `audit_sets.workflow_status` — the lifecycle stage (nullable; existing rows get null)
- `audit_sets.submitted_via_portal` — boolean flag

### New Role

`client` added to `VALID_ROLES` in `auth/schemas.py`. Client users can only access `/client/*` routes.

---

## The Single Most Important Constraint

**DO NOT BREAK THE EXISTING PORTAL.**

Every change is additive. Existing routes, pages, components, API endpoints, and database columns are untouched. Existing audit sets (with `workflow_status = null`) continue to work exactly as before. The `(app)` route group is not reorganized. No existing functionality is modified — only new files, new routes, and new columns are added.

---

## How We Will Work

I will send you 8 prompts, one at a time, in order. Each prompt is self-contained and builds on the previous one. Do not start the next prompt until you have committed and pushed the current one.

The prompts are numbered 01–08:
01 — DB + Role Extension
02 — Email Service (Resend)
03 — Public Application Form
04 — CB Applications Queue + Workflow Status API
05 — Client Portal Pages
06 — Messaging System
07 — Document Sharing + OTP Signing
08 — Auditor Portal

Wait for the first prompt now.
