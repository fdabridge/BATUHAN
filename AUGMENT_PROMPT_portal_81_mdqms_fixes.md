# Portal 81 — MDQMS / ISO 13485 Fixes

## Root-cause summary

ISO 13485 audits suffer from two bugs:

1. **Committee picker shows no auditors** — `_compute_covered_scope` in `auditors.py` bails out with `continue` when `required_codes == []`. For MDQMS with Turkish scope text, `_MEDICAL_TA_KW` has only English keywords, so `derive_required_scope` always returns `codes: []`. Every MDQMS auditor gets `covered_scope: {}`. The frontend committee picker then hides them with:
   ```javascript
   const eligiblePool = pool.filter(
     (a) => Object.values(a.covered_scope ?? {}).flat().length > 0
   )
   ```
   Result: zero auditors visible in the committee picker for any ISO 13485 audit set.

2. **FR.232-1 missing from MDQMS surveillance** — `uaf_blank_set/13485/Gözetim/` does not contain `FR.232-1`. The resolver calls `_add(..., "FR.232-1", "mdqms", ...)` for surveillance but finds nothing → goes to MISSING_TEMPLATES. The file exists only in `13485/İlk Belgelendirme/Aşama 2/` and was never copied to the surveillance folder.

---

## Fix 1 — `backend/api/routes/auditors.py`: `_compute_covered_scope` complete rewrite

Locate the inner function `_compute_covered_scope` (currently around line 577). Replace **the entire function body** with the version below. Three changes from current code:

- Move the `qual` lookup to the top of the loop, before the `required_codes` check.
- When `required_codes == []` but the auditor IS qualified for the standard, emit `covered[iso_std] = ["UNSCOPED"]` instead of `continue`. This non-empty sentinel makes the auditor visible in the committee picker.
- Change `if scope_type == "ea" and not auditor_codes:` → `if not auditor_codes:` so that medical / food / sector / energy auditors with no recorded `scope_category` also get all required codes credited (rather than `[]`).

```python
def _compute_covered_scope(auditor_qualifications: list, req: dict) -> dict:
    """
    For each required standard/codes, determine which codes this auditor covers.
    Returns {iso_standard: [covered_codes]}.
    'UNSCOPED' is a sentinel meaning "qualified for this standard, no sub-code restriction".
    """
    covered: dict = {}
    for iso_std, entry in req.items():
        scope_type = entry.get("type", "ea")
        required_codes: list[str] = entry.get("codes", [])

        std_lower = iso_std.lower().replace("iso ", "").replace(" ", "")
        qual = next(
            (q for q in auditor_qualifications
             if q.is_qualified is not False and std_lower in
             (q.standard_code or "").lower().replace("iso ", "").replace(" ", "")),
            None,
        )
        if not qual:
            continue

        # No specific sub-codes required (e.g. Turkish scope text, no keyword match).
        # Auditor is qualified → mark as unscoped so the committee picker can see them.
        if not required_codes:
            covered[iso_std] = ["UNSCOPED"]
            continue

        auditor_codes: list[str] = []
        if scope_type in ("food", "medical", "sector", "energy"):
            # scope_category is a comma-separated string like "A1.1, A1.3"
            raw = qual.scope_category or ""
            auditor_codes = [c.strip() for c in raw.split(",") if c.strip()]
        elif scope_type == "ea":
            auditor_codes = qual.ea_codes or []

        # If auditor has no recorded codes (any scope type), they cover all required codes.
        if not auditor_codes:
            covered[iso_std] = required_codes
            continue

        # Intersection of required codes and auditor's codes
        matched = [c for c in required_codes if c in auditor_codes]
        if matched:
            covered[iso_std] = matched

    return covered
```

---

## Fix 2 — `uaf_blank_set/13485/Gözetim/`: copy missing FR.232-1

Run this shell command in the repo root (or do the equivalent file copy):

```bash
cp "uaf_blank_set/13485/İlk Belgelendirme/Aşama 2/FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx" \
   "uaf_blank_set/13485/Gözetim/FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx"
```

After this, `_build_surveillance` for MDQMS will resolve FR.232-1 correctly.

---

## Fix 3 (recommended) — `backend/audit_set/service.py`: add Turkish keywords to `_MEDICAL_TA_KW`

