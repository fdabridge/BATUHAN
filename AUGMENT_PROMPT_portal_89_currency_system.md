# Portal 89 — Currency selection (USD / EUR / TRY) across the system

## Requirement

The Planner can select USD, EUR, or TRY for any audit set. The selection is stored and reflected in all generated documents (quotation FR.220, contract FR.221, and any other document that renders a fee amount). Only the Planner (and admin) can change the currency and pricing.

---

## Root cause of current limitation

`_fmt_fee()` in `filler.py` hardcodes the USD dollar sign:

```python
def _fmt_fee(val) -> str:
    """Format a fee as '$X,XXX' or '' if unset."""
    if val is None or val == "":
        return ""
    try:
        return f"${float(val):,.0f}"   # ← hardcoded '$'
    except (TypeError, ValueError):
        return str(val)
```

There is no `currency` field on `AuditSet` (DB model, schemas, or frontend types).

---

## Changes required

### 1. `backend/audit_set/db_models.py` — add `currency` column

**In `create_tables()`**, add the safe migration line after the surveillance_fee lines:

```python
_safe_add_column("audit_sets", "currency VARCHAR DEFAULT 'USD'")
```

**In the `AuditSet` class**, after the `surveillance_fee` column:

```python
certification_fee  = Column(Float, nullable=True)
surveillance_fee   = Column(Float, nullable=True)
currency           = Column(String, nullable=True, default="USD")  # "USD" | "EUR" | "TRY"
```

---

### 2. `backend/audit_set/schemas.py` — add `currency` to update and response schemas

In `AuditSetCreate` (if present), `AuditSetUpdate`, and `AuditSetResponse`, add:

```python
currency: Optional[str] = None    # "USD" | "EUR" | "TRY"
```

For `AuditSetResponse`, the default should be `"USD"` (not `None`) to preserve backward compatibility with sets that have no stored currency:

```python
currency: str = "USD"
```

---

### 3. `backend/audit_set/service.py` — persist currency on update

In the `update_audit_set` function, after the `surveillance_fee` update block (lines ~860–863):

```python
    if data.surveillance_fee is not None:
        audit_set.surveillance_fee = data.surveillance_fee
```

Add:
```python
    if data.currency is not None:
        if data.currency not in ("USD", "EUR", "TRY"):
            raise HTTPException(400, "currency must be one of: USD, EUR, TRY")
        audit_set.currency = data.currency
```

If the function imports are not already set, add `from fastapi import HTTPException` at the top.

Also update the AuditSet creation in `create_audit_set` to pass `currency` from the creation schema if provided (default: "USD"):

```python
audit_set = AuditSet(
    ...
    certification_fee=data.certification_fee,
    surveillance_fee=data.surveillance_fee,
    currency=data.currency or "USD",
    ...
)
```

---

### 4. `backend/audit_set/filler.py` — currency-aware `_fmt_fee`

**Add the symbol map** at the top of the file, near the other module-level constants (after the imports, before `_fmt_fee`):

```python
_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "TRY": "₺",
}
```

**Replace `_fmt_fee`** (current lines 132–139):

Current:
```python
def _fmt_fee(val) -> str:
    """Format a fee as '$X,XXX' or '' if unset."""
    if val is None or val == "":
        return ""
    try:
        return f"${float(val):,.0f}"
    except (TypeError, ValueError):
        return str(val)
```

Replace with:
```python
def _fmt_fee(val, currency: str = "USD") -> str:
    """Format a fee value with the correct currency symbol.

    Formats as '<symbol>X,XXX' (no decimal places — fees are always whole units).
    Falls back to '$' if an unrecognised currency code is passed.
    Returns '' when val is None or empty.
    """
    if val is None or val == "":
        return ""
    try:
        symbol = _CURRENCY_SYMBOLS.get(currency or "USD", "$")
        return f"{symbol}{float(val):,.0f}"
    except (TypeError, ValueError):
        return str(val)
```

