# Portal 73 — FR.225 short org-employee sig_key + CB_CERT_MANAGER for audit reports

## Context and what was already fixed

**Templates already patched (committed directly):**
- All UAF FR.225 templates: SIG marker runs now Calibri 8pt #B4B4B4 (was Times New Roman 10pt black)
- All UAF FR.231/FR.232 templates: `[APPOINTED_REVIEWER]` → `[CB_CERT_MANAGER]` 

**What still needs backend code changes (this portal):**
1. FR.225 org-employee sig_key is currently `ORG_EMP_<uuid>` (36-char UUID) — renders the full template marker as `[SIG:ORG_OPENING_ORG_EMP_<uuid>]` = 54 chars, which wraps across two PDF lines in the narrow cell, making pdfplumber miss the marker. Fix: use `ORG_EMP_1`, `ORG_EMP_2`, ... (short, never wraps).
2. `APPOINTED_REVIEWER` is gone from the templates — audit_report signing handlers (`_assert_can_sign` and `_get_field_status`) need to accept `CB_CERT_MANAGER` for FR.231/FR.232.

---

## Change 1 — `backend/audit_set/packager.py`

### Location: `_resolve_org_attendees` function, the employees list comprehension (~line 209–224)

**BEFORE:**
```python
employees = (
    db.query(ClientOrgEmployee)
    .filter_by(client_user_id=client.id, is_active=True)
    .order_by(ClientOrgEmployee.created_at)
    .all()
)
...
return [
    {"name": e.full_name, "role": e.role_title, "sig_key": f"ORG_EMP_{e.id}"}
    for e in employees
]
```

**AFTER:**
```python
employees = (
    db.query(ClientOrgEmployee)
    .filter_by(client_user_id=client.id, is_active=True)
    .order_by(ClientOrgEmployee.created_at)
    .all()
)
...
return [
    {"name": e.full_name, "role": e.role_title, "sig_key": f"ORG_EMP_{i}"}
    for i, e in enumerate(employees, 1)
]
```

The `sig_key` changes from `ORG_EMP_<uuid>` (UUID, 36 chars) to `ORG_EMP_1`, `ORG_EMP_2`, ... (max 10 chars). The template renders this as `[SIG:ORG_OPENING_ORG_EMP_1]` = 27 chars — fits on one line in any cell.

---

## Change 2 — `backend/audit_set/viewer_router.py`

Four surgical edits in one file:

### 2a — `ORG_SIG_RE` (~line 78)

**BEFORE:**
```python
ORG_SIG_RE = re.compile(
    r"^ORG_(OPENING|CLOSING)_ORG_EMP_([0-9a-fA-F-]{36})$"
)
```

**AFTER:**
```python
ORG_SIG_RE = re.compile(
    r"^ORG_(OPENING|CLOSING)_ORG_EMP_(\d+)$"
)
```

The regex now matches the short indexed form (`ORG_EMP_1`, `ORG_EMP_2`, ...) instead of UUIDs.
The capture group 2 is now the row index (string digit) instead of a UUID string.

**Downstream code that uses group 2 of ORG_SIG_RE:**
Any code that does `ORG_SIG_RE.match(sig_key).group(2)` to extract the employee ID (UUID) and look up the employee by ID must be updated to instead look up the employee by their 1-based position in the same ordered query used by packager:

```python
# NEW helper — resolves employee from row index
def _resolve_org_emp_by_index(audit_set_id: str, row_index: int, db: Session, auth_db: Session):
    """Return the ClientOrgEmployee at 1-based row_index (created_at order)."""
    client_user = auth_db.query(PlatformUser).filter_by(
        role="client", audit_set_id=audit_set_id
    ).first()
    if not client_user:
        return None
    employees = (
        db.query(ClientOrgEmployee)
        .filter_by(client_user_id=client_user.id, is_active=True)
        .order_by(ClientOrgEmployee.created_at)
        .all()
    )
    if 1 <= row_index <= len(employees):
        return employees[row_index - 1]
    return None
```

Wherever `ORG_SIG_RE.match(sig_key).group(2)` was used as a UUID to look up `ClientOrgEmployee.id == uuid`, replace with:
```python
row_idx = int(ORG_SIG_RE.match(sig_key).group(2))
emp = _resolve_org_emp_by_index(doc.audit_set_id, row_idx, db, auth_db)
```

