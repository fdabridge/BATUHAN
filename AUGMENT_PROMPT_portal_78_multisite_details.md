# Portal 78 — Multi-Site: Collect Per-Site Details Throughout the System

## Problem

When a client checks "We have additional sites / branches" in the application form and enters a count (e.g., 2), the backend creates placeholder site entries with `employee_count: 0` and empty address. The audit-time engine skips any site whose `employee_count <= 0`, so **all multi-site audit duration additions are silently zero** — making every multi-site calculation wrong.

Per IAF MD 1:2023, each additional site requires: name/label, address, headcount, and scope/activities. These fields must flow from application → audit set DB → FR.223 plan document.

## Files to read before starting

```
backend/audit_set/apply_router.py         # ApplicationPayload model + handler
frontend/src/app/apply/page.tsx           # Client application form
frontend/src/app/(app)/clients/[id]/page.tsx  # CB portal audit set view
backend/audit_set/service.py              # AuditSet update + sites extractor
backend/audit_set/db_models.py            # AuditSet.sites = Column(JSON)
backend/calculator/models.py              # SiteInfo model
backend/calculator/engine.py              # _add_site_time() uses employee_count
backend/audit_set/resolver.py            # Template field resolver
```

## Change 1 — `apply/page.tsx`: Replace count field with per-site detail form

**Current state:**
```tsx
{form.has_additional_sites && (
  <Field label="Number of additional sites">
    <input type="number" ... value={form.additional_site_count} />
  </Field>
)}
```

**Replace with:** A dynamic form that renders one entry per site, with an "Add site" button.

### Form state changes

Remove `additional_site_count: string` from the form state type and initial values.

Add:
```typescript
site_details: Array<{name: string; address: string; employee_count: string; process: string}>
```
Initial value: `site_details: []`

### UI

When `has_additional_sites` is checked, render:

```tsx
{form.has_additional_sites && (
  <div className="space-y-4">
    {form.site_details.map((site, i) => (
      <div key={i} className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700">Site {i + 1}</span>
          <button type="button" onClick={() => removeSite(i)}
            className="text-xs text-red-500 hover:text-red-700">Remove</button>
        </div>
        <Field label="Site name / label">
          <input className={inputCls} placeholder="e.g. Branch in İstanbul"
            value={site.name}
            onChange={e => patchSite(i, { name: e.target.value })} />
        </Field>
        <Field label="Address">
          <input className={inputCls} placeholder="Street, City, Country"
            value={site.address}
            onChange={e => patchSite(i, { address: e.target.value })} />
        </Field>
        <Field label="Employees at this site">
          <input className={inputCls} type="number" min="0" placeholder="0"
            value={site.employee_count}
            onChange={e => patchSite(i, { employee_count: e.target.value })} />
        </Field>
        <Field label="Main activities at this site">
          <input className={inputCls} placeholder="e.g. Warehousing and distribution"
            value={site.process}
            onChange={e => patchSite(i, { process: e.target.value })} />
        </Field>
      </div>
    ))}
    <button type="button"
      onClick={() => sel({ site_details: [...form.site_details, { name: '', address: '', employee_count: '', process: '' }] })}
      className="text-sm text-[#1A4731] hover:underline">
      + Add another site
    </button>
  </div>
)}
```

Add helpers (inside the component, not top-level):
```typescript
function patchSite(i: number, patch: Partial<typeof form.site_details[0]>) {
  const updated = form.site_details.map((s, idx) => idx === i ? { ...s, ...patch } : s)
  sel({ site_details: updated })
}
function removeSite(i: number) {
  sel({ site_details: form.site_details.filter((_, idx) => idx !== i) })
}
```

### Submit payload changes

In the `buildPayload` / `handleSubmit` function, replace:
```typescript
has_additional_sites: form.has_additional_sites,
additional_site_count: pInt(form.additional_site_count),
```
With:
```typescript
has_additional_sites: form.has_additional_sites && form.site_details.length > 0,
additional_site_count: form.site_details.length,
site_details: form.site_details.map(s => ({
  name: s.name.trim(),
  address: s.address.trim(),
  employee_count: pInt(s.employee_count),
  process: s.process.trim(),
})),
```

---

## Change 2 — `apply_router.py`: Accept site_details in payload

### Add a new model (above `ApplicationPayload`):

```python
class SiteDetailInput(BaseModel):
    name: str = ""
    address: str = ""
    employee_count: int = 0
    process: str = ""
```

### In `ApplicationPayload`, add:

```python
site_details: list[SiteDetailInput] = []
```

### In the handler, replace the sites-building block:

Find the current block:
```python
sites = []
if payload.has_additional_sites and payload.additional_site_count > 0:
    for _ in range(payload.additional_site_count):
        sites.append({"address": "", "process": "", "employee_count": 0})
```

Replace with:
```python
sites: list[dict] = []
if payload.site_details:
    sites = [
        {
            "name":           s.name,
            "address":        s.address,
            "employee_count": s.employee_count,
            "process":        s.process,
        }
        for s in payload.site_details
    ]
elif payload.has_additional_sites and payload.additional_site_count > 0:
    # Legacy fallback (old clients without site_details)
    sites = [
        {"name": f"Site {i+1}", "address": "", "employee_count": 0, "process": ""}
        for i in range(payload.additional_site_count)
    ]
```

---

## Change 3 — `calculator/models.py`: Add name field to SiteInfo

```python
class SiteInfo(BaseModel):
    """A single additional site on the application form."""
    name: str = ""           # ADD THIS
    address: str
    process_description: str = ""
    employee_count: int = 0
```

