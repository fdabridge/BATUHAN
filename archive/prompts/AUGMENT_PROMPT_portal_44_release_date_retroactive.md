# AUGMENT PROMPT — Portal 44: All Dates Must Be Editable (Retroactive Mode — Universal)

## Rule

Every date in the system that is recorded as a result of a user-triggered action must be
editable at the time of the action, defaulting to today. No date should ever be silently
set to `datetime.now()`, `datetime.utcnow()`, or `date.today()` without giving the user
the option to change it first.

This retroactive mode was established in Prompts 33/34. This prompt extends it universally
to every remaining place in the codebase where a date is still being auto-set.

---

## Audit Every Date in the System

Search the entire backend codebase for every occurrence of:
- `datetime.now()`
- `datetime.utcnow()`
- `date.today()`
- `datetime.utcnow().date()`

For each occurrence, determine: is this a user-triggered action (something the user
explicitly does)? If yes → replace with an optional request body param that defaults to
today. If no (e.g. internal `created_at` row timestamps, token expiry calculations,
scheduled job timestamps) → leave as-is.

---

## Specific Dates That Must Be Editable

Every one of these must show a date field in its modal/form, defaulting to today,
fully editable by the user:

### Documents
- **Document release date** — when "+ Release Document" is clicked
- **Document upload date** — when auditor uploads the filled stage package
- **Filled set received date** — when the system records that the auditor returned docs

### Signatures
- **Signing date** — when any user signs any document (already fixed in Portal 41 for
  some paths — verify all paths are covered, including FR.218, FR.222, FR.224, FR.225
  opening, FR.225 closing, FR.230, FR.231, FR.232, FR.229, FR.211)

### Audit stages
- **Stage start date** — already editable via date picker, confirm it is saved correctly
- **Stage end date** — same
- **Stage save date** (if recorded separately) — must be editable

### NC forms (FR.230)
- **NC raised date** — when an NC is recorded
- **NC response date** — when client responds to an NC
- **NC closed date** — when the NC is closed/resolved

### Reports
- **Report date** — the date on the audit report (FR.231/232/229), editable when
  generating or uploading the report

### Certification
- **Certification decision date** — when the certification manager records the decision
- **Certificate issue date** — when the certificate is generated and released
- **Certificate expiry date** — should be auto-calculated (issue + 3 years) but also
  manually overridable

### Assessments
- **Auditor assessment date** — when FR.211 is submitted/signed by client

### Committee
- **Committee appointment date** — when committee members are appointed

### Meetings
- **Opening meeting date** — when FR.225 opening section is completed
- **Closing meeting date** — when FR.225 closing section is completed

---

## Implementation Pattern

For every date listed above, the pattern is the same:

**Backend:**
```python
class SomeActionRequest(BaseModel):
    action_date: Optional[date] = None
    # ... other fields

# In endpoint:
record.some_date = payload.action_date or date.today()
```

**Frontend:**
Every modal or form that triggers one of these actions must include a date field:
```
Date: [ 11/06/2026 ]  ← editable input, defaults to today
```

The field label should be descriptive: "Release date", "Signing date", "NC raised date",
"Report date", etc.

---

## What NOT to change

- Internal DB row timestamps (`created_at`, `updated_at`) — these are system-generated,
  not user-facing, leave as `datetime.utcnow()`
- Token expiry timestamps — security-critical, must use real time
- Scheduled job / background task timestamps — leave as-is
- Audit log / system log timestamps — leave as-is

---

## Verification

Grep the backend for any remaining `datetime.now()` / `datetime.utcnow()` / `date.today()`
calls in user-triggered endpoints after this fix. There should be zero in any endpoint
that handles a user action. Any remaining ones should only be in internal/system code.