### 2b — `SIG_KEY_ALIASES` (~line 115–122)

**BEFORE:**
```python
SIG_KEY_ALIASES: dict[str, str] = {
    "AUDITOR_MEMBER":      "ASSIGNED_AUDITOR",
    "CLIENT":              "ORG_REP",
    "CB_REVIEWER":         "APPOINTED_REVIEWER",  # FR.231 / FR.232 only (template-scoped)
    "CERT_MANAGER_REVIEW": "CERT_MANAGER_FR233",
}
```

**AFTER:**
```python
SIG_KEY_ALIASES: dict[str, str] = {
    "AUDITOR_MEMBER":      "ASSIGNED_AUDITOR",
    "CLIENT":              "ORG_REP",
    # Portal 73 — FR.231/FR.232 templates now use CB_CERT_MANAGER.
    # Keep aliases so existing VisualSignaturePlacement rows written under the
    # old names (CB_REVIEWER, APPOINTED_REVIEWER) still resolve at read-time.
    "CB_REVIEWER":         "CB_CERT_MANAGER",
    "APPOINTED_REVIEWER":  "CB_CERT_MANAGER",
    "CERT_MANAGER_REVIEW": "CERT_MANAGER_FR233",
}
```

### 2c — `_assert_can_sign` audit_report branch (~line 627)

**BEFORE:**
```python
elif sig_key == "CB_REVIEWER":
    # Portal 75 — CB_REVIEWER on audit_report is signed by the Certification
    # Manager directly (no committee appointment needed). Same pattern as the
    # CB_CERT_MANAGER slot on FR.218 (application review).
    if report.reviewer_signed_at:
        raise HTTPException(400, "Certification Manager has already signed this report")
    if current_user.role not in ("certification_manager", "admin"):
        raise HTTPException(403, "Only the Certification Manager may sign this slot")
    if not report.la_signed_at:
        raise HTTPException(
            400,
            "The Lead Auditor must sign before the Certification Manager can sign",
        )

else:
    raise HTTPException(400, f"Unexpected sig_key '{sig_key}' for audit_report")
```

**AFTER:**
```python
elif sig_key in ("CB_REVIEWER", "CB_CERT_MANAGER"):
    # Portal 73 — templates now use CB_CERT_MANAGER; CB_REVIEWER kept as alias.
    if report.reviewer_signed_at:
        raise HTTPException(400, "Certification Manager has already signed this report")
    if current_user.role not in ("certification_manager", "admin"):
        raise HTTPException(403, "Only the Certification Manager may sign this slot")
    if not report.la_signed_at:
        raise HTTPException(
            400,
            "The Lead Auditor must sign before the Certification Manager can sign",
        )

else:
    raise HTTPException(400, f"Unexpected sig_key '{sig_key}' for audit_report")
```

### 2d — `_get_field_status` audit_report branch (~line 849)

**BEFORE:**
```python
elif sig_key == "CB_REVIEWER":
    # Portal 75 — CB_REVIEWER on audit_report is the Certification Manager. ...
    if report.reviewer_signed_at:
        return _result("signed", _user_name(report.reviewer_user_id), ...)
    if not report.la_signed_at:
        return _result("blocked")
    cm_user = auth_db.query(PlatformUser).filter_by(
        role="certification_manager", is_active=True,
    ).first()
    reviewer_name = cm_user.full_name if cm_user else "Certification Manager"
    if current_user.role in ("certification_manager", "admin"):
        return _result("current_user", reviewer_name)
    return _result("pending", reviewer_name)
```

**AFTER:**
```python
elif sig_key in ("CB_REVIEWER", "CB_CERT_MANAGER"):
    # Portal 73 — templates now use CB_CERT_MANAGER; CB_REVIEWER kept as alias.
    if report.reviewer_signed_at:
        return _result("signed", _user_name(report.reviewer_user_id), ...)
    if not report.la_signed_at:
        return _result("blocked")
    cm_user = auth_db.query(PlatformUser).filter_by(
        role="certification_manager", is_active=True,
    ).first()
    reviewer_name = cm_user.full_name if cm_user else "Certification Manager"
    if current_user.role in ("certification_manager", "admin"):
        return _result("current_user", reviewer_name)
    return _result("pending", reviewer_name)
```

