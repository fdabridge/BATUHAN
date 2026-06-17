# Push: EA Code System Fix (IAF EA 1–39 Correct Mapping)

## What was changed (already edited on disk — do NOT rewrite these files)

Three files were edited directly in the working directory:

1. **`backend/audit_set/service.py`**
   - `_SCOPE_TO_EA_KW` dict completely rewritten with correct IAF EA codes 1–39 per TÜRKAK R40.01
   - All 39 keys now use the correct sector numbers (e.g. EA 29 = wholesale/retail, EA 17 = basic metals)
   - Previously the entire dict used wrong numbers (e.g. wholesale/retail was wrongly keyed as "EA 17")
   - A bad interim fix (wrong keywords stuffed into "EA 17") has been reverted and corrected

2. **`frontend/src/app/(app)/auditors/[id]/page.tsx`**
   - Eligibility checker placeholder fixed: `"e.g. 17, 29"` → `"e.g. EA 17, EA 29"`
   - Matches the actual stored format for EA codes in the database

3. **`REFERENCE_ISO_IAF_Standards_Knowledge.md`**
   - Section 1 updated with NACE Rev.2 sub-codes for all 39 EA codes
   - "Common traps" section added (EA 17 ≠ wholesale, EA 29 ≠ engineering, etc.)
   - Last updated date and sources updated

## Your task

Just commit and push these three files to Railway. No code changes needed.

```bash
cd /path/to/repo

git add backend/audit_set/service.py
git add frontend/src/app/(app)/auditors/[id]/page.tsx
git add REFERENCE_ISO_IAF_Standards_Knowledge.md

git commit -m "fix: correct IAF EA code mapping in _SCOPE_TO_EA_KW (EA 1-39 per TÜRKAK R40.01)

- Rewrite entire _SCOPE_TO_EA_KW dict with correct IAF sector numbers
- EA 29 = wholesale/retail/trade/medical device sales (was wrongly EA 17)
- EA 17 = basic metals/fabricated metal products (was wrongly wholesale)
- EA 12 = chemicals, EA 13 = pharma, EA 28 = construction, etc.
- All 39 codes now keyed correctly per TÜRKAK R40.01 / IAF MD 1
- Fix eligibility checker placeholder to show 'EA X' format
- Update reference doc with NACE sub-codes and common traps"

git push
```

After pushing, Railway will redeploy automatically. No migrations needed — this is pure logic/keyword change in Python, no DB schema changes.

## Verification after deploy

Open any audit set that has scope text containing "sales", "wholesale", "medical devices", or "marketing" and click "Derive Scope" (or save the audit set). The derived EA code should now show **EA 29** instead of a wrong code or "no codes derived".
