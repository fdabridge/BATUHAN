# Portal 74 — FR.225 org-employee dialog: update frontend regex for digit-indexed sig_key

## What is broken and why

Portal 73 changed org-employee sig_keys from UUID-based (`ORG_EMP_<uuid>`) to
digit-indexed (`ORG_EMP_1`, `ORG_EMP_2`, …). The backend `ORG_SIG_RE`, the
packager, the seeding code, and the `sign_confirm` endpoint were all updated.

**One file was missed: `frontend/src/components/SignatureConfirmDialog.tsx`.**

It contains:

```ts
// Portal 73 — UUID-based org-employee slots embedded in sig_key (FR.225).
// Format: ORG_OPENING_ORG_EMP_<uuid> | ORG_CLOSING_ORG_EMP_<uuid>
const ORG_EMP_RE = /^ORG_(OPENING|CLOSING)_ORG_EMP_([0-9a-fA-F-]{36})$/
```

After Portal 73, the sig_key arriving at this dialog is `ORG_OPENING_ORG_EMP_1`
(a short digit, never 36 hex chars). The regex produces `null`. As a result:

- `isOrgEmpSlot = false`
- `needsEmployeePicker = false` (key is not in `CLIENT_SIDE_SIG_KEYS`)
- Falls through to the **personal-signature-setup** branch → wrong dialog

### Why the boxes also show as clock (pending) and not pen

Separately: after Portal 73 was deployed, the `/viewer/prepare` cache in
`DocumentSignatureField` still holds the **old UUID-based** sig_keys that were
scanned from the document that existed before Portal 73. Those old UUID keys
no longer match the updated backend `ORG_SIG_RE = \d+` regex, so
`_get_field_status` returns `"pending"` for them → clock icon on the positioned
overlay boxes.

This second issue resolves **automatically** once the planner clicks
**"Refresh FR.225"** (which calls the regeneration endpoint, clears the
`DocumentSignatureField` cache, deletes the old PDF, and re-seeds) and then
reopens the document in the viewer (which triggers `/viewer/prepare` to scan the
new short-marker PDF). No backend code change is needed for this part.

The only code change required is the frontend regex fix below.

---

## Change — `frontend/src/components/SignatureConfirmDialog.tsx`

Four surgical edits, all related to switching from UUID lookup to digit-index lookup.

---

### Edit 1 — `ORG_EMP_RE` (~line 43)

**BEFORE:**
```ts
// Portal 73 — UUID-based org-employee slots embedded in sig_key (FR.225).
// Format: ORG_OPENING_ORG_EMP_<uuid> | ORG_CLOSING_ORG_EMP_<uuid>
// The employee is already determined by the key — no picker needed.
const ORG_EMP_RE = /^ORG_(OPENING|CLOSING)_ORG_EMP_([0-9a-fA-F-]{36})$/
```

**AFTER:**
```ts
// Portal 74 — digit-indexed org-employee slots (FR.225 after Portal 73).
// Format: ORG_OPENING_ORG_EMP_<N> | ORG_CLOSING_ORG_EMP_<N>  (N is 1-based)
// The employee is resolved by position — no picker needed.
const ORG_EMP_RE = /^ORG_(OPENING|CLOSING)_ORG_EMP_(\d+)$/
```

---

### Edit 2 — derived match values (~line 84–87)

**BEFORE:**
```ts
  // Portal 73 — UUID-embedded org-employee slots (FR.225 opening/closing rows).
  // The employee is already identified by the sig_key — no picker needed.
  const orgEmpMatch    = ORG_EMP_RE.exec(sigKey)
  const isOrgEmpSlot   = orgEmpMatch !== null
  const orgEmpUuid     = orgEmpMatch ? orgEmpMatch[2] : null
  const orgEmpPhase    = orgEmpMatch ? orgEmpMatch[1] : null   // 'OPENING' | 'CLOSING'
```

**AFTER:**
```ts
  // Portal 74 — digit-indexed org-employee slots (FR.225 opening/closing rows).
  // The employee is resolved by 1-based row index (created_at order) — no picker needed.
  const orgEmpMatch    = ORG_EMP_RE.exec(sigKey)
  const isOrgEmpSlot   = orgEmpMatch !== null
  const orgEmpIndex    = orgEmpMatch ? parseInt(orgEmpMatch[2]) : null  // 1-based
  const orgEmpPhase    = orgEmpMatch ? orgEmpMatch[1] : null   // 'OPENING' | 'CLOSING'
```

---

### Edit 3 — useEffect: employee fetch by index (~line 98–116)

