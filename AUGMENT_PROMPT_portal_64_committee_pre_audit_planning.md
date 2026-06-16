# Portal 64 — Certification Committee: Move to Pre-Audit Planning

## Context

The certification committee signs only FR.233 (Review and Decision Form). It does
not appear in any other document. Looking at FR.233, there are no rows below the
committee signing block — the committee is the final sign-off before the certificate.

The committee is conceptually identical to the audit team picker (Stage 1 and Stage 2
auditors), with one constraint: committee members must NOT be on the audit team for
this specific audit. They are picked at the same time as the audit team — during
planning, before the audit starts — not after Stage 2.

**Portal 62's post-audit committee appointment UI must be removed.** Committee
appointment moves to the planning phase.

---

## What is the committee

- Auditors from the auditor pool (same `Auditor` model as Stage 1/Stage 2 team members)
- Selected so that collectively they cover ALL of the audit's standards and EA codes
- None of them may be on the Stage 1 or Stage 2 audit team for this audit set
- First selected = Chairperson; remaining = Members
- They sign FR.233 at the end of the pipeline

---

## Part A — Remove Portal 62's Post-Audit Committee UI

### What to remove

Portal 62 added a committee appointment section that appears after Stage 2 in the
workflow. Remove it entirely:

- Remove `GET /audit-sets/{id}/committee/available-auditors` endpoint (Portal 62)
- Remove `POST /audit-sets/{id}/committee/appoint-team` endpoint (Portal 62)
- Remove the committee picker page/section from the post-Stage-2 frontend workflow

Keep the `audit_sets.committee_members` TEXT (JSON) column — it is still used, just
populated earlier (at planning time now).

---

## Part B — Add Committee Picker to Audit Planning

### Where it lives

In the audit planning UI where the planner currently picks Stage 1 and Stage 2
auditor teams, add a third section: **Certification Committee**.

The three sections of the planning form:
1. Stage 1 Team (existing) — Lead Auditor + Auditors + Technical Experts
2. Stage 2 Team (existing) — same structure
3. Certification Committee (new) — Chairperson + Members

All three sections are planned together and submitted as part of the same planning
payload. The committee is confirmed at the same time as the audit team.

### Backend — new endpoint: available committee members

```
GET /audit-sets/{audit_set_id}/planning/committee/available-auditors
```

This replaces Portal 62's available-auditors endpoint. Called during planning, so
it excludes auditors from the CURRENT planning form selection (not necessarily DB-saved
yet). The frontend passes the current Stage 1 and Stage 2 selections so the backend
can compute exclusions:

```
GET /audit-sets/{audit_set_id}/planning/committee/available-auditors
  ?exclude_auditor_ids=uuid1,uuid2,uuid3
```

Or accept as query params. Response structure same as Stage auditor picker:

```json
[
  {
    "id": "uuid",
    "full_name": "Ahmet Yıldız",
    "auditor_code": "AUD-001",
    "standards": ["ISO 9001", "ISO 14001"],
    "ea_codes": ["29", "30"],
    "covers_audit": true
  }
]
```

Filter:
- Active auditors only (`is_active = true`)
- Exclude any auditor whose ID is in `exclude_auditor_ids`
- Sort: `covers_audit = true` first

Coverage check per auditor: `auditor.standards` intersects `audit_set.standards`
AND `auditor.ea_codes` intersects `audit_set.ea_codes`.

### Backend — save committee with planning payload

Extend the existing planning save endpoint (wherever Stage 1/Stage 2 team is saved)
to also accept and persist the committee:

```python
# In the planning save handler:
if payload.committee_members:
    # Validate: no overlap with Stage 1 or Stage 2 team
    stage1_ids = {a["id"] for a in payload.stage1_auditors} | {payload.stage1_lead_auditor_id}
    stage2_ids = {a["id"] for a in payload.stage2_auditors} | {payload.stage2_lead_auditor_id}
    all_team_ids = stage1_ids | stage2_ids
    
    committee_ids = {m["id"] for m in payload.committee_members}
    overlap = committee_ids & all_team_ids
    if overlap:
        raise HTTPException(422, f"Committee members cannot be on the audit team: {overlap}")
    
    # Validate: collectively covers all standards and EA codes
    covered_standards = set()
    covered_ea_codes = set()
    for member in payload.committee_members:
        covered_standards |= set(member.get("standards", []))
        covered_ea_codes |= set(member.get("ea_codes", []))
    
    missing_standards = set(audit_set.standards) - covered_standards
    missing_ea_codes = set(audit_set.ea_codes) - covered_ea_codes
    if missing_standards or missing_ea_codes:
        raise HTTPException(422, 
            f"Committee does not cover: standards={missing_standards}, ea_codes={missing_ea_codes}")
    
    # Store denormalized on audit_set (first member = chairperson)
    committee_data = [
        {
            "id": m["id"],
            "name": m["full_name"],
            "ea_codes": m.get("ea_codes", []),
            "standards": m.get("standards", []),
            "role": "chairperson" if i == 0 else "member"
        }
        for i, m in enumerate(payload.committee_members)
    ]
    audit_set.committee_members = json.dumps(committee_data)
    db.flush()
```

