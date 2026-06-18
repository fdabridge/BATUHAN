# Hotfix Push — filler.py generator bug (Portal 78 regression)

## What was fixed (already edited on disk)

**`backend/audit_set/filler.py`** — one block corrected:

The Portal 78 site-variable injection used:
```python
**{k: v for k, v in (
    { f"site_{i}_name": ..., ... }
    for i, s in enumerate(...)
).items()}
```
This calls `.items()` on a **generator** (the `(... for ...)` expression), not on a dict.
Generators don't have `.items()`, so `'generator' object has no attribute 'items'` crashed
every "Download audit package" call — even for audit sets with no additional sites.

Fixed to a proper nested dict comprehension:
```python
**{
    k: v
    for i, s in enumerate((audit_set.sites or [])[:5], start=1)
    for k, v in {
        f"site_{i}_name":      s.get("name", f"Site {i}"),
        f"site_{i}_address":   s.get("address", ""),
        f"site_{i}_employees": s.get("employee_count", "") or "",
        f"site_{i}_process":   s.get("process", ""),
    }.items()
}
```

## Your task

Commit and push only this file:

```bash
git add backend/audit_set/filler.py
git commit -m "hotfix: fix generator .items() crash in filler.py portal-78 site injection"
git push
```

No other files changed. No migrations needed.

## Verification after deploy

Open any audit set (including surveillance ones with no additional sites) and click
"Download audit package". It should succeed without the 'generator' object error.
