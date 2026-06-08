# Portal Build — Prompt 1 of 8: DB Extensions + Role System

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
This is purely additive. Do NOT modify any existing column, existing route, existing API endpoint,
or existing frontend page. Only ADD new columns, new tables, and extend the roles list.
Existing `platform_users` rows, `audit_sets` rows, and all existing functionality must continue
to work exactly as before.

---

## Context

The existing system has:
- `platform_users` table with roles: `admin | planner | auditor | officer | executive`
- `audit_sets` table tracking certification jobs
- `_safe_add_column()` helper in `audit_set/db_models.py` that safely adds columns to existing tables

We are building a multi-stakeholder portal. This prompt adds the database foundation.

---

## Task

### 1. Add `client` role to auth system

In `backend/auth/schemas.py`:
```python
# Change:
VALID_ROLES = {"admin", "planner", "auditor", "officer", "executive"}
# To:
VALID_ROLES = {"admin", "planner", "auditor", "officer", "executive", "client"}
```

In `backend/auth/db_models.py`, update the docstring comment to include `client`:
```python
# role choices: "admin" | "planner" | "auditor" | "officer" | "executive" | "client"
```

### 2. Add `audit_set_id` column to `platform_users`

Client accounts are linked to their audit set. Add this column to `PlatformUser`:
```python
audit_set_id = Column(String, nullable=True)   # soft FK → audit_sets.id (client role only)
```

In `auth/db_models.py` `create_tables()`, add the migration:
```python
_safe_add_column_auth("platform_users", "audit_set_id VARCHAR")
```

You'll need to add `_safe_add_column_auth` in `auth/db_models.py` — it's the same pattern as `_safe_add_column` in `audit_set/db_models.py`:
```python
def _safe_add_column_auth(table: str, col_def: str) -> None:
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
            conn.commit()
        except Exception:
            pass
```

### 3. Add `workflow_status` column to `audit_sets`

In `audit_set/db_models.py`, add to `AuditSet` class:
```python
# ── Client portal workflow ─────────────────────────────────────────────────
# workflow_status tracks the certification lifecycle for the client portal.
# Separate from `status` (which is the internal planning status: draft/planning/complete).
# Valid values:
#   pending_review    → client submitted application, CB reviewing
#   in_planning       → CB approved, doing man-days/auditor assignment
#   quotation_sent    → FR.220 released to client portal
#   agreement_signed  → FR.220 + FR.221 both signed by client
#   audit_scheduled   → audit dates confirmed by both sides
#   audit_in_progress → audit underway
#   under_review      → auditor uploaded docs, CB technical review
#   certified         → certificate issued
# NULL = audit set created internally (not via client portal) — existing records
workflow_status       = Column(String, nullable=True)
submitted_via_portal  = Column(Boolean, default=False, nullable=False, server_default="0")
```

In `audit_set/db_models.py` `create_tables()`, add migrations:
```python
_safe_add_column("audit_sets", "workflow_status VARCHAR")
_safe_add_column("audit_sets", "submitted_via_portal BOOLEAN DEFAULT 0")
```

### 4. Add `status_events` table

This is a new table in `audit_set/db_models.py`. Add the class AND include it in `Base.metadata.create_all`:

```python
class AuditSetStatusEvent(Base):
    __tablename__ = "audit_set_status_events"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id   = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    from_status    = Column(String, nullable=True)   # null for initial creation event
    to_status      = Column(String, nullable=False)
    triggered_by   = Column(String, nullable=True)   # user id or "system"
    triggered_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes          = Column(Text, nullable=True)
```

### 5. Add `messages` table

New table in `audit_set/db_models.py`:

```python
class AuditSetMessage(Base):
    __tablename__ = "audit_set_messages"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id  = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    sender_user_id = Column(String, nullable=False)
    sender_name   = Column(String, nullable=False)
    sender_role   = Column(String, nullable=False)   # "client" | "planner" | "auditor" etc.
    body          = Column(Text, nullable=False)
    attachment_url = Column(String, nullable=True)   # optional file link
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    read_by       = Column(JSON, default=list)        # list of user ids who have read this
```

### 6. Add `documents_shared` table

New table in `audit_set/db_models.py`:

```python
class AuditSetSharedDocument(Base):
    __tablename__ = "audit_set_shared_documents"

    id                 = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id       = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    label              = Column(String, nullable=False)   # e.g. "Quotation (FR.220)", "Agreement (FR.221)"
    document_type      = Column(String, nullable=False)   # "quotation" | "agreement" | "audit_upload" | "certificate"
    file_path          = Column(String, nullable=True)    # server-side path (for CB-generated docs)
    direction          = Column(String, nullable=False, default="cb_to_client")
    # direction: "cb_to_client" (CB releases to client) | "auditor_to_cb" (auditor uploads to CB)
    status             = Column(String, nullable=False, default="released")
    # status: "released" | "signed" | "uploaded"
    released_by        = Column(String, nullable=True)    # user id
    released_at        = Column(DateTime, nullable=True)
    signed_by          = Column(String, nullable=True)    # user id
    signed_at          = Column(DateTime, nullable=True)
    signed_ip          = Column(String, nullable=True)
    otp_hash           = Column(String, nullable=True)    # bcrypt hash of OTP
    otp_expires_at     = Column(DateTime, nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
```

### 7. Update `AuditSetResponse` schema to include new fields

In `audit_set/schemas.py`, add to `AuditSetResponse`:
```python
workflow_status:      Optional[str] = None
submitted_via_portal: bool = False
```

### 8. Verify everything starts cleanly

After changes:
- Run `python -c "from audit_set.db_models import create_tables; create_tables(); print('OK')"` — must print OK
- Run `python -c "from auth.db_models import create_tables; create_tables(); print('OK')"` — must print OK
- Existing audit sets must still be readable (workflow_status will be None for them, that's correct)

### Commit and push

Commit: `feat(portal): add client role, workflow_status, messages, documents_shared, status_events tables`
Push to main.

## Files to edit
- `backend/auth/schemas.py` — add `client` to VALID_ROLES
- `backend/auth/db_models.py` — add `audit_set_id` column + `_safe_add_column_auth` + migration
- `backend/audit_set/db_models.py` — add `workflow_status`, `submitted_via_portal` to AuditSet + 3 new tables + migrations
- `backend/audit_set/schemas.py` — add `workflow_status`, `submitted_via_portal` to AuditSetResponse
