# Portal 90 — Surveillance "Failed to release document." is a false error

## Root cause

`load()` in `frontend/src/components/ui/SharedDocumentsSection.tsx` uses
`try/finally` with **no `catch`**:

```typescript
async function load() {
  try {
    const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
    setDocs(r.data)
  } finally {          // ← no catch — exceptions escape
    setLoading(false)
  }
}
```

In `release()`, `await load()` is called **inside** the outer try block (line ~153).
If the GET `/audit-sets/{id}/documents` call fails for any reason — a transient
server hiccup, a serialization error on an existing document row, anything — the
exception bubbles into the `catch (err)` below it, which sets:

```typescript
setError(detail || 'Failed to release document.')
```

The release POST already returned 200. The file is stored. The DB row exists.
The workflow status advanced to `notification_sent`. The Planner sees failure;
the system is actually fine.

---

## The fix

**File:** `frontend/src/components/ui/SharedDocumentsSection.tsx`

Find `load()` (around line 116):

```typescript
async function load() {
  try {
    const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
    setDocs(r.data)
  } finally {
    setLoading(false)
  }
}
```

Replace with:

```typescript
async function load() {
  try {
    const r = await api.get<SharedDoc[]>(`/audit-sets/${auditSetId}/documents`)
    setDocs(r.data)
  } catch {
    // A GET failure after a successful release must not surface as
    // "Failed to release document." — keep errors isolated.
  } finally {
    setLoading(false)
  }
}
```

That is the **only change** required.

---

## What does NOT change

- The release POST endpoint — unchanged.
- Any backend file — no changes.
- The rest of SharedDocumentsSection.tsx — unchanged.

---

## Commit message

```
Portal 90: fix false "Failed to release" when load() throws after successful POST

SharedDocumentsSection load() used try/finally without catch, so any
error from GET /documents propagated into the release() catch block and
displayed "Failed to release document." even though the POST had already
succeeded. Adding a catch block isolates GET failures from release errors.
```