### Frontend — committee section in planning UI

Add a third picker section in the planning form, after the Stage 2 team:

```
┌─────────────────────────────────────────────────────┐
│  Certification Committee                             │
│                                                      │
│  Must collectively cover all standards and EA codes. │
│  Cannot include any Stage 1 or Stage 2 team member.  │
│                                                      │
│  [Available auditors pool]    [Selected committee]   │
│  - Ahmet Y. ✓ covers          Chairperson: Mehmet K. │
│  - Mehmet K. ✓ covers         Member:      Ayşe D.   │
│  - Fatma D. (excluded:        Member:      ...       │
│    on Stage 1 team)                                  │
│                                                      │
│  Coverage: ISO 9001 ✓  ISO 14001 ✓  EA 29 ✓         │
└─────────────────────────────────────────────────────┘
```

- Left panel: call `GET /planning/committee/available-auditors?exclude_auditor_ids=...`
  passing the CURRENT (unsaved) Stage 1 + Stage 2 selections as exclude list
  — this auto-excludes audit team members in real time as the planner selects them
- Right panel: selected committee members; first = Chairperson, rest = Members
- Coverage indicator: show which standards/EA codes are covered by current selection
- Error if any standard or EA code is uncovered (disable "Save Plan" button)
- Auditors already on Stage 1 or Stage 2 team shown as greyed out / excluded

The committee picker re-queries available-auditors when Stage 1 or Stage 2
selections change (so the exclusion list stays live).

---

## Part C — FR.233 Packager: Unchanged

The packager already reads `audit_set.committee_members` (JSON) and injects it into
the FR.233 docxtpl context. No change needed — committee is now stored earlier
(at planning time) but the same JSON column is used.

---

## Part D — Viewer: Unchanged

`COMMITTEE_MEMBER_RE` signing (Portal 62 + 63) is unchanged. Committee members
are stored in `committee_members` JSON at planning time; the viewer reads that
snapshot to identify who can sign each `COMMITTEE_MEMBER_<id>` slot. No change needed.

---

## Part E — Workflow Gate: Unchanged

The gate requiring all `COMMITTEE_MEMBER_*` slots to be signed before CM signs
`CERT_MANAGER_REVIEW` (Portal 62 Part E) remains in place. No change needed.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/audit_set_router.py` | Remove Portal 62's `GET /committee/available-auditors` and `POST /committee/appoint-team`; add `GET /planning/committee/available-auditors?exclude_auditor_ids=...` |
| `backend/audit_set/audit_set_router.py` (or `workflow_router.py`) | Extend planning save endpoint to accept + validate + store `committee_members` JSON |
| `frontend/.../planning/page.tsx` (or equivalent) | Add Certification Committee section (third picker, exclusion logic, coverage indicator) |
| `frontend/.../committee/page.tsx` (Portal 62 UI) | Remove post-audit committee appointment page entirely |

No changes needed to: `packager.py`, `viewer_router.py`, `workflow_router.py` gate,
FR.233 templates, `audit_sets.committee_members` column.

---

## Commit message

```
Portal 64: certification committee appointment moves to pre-audit planning

Committee members are picked alongside Stage 1/Stage 2 audit teams during
planning, before the audit starts. Post-audit committee appointment UI removed.

- Remove Portal 62 endpoints: GET /committee/available-auditors,
  POST /committee/appoint-team
- Add GET /planning/committee/available-auditors?exclude_auditor_ids=...
  Excludes current Stage 1 + Stage 2 selections; coverage flag per auditor
- Planning save: validate committee (no team overlap, full coverage),
  store as committee_members JSON on audit_set
- Frontend planning: third picker section (Chairperson + Members),
  live exclusion as Stage 1/2 selections change, coverage indicator
- Remove post-Stage-2 committee appointment page (Portal 62 UI)

Packager, viewer, workflow gate, FR.233 templates unchanged —
they already read from audit_set.committee_members.
```