Currently all keywords in `_MEDICAL_TA_KW` are English-only. Turkish scope text produces `codes = []`, which is why Fix 1 is needed at all. Adding Turkish terms means real scope codes will be derived when possible, giving proper per-code coverage display in the committee picker (rather than the generic `UNSCOPED` sentinel).

Locate `_MEDICAL_TA_KW` (around line 71). Extend each tuple with Turkish equivalents:

```python
_MEDICAL_TA_KW: dict[str, tuple[str, ...]] = {
    "A1.1": (
        "bandage", "wound care", "catheter", "surgical instrument", "syringe",
        # Turkish
        "yara örtüsü", "pansuman", "kateter", "cerrahi alet", "şırınga", "enjektör",
        "tek kullanımlık", "disposable",
    ),
    "A1.2": (
        "hip replacement", "dental implant", "non-active implant", "orthopaedic",
        # Turkish
        "kalça protezi", "diş implantı", "kemik çivisi", "ortopedik implant",
        "pasif implant", "aktif olmayan implant",
    ),
    "A1.3": (
        "imaging equipment", "monitoring equipment", "ventilator",
        # Turkish
        "görüntüleme cihazı", "hasta monitörü", "solunum cihazı", "ventilatör",
        "ultrason cihazı", "mri", "tomografi", "endoskop",
    ),
    "A1.4": (
        "pacemaker", "active implant", "defibrillator",
        # Turkish
        "kalp pili", "defibrilatör", "aktif implant", "koklear implant",
    ),
    "A1.5": (
        "sterilization", "sterilisation", "ethylene oxide", "gamma steriliz",
        # Turkish
        "sterilizasyon", "etilen oksit", "gama sterilizasyon", "steril",
        "dezenfeksiyon hizmeti",
    ),
    "A1.6": (
        "software as medical device", "samd", "medical software", "ai medical",
        # Turkish
        "tıbbi yazılım", "tıbbi yapay zeka", "klinik karar destek",
        "sağlık bilgi sistemi", "hastane yönetim sistemi",
    ),
    "A1.7": (
        "medical device component", "medical parts supplier",
        # Turkish
        "tıbbi cihaz bileşeni", "tıbbi parça", "medikal komponent",
        "tıbbi malzeme tedarikçisi",
    ),
    "A2.1": (
        "in-vitro diagnostic", "ivd reagent",
        # Turkish
        "in vitro tanı", "ivd", "teşhis reaktifi", "laboratuvar kiti",
        "biyokimya kiti", "immünoloji kiti",
    ),
    "A2.2": (
        "ivd self-test", "self-testing diagnostic",
        # Turkish
        "kendi kendine test", "hızlı test", "ev tipi test",
        "antijen testi", "hamilelik testi", "glikoz ölçüm",
    ),
    "A2.3": (
        "ivd professional", "professional diagnostic",
        # Turkish
        "profesyonel tanı", "laboratuvar cihazı", "analizör",
        "kan sayım cihazı", "koagülasyon",
    ),
    "A2.4": (
        "companion diagnostic",
        # Turkish
        "eşlik eden tanı", "biyobelirteç testi", "hedefe yönelik tedavi testi",
    ),
}
```

---

## What each fix unblocks

| Fix | Before | After |
|-----|--------|-------|
| Fix 1 (`_compute_covered_scope`) | All MDQMS auditors hidden from committee picker (`covered_scope = {}`) | Auditors visible; show "UNSCOPED" badge when no TA codes derived, or matched codes when they are |
| Fix 2 (FR.232-1 copy) | Surveillance package for ISO 13485 missing the MDQMS audit report template | FR.232-1 resolves correctly; document package complete |
| Fix 3 (Turkish keywords) | `_MEDICAL_TA_KW` only matches English scope text | Turkish scope text derives actual A1.x/A2.x codes; committee coverage display shows real codes instead of "UNSCOPED" |

## Commit message suggestion

```
Portal 81: fix MDQMS committee picker + add FR.232-1 to surveillance

- auditors.py _compute_covered_scope: move qual lookup before required_codes
  check; emit ["UNSCOPED"] when codes=[] but auditor is qualified; broaden
  `if not auditor_codes` to all scope types (was ea-only)
- copy FR.232-1 to uaf_blank_set/13485/Gözetim/ (was only in Aşama 2)
- service.py _MEDICAL_TA_KW: add Turkish keyword variants for all 12 codes
```