**BEFORE:**
```ts
    // Portal 73 — UUID-embedded employee slot: fetch that specific employee.
    if (isOrgEmpSlot && orgEmpUuid) {
      api.get('/org/employees')
        .then((r) => {
          const list: OrgEmployee[] = Array.isArray(r.data) ? r.data : []
          const emp = list.find((e) => e.id === orgEmpUuid) ?? null
          setOrgEmployee(emp)
          if (!emp || !emp.has_signature) {
            setStage('no_signature')
          } else {
            return api.get(`/org/employees/${orgEmpUuid}/signature`).then((sr) => {
              setSigImage(sr.data?.image_data ?? null)
              setStage('preview')
            })
          }
        })
        .catch(() => {
          setOrgEmployee(null)
          setStage('no_signature')
        })
      return
    }
```

**AFTER:**
```ts
    // Portal 74 — digit-indexed employee slot: fetch by 1-based position in
    // created_at-ordered roster (mirrors packager._resolve_org_attendees).
    if (isOrgEmpSlot && orgEmpIndex !== null) {
      api.get('/org/employees')
        .then((r) => {
          const list: OrgEmployee[] = Array.isArray(r.data) ? r.data : []
          const emp = list[orgEmpIndex - 1] ?? null   // 0-based array index
          setOrgEmployee(emp)
          if (!emp || !emp.has_signature) {
            setStage('no_signature')
          } else {
            return api.get(`/org/employees/${emp.id}/signature`).then((sr) => {
              setSigImage(sr.data?.image_data ?? null)
              setStage('preview')
            })
          }
        })
        .catch(() => {
          setOrgEmployee(null)
          setStage('no_signature')
        })
      return
    }
```

---

### Edit 4 — useEffect dependency array (~line 151)

**BEFORE:**
```ts
  }, [isOpen, sigKey, needsEmployeePicker, isOrgEmpSlot, orgEmpUuid])
```

**AFTER:**
```ts
  }, [isOpen, sigKey, needsEmployeePicker, isOrgEmpSlot, orgEmpIndex])
```

---

## What does NOT change

- `handleConfirm`: the backend resolves the employee from the sig_key's digit
  index — no `employee_id` needed in the request body for `isOrgEmpSlot` slots.
  The existing logic (`if (needsEmployeePicker) body.employee_id = selectedEmpId`)
  is already correct and remains unchanged.
- `resolveSigLabel`: uses `orgEmpPhase` (still valid) and the `orgEmployee` state
  object — no change.
- The `no_signature` and `preview` JSX branches for `isOrgEmpSlot`: use
  `orgEmployee` state — no change.
- `needsEmployeePicker`, `employees`, `selectedEmpId`, `selectedEmp`: unchanged.
- Backend: no changes. `sign_confirm` already resolves the employee by row index
  from the sig_key. `regenerate_meeting_form` already clears the
  `DocumentSignatureField` cache when called.

---

## After deploying

1. **Push and Railway redeploy** (frontend only — no backend change).
2. **In the planner UI**: find the audit set → FR.225 card → click
   **"Refresh FR.225"** for both Stage 1 and Stage 2. This clears the stale
   `DocumentSignatureField` rows, deletes the old PDF, and overwrites the DOCX
   with fresh short-marker content.
3. **Re-open the document** in the client portal viewer. The viewer calls
   `/viewer/prepare`, pdfplumber re-scans the new PDF, and finds
   `ORG_OPENING_ORG_EMP_1` etc. (27-char markers that fit in narrow cells).
4. **Signing-status** now returns `"current_user"` for the client on those keys
   → pen icon on the overlay boxes (clickable on-the-spot).
5. **Clicking a box** opens `SignatureConfirmDialog` with `ORG_OPENING_ORG_EMP_1`
   as `sigKey`. The updated regex matches, `isOrgEmpSlot = true`, `orgEmpIndex = 1`.
   The component fetches `/org/employees`, picks `list[0]` (the first employee),
   shows their name + signature preview. Client confirms → signed on the spot.

---

## Files to change

| File | Changes |
|------|---------|
| `frontend/src/components/SignatureConfirmDialog.tsx` | 4 edits: regex `\d+`, `orgEmpUuid`→`orgEmpIndex`, employee lookup by index, dep array |

No backend changes. No template changes.

---

## Commit message

```
Portal 74: FR.225 client signing — update frontend regex for digit-indexed sig_key

Portal 73 changed org-employee sig_keys from ORG_EMP_<uuid> to ORG_EMP_N
(1-based index). SignatureConfirmDialog.tsx still had the old UUID regex,
so ORG_OPENING_ORG_EMP_1 never matched → isOrgEmpSlot = false → dialog
fell through to the personal-signature-setup branch instead of showing the
employee's info and signature.

Fix: update ORG_EMP_RE to \d+, rename orgEmpUuid → orgEmpIndex, resolve
the employee by list[orgEmpIndex - 1] from the created_at-ordered roster
(same order as packager._resolve_org_attendees and the backend helper).

After deploying: planner must click "Refresh FR.225" to clear the stale
DocumentSignatureField cache and regenerate with short markers — then
client opens the viewer and the boxes are pen (clickable) not clock.
```