---

## Change 4 — `service.py`: Pass name through in site extractor

Find the sites extractor block (around line 439–448):
```python
sites = [
    SiteInfo(
        address=s.get("address", ""),
        process_description=s.get("process", ""),
        employee_count=s.get("employee_count", 0),
    )
    for s in sites_raw
    if s.get("employee_count", 0) > 0
]
```

Replace with:
```python
sites = [
    SiteInfo(
        name=s.get("name", ""),
        address=s.get("address", ""),
        process_description=s.get("process", ""),
        employee_count=s.get("employee_count", 0),
    )
    for s in sites_raw
    if s.get("employee_count", 0) > 0
]
```

Also remove the `employee_count > 0` filter — allow sites with 0 employees through so CB can see them (calculation already skips them via the engine's own check). Change to:
```python
sites = [
    SiteInfo(
        name=s.get("name", ""),
        address=s.get("address", ""),
        process_description=s.get("process", ""),
        employee_count=s.get("employee_count", 0),
    )
    for s in sites_raw
]
```

---

## Change 5 — CB Portal `clients/[id]/page.tsx`: Show and edit sites

### Where to add it

In the Audit Set detail view (the panel that shows Personnel, Integration Level, etc.), add a **"Additional Sites"** section that appears when `audit_set.sites` is non-empty OR `additional_site_count > 0`.

Find where the personnel card / calculation section is rendered and insert after it.

### Read-only display (planning phase and beyond)

```tsx
{((auditSet.sites ?? []).length > 0) && (
  <section>
    <h3 className="text-sm font-semibold text-gray-700 mb-2">
      Additional Sites ({auditSet.sites!.length})
    </h3>
    <div className="space-y-2">
      {auditSet.sites!.map((site: AuditSite, i: number) => (
        <div key={i} className="rounded border border-gray-100 bg-gray-50 px-3 py-2 text-xs space-y-0.5">
          <div className="font-medium text-gray-800">{site.name || `Site ${i + 1}`}</div>
          <div className="text-gray-500">{site.address || '— no address —'}</div>
          <div className="text-gray-500">
            {site.employee_count > 0 ? `${site.employee_count} employees` : 'employee count not set'}
            {site.process ? ` · ${site.process}` : ''}
          </div>
        </div>
      ))}
    </div>
    {/* Warn if any site has no employee count — this breaks the duration calculation */}
    {auditSet.sites!.some((s: AuditSite) => !s.employee_count) && (
      <p className="mt-2 text-xs text-amber-600">
        ⚠ One or more sites is missing an employee count — audit duration may be understated.
        Edit below to fix.
      </p>
    )}
  </section>
)}
```

### Editable inline form (admin / planner roles only)

Below the read-only section, for `role === 'admin' || role === 'planner'`, add an **"Edit sites"** button that expands an inline edit form:

The edit form renders one card per site (same layout as the apply form) with:
- Site name
- Address
- Employee count
- Activities

On save, PATCH `PUT /audit-sets/{id}` with the updated `sites` array.

Add to `AuditSet` TypeScript type (if not already there):
```typescript
type AuditSite = {
  name?: string
  address?: string
  employee_count?: number
  process?: string
}
```

---

## Change 6 — `resolver.py`: Expose site fields as template variables

In the resolver (the function that builds the Jinja2 / field context for document generation), add site-related template variables so FR.223/FR.224 can render them.

Add the following to the context dict that is returned:

```python
sites_raw = audit_set.sites or []

# Total additional site count
ctx["additional_sites_count"] = len(sites_raw)

# Per-site fields for up to 5 sites (FR.223 template can show a table)
for i, s in enumerate(sites_raw[:5], start=1):
    ctx[f"site_{i}_name"]        = s.get("name", f"Site {i}")
    ctx[f"site_{i}_address"]     = s.get("address", "")
    ctx[f"site_{i}_employees"]   = s.get("employee_count", 0) or ""
    ctx[f"site_{i}_process"]     = s.get("process", "")

# Blank out unused slots
for i in range(len(sites_raw) + 1, 6):
    ctx[f"site_{i}_name"]      = ""
    ctx[f"site_{i}_address"]   = ""
    ctx[f"site_{i}_employees"] = ""
    ctx[f"site_{i}_process"]   = ""

# Human-readable summary for embedding anywhere
if sites_raw:
    lines = []
    for i, s in enumerate(sites_raw, start=1):
        parts = [s.get("name") or f"Site {i}"]
        if s.get("address"): parts.append(s["address"])
        if s.get("employee_count"): parts.append(f"{s['employee_count']} emp.")
        if s.get("process"): parts.append(s["process"])
        lines.append(" — ".join(parts))
    ctx["additional_sites_summary"] = "\n".join(lines)
else:
    ctx["additional_sites_summary"] = "None"
```

---

## Verification checklist

1. Open the client application form (`/apply`) — check "We have additional sites", confirm the per-site detail form appears with name/address/employees/activities fields
2. Submit — confirm the `sites` JSON in the DB has real addresses and employee counts (not empty)
3. In the CB portal (`/clients/{id}`), open the audit set — confirm the Additional Sites section shows the submitted site details with the warning if employee count is missing
4. Re-run the audit duration calculation — confirm "Combined base (incl. sites)" is now higher than before for multi-site organizations (previously was identical to single-site)
5. Generate FR.223 — confirm site details appear in the document

## No DB migration needed

`AuditSet.sites` is already a `Column(JSON)` — the schema accepts any JSON dict. Adding `name` to the stored dicts is backward-compatible.