**Update `build_base_context`** to read the currency from the audit set and pass it through:

Find the fee lines in `build_base_context` (around line 362–364):
```python
        "certification_fee": _fmt_fee(audit_set.certification_fee),
        "initial_fee":       _fmt_fee(audit_set.certification_fee),
        "surveillance_fee":  _fmt_fee(audit_set.surveillance_fee),
```

Replace with:
```python
        _currency = (audit_set.currency or "USD"),
        "certification_fee": _fmt_fee(audit_set.certification_fee, _currency),
        "initial_fee":       _fmt_fee(audit_set.certification_fee, _currency),
        "surveillance_fee":  _fmt_fee(audit_set.surveillance_fee, _currency),
        "currency":          _currency,
        "currency_symbol":   _CURRENCY_SYMBOLS.get(_currency, "$"),
        "currency_code":     _currency,
```

> **Note:** The three new keys `currency`, `currency_symbol`, and `currency_code` are additive — templates can use whichever form they need. Existing templates that only use `certification_fee` / `surveillance_fee` tags are unaffected since those are now formatted strings (same as before, just with the correct symbol).

**Important — Python tuple bug fix**: `_currency = (audit_set.currency or "USD"),` creates a tuple if the trailing comma is there accidentally. Write it correctly as a plain assignment on its own line:

```python
        _currency = audit_set.currency or "USD"
        "certification_fee": _fmt_fee(audit_set.certification_fee, _currency),
        "initial_fee":       _fmt_fee(audit_set.certification_fee, _currency),
        "surveillance_fee":  _fmt_fee(audit_set.surveillance_fee, _currency),
        "currency":          _currency,
        "currency_symbol":   _CURRENCY_SYMBOLS.get(_currency, "$"),
        "currency_code":     _currency,
```

In the dict literal, `_currency` is assigned as a variable BEFORE the dict construction — either extract it before the `return {` line, or add it as a local variable at the top of the function body.

Correct form:
```python
def build_base_context(audit_set, stage, ...):
    ...
    _currency = audit_set.currency or "USD"
    ...
    return {
        ...
        "certification_fee": _fmt_fee(audit_set.certification_fee, _currency),
        "initial_fee":       _fmt_fee(audit_set.certification_fee, _currency),
        "surveillance_fee":  _fmt_fee(audit_set.surveillance_fee, _currency),
        "currency":          _currency,
        "currency_symbol":   _CURRENCY_SYMBOLS.get(_currency, "$"),
        "currency_code":     _currency,
        ...
    }
```

---

### 5. `frontend/src/types/index.ts` — add `currency` to `AuditSetResponse`

After `surveillance_fee`:

```typescript
  certification_fee: number | null
  surveillance_fee: number | null
  currency?: string | null          // "USD" | "EUR" | "TRY" — null for legacy sets
```

---

### 6. `frontend/src/app/(app)/clients/[id]/page.tsx` — currency selector in Fees section

#### 6a. Add `userRole` prop to `PlanOverview`

The `PlanOverview` function signature currently:
```typescript
function PlanOverview({
  data,
  auditSetId,
  onInvalidate,
}: {
  data: AuditSetResponse
  auditSetId: string
  onInvalidate: () => void
})
```

Add `userRole`:
```typescript
function PlanOverview({
  data,
  auditSetId,
  onInvalidate,
  userRole = '',
}: {
  data: AuditSetResponse
  auditSetId: string
  onInvalidate: () => void
  userRole?: string
})
```

#### 6b. Add `currency` state inside `PlanOverview`

After the `survFee` state line:
```typescript
const [currency, setCurrency] = useState(data.currency ?? 'USD')
```

#### 6c. Include `currency` in the `saveFees` mutation

