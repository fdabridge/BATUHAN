# Augment Prompt — Company Reference Code (Client ID)

## Problem

The user enters company details when creating an audit set. They also want to enter a **company reference code** (e.g., `202601`, `13412`) — a custom identifier for the client. This code should:

1. **Appear as the Quotation No / Agreement No** in all generated documents (FR.220, FR.221, etc.) — replacing `plan_number` in document headers
2. **Be searchable** in the client portal list alongside company name
3. **Act as the client's second identity** — alongside company name, it uniquely identifies them

Currently, `plan_number` (auto-assigned, 4-digit, starts at 1600) is used in document headers. The user's codes are typically 5-6 digit values they assign themselves.

---

## What to Build

### 1. DB migration — add `client_reference` column

In `backend/audit_set/db_models.py`, add to `AuditSet`:

```python
# After plan_number:
client_reference = Column(String, nullable=True, index=True)
# User-entered identifier, e.g. "202601" or "ACC-2026-001"
# Used as Agreement No / Quotation No in documents.
# Falls back to str(plan_number) if not set.
```

Add migration in `create_tables()`:
```python
_safe_add_column("audit_sets", "client_reference VARCHAR")
```

### 2. Schema updates

In `backend/audit_set/schemas.py`:

**AuditSetCreateSchema** — add:
```python
client_reference: Optional[str] = None
```

**AuditSetUpdatePlanningSchema** — add:
```python
client_reference: Optional[str] = None
```

**AuditSetResponse** — add:
```python
client_reference: Optional[str] = None
```

**AuditSetSummarySchema** — add:
```python
client_reference: Optional[str] = None
```

**ClientSummarySchema** — add:
```python
client_reference: Optional[str] = None
```

### 3. Service layer

In `backend/audit_set/service.py`, in the create function:
```python
audit_set.client_reference = payload.client_reference or None
```

In the update function (`update_planning` or equivalent):
```python
if payload.client_reference is not None:
    audit_set.client_reference = payload.client_reference or None
```

### 4. Filler context — add `agreement_number`

In `backend/audit_set/filler.py`, in `build_base_context()`, add:

```python
# agreement_number: client_reference if set, else plan_number as string
"agreement_number": audit_set.client_reference or str(audit_set.plan_number),
```

### 5. Template context key

The templates currently use `{{ plan_number }}` in document headers. We want to keep `plan_number` in the context (for backward compat) but **add `agreement_number`** as the display key.

The templates should use `{{ agreement_number }}` for the Quotation No / Agreement No cell. However, changing all templates via Python script would be extensive. Instead:

**Simpler approach:** In `filler.py`, override `plan_number` in the context to use `agreement_number`:

```python
"plan_number": audit_set.client_reference or audit_set.plan_number,
```

This way ALL templates using `{{ plan_number }}` will automatically show the client reference code when set, without any template changes. The `plan_number` variable in the context becomes the "display number" (client_reference if set, otherwise the DB plan_number).

Keep `"plan_number_internal": audit_set.plan_number` as a separate key if needed.

### 6. Frontend changes

#### Audit Set creation form — add "Client Reference Code" field
- **Location:** Immediately after "Company Name" (it's closely related to the client's identity)
- **Label:** "Client Reference / Agreement No"
- **Placeholder:** "e.g. 202601"
- **Type:** Text input (allow alphanumeric + dashes)
- **Required:** No (falls back to plan_number if empty)
- **Helper text:** "Used as the Agreement No and Quotation No in all documents. If left blank, the system assigns one automatically."

#### Client portal list — add reference code to search and display
In the client portal list view:
- Show `client_reference` next to company name in each row (if set): e.g. "[202601] tayland"
- Include `client_reference` in the search query so users can find clients by their code
- In the API search endpoint (`GET /audit-sets?search=...`), add `client_reference` to the `ilike` filter alongside `company_name`

Find the search query in `service.py` (likely something like):
```python
query = query.filter(AuditSet.company_name.ilike(f"%{search}%"))
```
Change to:
```python
from sqlalchemy import or_
query = query.filter(or_(
    AuditSet.company_name.ilike(f"%{search}%"),
    AuditSet.client_reference.ilike(f"%{search}%"),
))
```

---

## Testing

1. Create a new audit set with Client Reference "202601"
2. Download the audit package
3. Open FR.220 — Quotation No should show "202601" (not "1603" or whatever plan_number is)
4. Open FR.221 — Agreement No should show "202601"
5. In the portal client list, search for "202601" — the client should appear

## Commit

```bash
git add backend/audit_set/
git add frontend/  # wherever the frontend form changes are
git commit -m "feat: company reference code — custom client ID shown as Agreement/Quotation No in docs, searchable in portal"
git push
```