### 2e — Meeting_form seeding: employee sig_key ordering (~line 1272)

**BEFORE:**
```python
for emp in employees:
    db_sig_keys.add(f"ORG_OPENING_ORG_EMP_{emp.id}")
    db_sig_keys.add(f"ORG_CLOSING_ORG_EMP_{emp.id}")
```

**AFTER:**
```python
# Ordering MUST match packager._resolve_org_attendees (created_at).
for i, emp in enumerate(employees, 1):
    db_sig_keys.add(f"ORG_OPENING_ORG_EMP_{i}")
    db_sig_keys.add(f"ORG_CLOSING_ORG_EMP_{i}")
```

Also ensure the `employees` query above these lines uses `.order_by(ClientOrgEmployee.created_at)` — the same ordering as `packager.py`.

---

## What NOT to change

- The blank-placeholder path (`ORG_EMP_BLANK_N`, `ORG_BLANK_RE`) — untouched, still used when no employees are registered.
- `ORG_TEAM_RE` (audit-team slots LEAD_AUDITOR / AUDITOR_N / TE_N) — untouched.
- FR.233 committee signing handlers — untouched.
- `ROLE_TO_SIG` / `SIG_TO_ROLE` dicts — the `cb_cert_manager → CB_CERT_MANAGER` entry already exists; `appointed_reviewer → APPOINTED_REVIEWER` can stay for old DB records.
- Any other document type signing handler.
- The templates themselves (already patched in this commit).

---

## After deploying

1. **Existing FR.225 documents** in the system were generated with UUID-based markers. The PDF scan will now try to find `ORG_EMP_1`-style markers and won't find them in the old document (still has UUID markers). The `db_sig_keys` fallback from `eed1cfc` (seeding from roster) will supply the new short keys — the `unpositionedSignable` fallback will render "Sign as…" buttons. Planner clicks **Refresh FR.225** to regenerate; new document has short markers, overlay boxes appear on-page.
2. **Existing FR.231/FR.232 documents** signed with `APPOINTED_REVIEWER` VSP rows: `SIG_KEY_ALIASES` now maps `APPOINTED_REVIEWER → CB_CERT_MANAGER`, so those VSP rows still resolve. No DB migration needed.
3. **New FR.231/FR.232 documents** generated from the updated templates will use `CB_CERT_MANAGER` natively.

---

## Files to change

| File | Changes |
|------|---------|
| `backend/audit_set/packager.py` | `_resolve_org_attendees`: `sig_key = f"ORG_EMP_{i}"` (enumerate, 1-indexed) |
| `backend/audit_set/viewer_router.py` | `ORG_SIG_RE`: `\d+` instead of UUID; `SIG_KEY_ALIASES`: add APPOINTED_REVIEWER→CB_CERT_MANAGER, update CB_REVIEWER alias; `_assert_can_sign` audit_report: accept CB_CERT_MANAGER; `_get_field_status` audit_report: accept CB_CERT_MANAGER; meeting_form seeding: enumerate with created_at ordering |

---

## Commit message

```
Portal 73: FR.225 short org-emp sig_key + CB_CERT_MANAGER for audit reports

FR.225 org employee markers were ORG_EMP_<uuid> (54 chars) causing them to
wrap in narrow table cells and be missed by pdfplumber. Changed to ORG_EMP_N
(row-indexed, max ~11 chars, never wraps). Ordering matches packager created_at.

FR.231/FR.232 templates (already patched in this commit) now use [CB_CERT_MANAGER]
instead of [APPOINTED_REVIEWER]. Extended audit_report signing handlers to accept
CB_CERT_MANAGER with the same CM role check as CB_REVIEWER. Added SIG_KEY_ALIASES
entries so existing VSP rows written under APPOINTED_REVIEWER / CB_REVIEWER still
resolve without any DB migration.

Files: packager.py (1 line), viewer_router.py (4 locations)
Templates: all UAF FR.225 (font), all UAF FR.231/FR.232 (marker rename) — pre-patched
```