Current `mutationFn`:
```typescript
mutationFn: () =>
  api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, {
    certification_fee: certFee.trim() === '' ? null : parseFloat(certFee),
    surveillance_fee:  survFee.trim() === '' ? null : parseFloat(survFee),
  }),
```

Replace with:
```typescript
mutationFn: () =>
  api.put<AuditSetResponse>(`/audit-sets/${auditSetId}/planning`, {
    certification_fee: certFee.trim() === '' ? null : parseFloat(certFee),
    surveillance_fee:  survFee.trim() === '' ? null : parseFloat(survFee),
    currency,
  }),
```

#### 6d. Add currency selector to the Fees UI block

The existing fees section (around line 771–791) — add a currency dropdown. It is only editable by `planner` or `admin` roles; all other CB roles see it read-only.

After the Surveillance Fee input, before the "Save fees" button, insert:
```tsx
<div className="w-28">
  <label className={lblCls}>Currency</label>
  {(userRole === 'planner' || userRole === 'admin') ? (
    <select
      className={inputCls}
      value={currency}
      onChange={(e) => setCurrency(e.target.value)}
    >
      <option value="USD">USD ($)</option>
      <option value="EUR">EUR (€)</option>
      <option value="TRY">TRY (₺)</option>
    </select>
  ) : (
    <div className={inputCls + ' bg-gray-50 text-gray-500 cursor-not-allowed'}>
      {currency}
    </div>
  )}
</div>
```

#### 6e. Pass `userRole` to `PlanOverview` in the page JSX

Current call at line ~2222:
```tsx
<PlanOverview data={data} auditSetId={id} onInvalidate={invalidate} />
```

Replace with:
```tsx
<PlanOverview data={data} auditSetId={id} onInvalidate={invalidate} userRole={currentUser?.role ?? ''} />
```

---

## What does NOT change

- Document templates (`.docx` files) — they already render `{{ certification_fee }}` and `{{ surveillance_fee }}` as formatted strings. The symbol is now embedded in the formatted value (e.g., `₺1,000` instead of `$1,000`). No template edits needed.
- The audit set creation flow via the portal application form — surveillance/initial sets will default to `"USD"` if not specified.
- Any auditor-facing or client-facing views — currency is a CB/Planner setting that affects document generation only.
- The `surveillance_fee` and `certification_fee` DB columns — still Float, unchanged.

---

## Backward compatibility

- Existing audit sets have `currency = NULL` in DB (the column DEFAULT 'USD' applies to new rows only). `_fmt_fee` defaults currency to `"USD"` when the value is None, so all existing sets continue to show `$` amounts unchanged.
- The `AuditSetResponse.currency` field defaults to `"USD"` in the schema, so the frontend initializes correctly for legacy sets.

---

## Verification checklist (post-deploy)

1. Open an existing audit set. Confirm the Fees section now shows a "Currency" dropdown visible only to Planner/admin role.
2. Change currency to TRY, click "Save fees". Reload and confirm `₺` appears in generated documents (FR.220 quotation, FR.221 agreement).
3. Change to EUR, regenerate — confirm `€` symbol.
4. Log in as `officer` or `certification_manager` — confirm they see the currency label as read-only text, not an editable dropdown.
5. Confirm existing audit sets (with `currency = NULL` in DB) still render `$` correctly.

---

## Commit message suggestion

```
Portal 89: currency selection (USD / EUR / TRY) stored per audit set

- db_models: add currency VARCHAR column with DEFAULT 'USD'; safe migration
- schemas: currency Optional[str] on Update; str default 'USD' on Response
- service: validate and persist currency on update; default 'USD' on create
- filler: _CURRENCY_SYMBOLS map; _fmt_fee now currency-aware; build_base_context
  emits currency, currency_symbol, currency_code keys alongside fee strings
- types/index.ts: currency field on AuditSetResponse
- page.tsx: PlanOverview receives userRole; currency state + dropdown in Fees
  section (editable planner/admin only); currency included in saveFees payload
```
