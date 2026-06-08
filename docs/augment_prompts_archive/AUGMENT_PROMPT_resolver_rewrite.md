# Resolver Rewrite — Route Templates to the Right Folder

The document template resolver (`backend/audit_set/resolver.py`) is fundamentally broken. It uses a single hardcoded path, wrong folder names, and broken routing logic that causes every UAF package download to contain only `MISSING_TEMPLATES.txt`. Fix it completely.

---

## WHAT IS ON DISK — VERIFIED GROUND TRUTH

There are two separate template roots:

```
uaf_blank_set/
  9-14-45-22-5001/
    İlk Belgelendirme/Aşama 1/   ← Stage 1
    İlk Belgelendirme/Aşama 2/   ← Stage 2 AND Recertification
    Gözetim/                      ← Surveillance
  13485/
    İlk Belgelendirme/Aşama 1/
    İlk Belgelendirme/Aşama 2/
    Gözetim/
  27001/
    İlk Belgelendirme/Aşama 1/
    İlk Belgelendirme/Aşama 2/
    Gözetim/

turkak_blank_set/
  english/
    9-14-45-22-5001/
      Stage 1/
      Stage 2/   ← also used for Recertification
      Surv/
    27001/
      Stage 1/
      Stage 2/
      Surv/
  turkish/
    9-14-45-22-5001/
      Aşama 1/
      Aşama 2/   ← also used for Recertification
      GD/
    27001/
      Aşama 1/
      Aşama 2/
      GD/
```

**Critical facts:**
- TÜRKAK has NO `13485/` folder anywhere — MDQMS is UAF-only
- Recertification uses the Stage 2 folder — there is no separate Recertification folder in any root
- UAF uses Turkish folder names on disk even though the documents inside are in English
- UAF standard group folder is `9-14-45-22-5001` (not `9-14-45`)
- ISO 27001 uses `FR.229` as the audit report (not `FR.232`) in Stage 2 and Surveillance — across ALL roots
- `FR.217` is excluded from all document sets (application forms are being digitalized separately)

---

## PART 1 — Add `document_language` to the AuditSet model

TÜRKAK can generate either Turkish (default) or English documents. This choice is made at audit set creation and stored on the model.

### `backend/audit_set/db_models.py`

Find the `AuditSet` ORM class and add this column:

```python
document_language = Column(String, nullable=False, server_default="turkish")
# "turkish" | "english" — only used when accreditation_body is TÜRKAK/TURKAK
# UAF always generates English documents (but uses Turkish folder names on disk)
```

### `backend/audit_set/schemas.py`

Add `document_language` to `AuditSetCreate`, `AuditSetUpdate`, and `AuditSetResponse`:

```python
# In AuditSetCreate and AuditSetUpdate:
document_language: str = "turkish"   # "turkish" | "english"

# In AuditSetResponse:
document_language: str = "turkish"
```

### Alembic migration

Generate a migration to add the column:
```
alembic revision --autogenerate -m "add_document_language_to_audit_set"
alembic upgrade head
```

If Alembic is not set up, add the column with a manual `ALTER TABLE` in a new migration file following the existing pattern.

---

## PART 2 — Add two path settings

### `backend/config/settings.py`

Replace the single `blank_set_path` field with two separate fields:

```python
# Remove:
# blank_set_path: str = "/Users/batuhan/BATUHAN/uaf_blank_set"

# Add:
uaf_blank_set_path: str = "/Users/batuhan/BATUHAN/uaf_blank_set"
turkak_blank_set_path: str = "/Users/batuhan/BATUHAN/turkak_blank_set"
# On Railway: set UAF_BLANK_SET_PATH and TURKAK_BLANK_SET_PATH environment variables.
```

---

## PART 3 — Rewrite `backend/audit_set/resolver.py` completely

Replace the entire file with the implementation below. Read it carefully — every routing decision is documented.

```python
"""
Certiva — Audit Set: blank-template resolver.

Given an AuditSet, resolve which template folder to use, then discover all
FR.* DOCX files in that folder. Documents are discovered from disk — no
hardcoded FR lists — so adding a new template to a folder automatically
includes it in future packages.

FR.217 is always excluded (application forms are being digitalized).

Routing matrix
--------------
accreditation_body  | template root           | standard group     | stage subfolders
--------------------|-------------------------|--------------------|-------------------------------
UAF                 | uaf_blank_set/          | 9-14-45-22-5001    | İlk Belgelendirme/Aşama 1
                    |                         | 13485              | İlk Belgelendirme/Aşama 2
                    |                         | 27001              | Gözetim
                    |                         |                    | (Recert → Aşama 2)
TÜRKAK english      | turkak_blank_set/english| 9-14-45-22-5001    | Stage 1 / Stage 2 / Surv
                    |                         | 27001              | (Recert → Stage 2)
                    |                         | (no 13485)         |
TÜRKAK turkish      | turkak_blank_set/turkish| 9-14-45-22-5001    | Aşama 1 / Aşama 2 / GD
                    |                         | 27001              | (Recert → Aşama 2)
                    |                         | (no 13485)         |
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from audit_set.field_maps import (
    FR211_MAP, FR218_MAP, FR222_MAP, FR223_MAP,
    FR224_MAP, FR225_MAP, FR230_MAP, FR231_MAP, FR232_MAP, FR234_MAP,
)
from config.settings import get_settings

# ---------------------------------------------------------------------------
# Field map lookup — keyed by FR-number prefix (e.g. "FR.231-1" → FR231_MAP)
# FR.220, FR.221 have no auto-fill fields; use empty dict.
# FR.229 is the ISMS/PIMS audit report — same table structure as FR.232.
# ---------------------------------------------------------------------------
_FR_MAP: dict[str, dict] = {
    "FR.211":   FR211_MAP,
    "FR.218":   FR218_MAP,
    "FR.220":   {},
    "FR.221":   {},
    "FR.222":   FR222_MAP,
    "FR.223":   FR223_MAP,
    "FR.224":   FR224_MAP,
    "FR.225":   FR225_MAP,
    "FR.229":   FR232_MAP,   # ISMS audit report — same structure as FR.232
    "FR.230":   FR230_MAP,
    "FR.231":   FR231_MAP,
    "FR.231-1": FR231_MAP,
    "FR.232":   FR232_MAP,
    "FR.232-1": FR232_MAP,
    "FR.234":   FR234_MAP,
}

_FR_NUMBER_RE = re.compile(r'^(FR\.\d+(?:-\d+)?)', re.IGNORECASE)

# Standards that belong to each group folder
_BASE_STANDARDS  = {"QMS", "EMS", "OHSMS", "FSMS", "ABMS", "ENMS"}
_MDQMS_STANDARDS = {"MDQMS"}
_ISMS_STANDARDS  = {"ISMS"}


@dataclass
class DocumentSpec:
    fr_number:       str    # e.g. "FR.223", "FR.231-1"
    template_path:   Path
    field_map:       dict
    output_filename: str    # clean name for the ZIP entry


def _clean_filename(name: str) -> str:
    """Strip the revision suffix from a template filename."""
    cleaned = re.sub(r"\s*_?R\d+[^.]*\.docx$", ".docx", name, flags=re.IGNORECASE)
    return cleaned.strip()


def _extract_fr_number(filename: str) -> str | None:
    """Extract the FR-number prefix from a template filename, e.g. 'FR.231-1'."""
    m = _FR_NUMBER_RE.match(filename)
    return m.group(1).upper() if m else None


def _build_from_folder(folder: Path, missing: list[str]) -> list[DocumentSpec]:
    """
    Discover all FR.*.docx templates in `folder`, skip FR.217, and return
    a DocumentSpec for each one found.  If the folder itself is missing, log
    a warning and append to `missing`.
    """
    if not folder.exists():
        missing.append(str(folder))
        logger.warning("[Resolver] Folder not found: %s", folder)
        return []

    specs: list[DocumentSpec] = []
    for template in sorted(folder.glob("FR.*.docx")):
        fr_num = _extract_fr_number(template.name)
        if fr_num is None:
            logger.warning("[Resolver] Cannot extract FR number from: %s", template.name)
            continue
        if fr_num.upper().startswith("FR.217"):
            # Application forms are being digitalized — exclude from all packages
            continue
        field_map = _FR_MAP.get(fr_num, {})
        if field_map == {} and fr_num not in ("FR.220", "FR.221"):
            logger.warning("[Resolver] No field map registered for %s — using empty map", fr_num)
        specs.append(DocumentSpec(
            fr_number=fr_num,
            template_path=template,
            field_map=field_map,
            output_filename=_clean_filename(template.name),
        ))
    return specs


def _get_template_root(accreditation_body: str, document_language: str) -> Path:
    """Return the correct template root directory."""
    s = get_settings()
    ab = (accreditation_body or "").upper()
    if ab == "UAF":
        return Path(s.uaf_blank_set_path)
    # TÜRKAK / TURKAK
    lang = (document_language or "turkish").lower()
    sub = "english" if lang == "english" else "turkish"
    return Path(s.turkak_blank_set_path) / sub


def _get_standard_group(standards: list[str], accreditation_body: str, needs_base: bool, needs_mdqms: bool, needs_isms: bool) -> list[str]:
    """
    Return the list of standard group folder names to include.
    Each audit set can span multiple groups (e.g. ISO 9001 + ISO 13485 → base + mdqms).
    TÜRKAK has no 13485 folder — MDQMS is skipped with a warning.
    """
    ab = (accreditation_body or "").upper()
    groups = []
    if needs_base:
        groups.append("9-14-45-22-5001")
    if needs_mdqms:
        if ab != "UAF":
            logger.warning(
                "[Resolver] MDQMS (ISO 13485) requested for accreditation_body=%r — "
                "TÜRKAK has no 13485 template set. Skipping.", accreditation_body
            )
        else:
            groups.append("13485")
    if needs_isms:
        groups.append("27001")
    return groups


def _get_stage_subfolder(audit_type: str, stage_key: str, accreditation_body: str, document_language: str) -> str:
    """
    Return the subfolder name inside the standard-group folder.

    stage_key: "stage_1" | "stage_2" | "surveillance"
    Recertification uses the stage_2 subfolder — there is no separate recertification folder.
    """
    ab = (accreditation_body or "").upper()
    lang = (document_language or "turkish").lower()

    if ab == "UAF":
        # UAF disk always uses Turkish folder names regardless of document language
        mapping = {
            "stage_1":      "İlk Belgelendirme/Aşama 1",
            "stage_2":      "İlk Belgelendirme/Aşama 2",
            "surveillance": "Gözetim",
        }
    elif lang == "english":
        mapping = {
            "stage_1":      "Stage 1",
            "stage_2":      "Stage 2",
            "surveillance": "Surv",
        }
    else:  # turkish
        mapping = {
            "stage_1":      "Aşama 1",
            "stage_2":      "Aşama 2",
            "surveillance": "GD",
        }

    if stage_key == "surveillance":
        return mapping["surveillance"]

    # Recertification uses Stage 2 folder
    if (audit_type or "").lower() == "recertification" and stage_key == "stage_2":
        return mapping["stage_2"]

    return mapping[stage_key]


def resolve_document_set(audit_set) -> tuple[dict[str, list[DocumentSpec]], list[str]]:
    """
    Returns (document_set, missing) where:
    - document_set: keyed by output folder name in the ZIP
        "Stage_1"      → list[DocumentSpec]   (initial / recertification)
        "Stage_2"      → list[DocumentSpec]   (initial / recertification)
        "Surveillance" → list[DocumentSpec]   (any surveillance_* audit_type)
    - missing: list of folder paths that could not be found on disk

    Initial and Recertification produce Stage_1 + Stage_2.
    Surveillance (surveillance_1, surveillance_2, etc.) produces only Surveillance.
    """
    standards          = audit_set.standards or []
    audit_type         = (audit_set.audit_type or "").lower()
    accreditation_body = (getattr(audit_set, "accreditation_body", "") or "")
    document_language  = (getattr(audit_set, "document_language", "turkish") or "turkish")

    needs_base  = any(s in _BASE_STANDARDS  for s in standards)
    needs_mdqms = any(s in _MDQMS_STANDARDS for s in standards)
    needs_isms  = any(s in _ISMS_STANDARDS  for s in standards)

    template_root = _get_template_root(accreditation_body, document_language)
    groups        = _get_standard_group(standards, accreditation_body, needs_base, needs_mdqms, needs_isms)

    document_set: dict[str, list[DocumentSpec]] = {}
    missing:      list[str]                     = []

    if audit_type.startswith("surveillance"):
        surv_sub = _get_stage_subfolder(audit_type, "surveillance", accreditation_body, document_language)
        specs: list[DocumentSpec] = []
        for group in groups:
            folder = template_root / group / surv_sub
            specs.extend(_build_from_folder(folder, missing))
        document_set["Surveillance"] = specs

    else:  # initial or recertification
        sub1 = _get_stage_subfolder(audit_type, "stage_1", accreditation_body, document_language)
        sub2 = _get_stage_subfolder(audit_type, "stage_2", accreditation_body, document_language)

        s1_specs: list[DocumentSpec] = []
        s2_specs: list[DocumentSpec] = []
        for group in groups:
            s1_specs.extend(_build_from_folder(template_root / group / sub1, missing))
            s2_specs.extend(_build_from_folder(template_root / group / sub2, missing))

        document_set["Stage_1"] = s1_specs
        document_set["Stage_2"] = s2_specs

    return document_set, missing
```

---

## PART 4 — Update `build_audit_set_zip` to use the new resolver output

The `build_audit_set_zip` function in `backend/audit_set/resolver.py` (or wherever it is defined — it may be in `backend/api/routes/audit_sets.py`) currently calls the old `resolve_document_set`. The new resolver returns the same `(document_set, missing)` shape, so minimal changes are needed.

Find `build_audit_set_zip` and verify:
1. It calls `resolve_document_set(audit_set)` and receives `(document_set, missing)`
2. It iterates `document_set.items()` → `(folder_name, specs)` → writes each `spec.template_path` into the ZIP under `{folder_name}/{spec.output_filename}`
3. If `missing` is non-empty, it adds `MISSING_TEMPLATES.txt` to the ZIP (this was already implemented — keep it)

If `build_audit_set_zip` is not in `resolver.py`, find it and update any import that references the old `_build_stage_1`, `_build_stage_2`, `_build_surveillance`, `_add`, `BLANK_SET_PATH`, `GROUP_FOLDER`, `STAGE_SUBFOLDER`, or `STAGE_SUBFOLDER_EN` — all of these are removed in the rewrite.

---

## PART 5 — Remove stale imports from `resolver.py`

The new resolver does not use `FR217_MAP` or the old per-stage builder functions. Remove:
- The import of `FR217_MAP` from `field_maps`
- The old `STANDARD_FOLDER`, `GROUP_FOLDER`, `STAGE_SUBFOLDER`, `STAGE_SUBFOLDER_EN`, `STAGE_SUBFOLDER_RECERT_EN`, `STAGE_SUBFOLDER_RECERT_TR` dicts
- The old `_build_stage_1`, `_build_stage_2`, `_build_surveillance`, `_add` functions
- `BASE_STANDARDS` (replaced by `_BASE_STANDARDS`)
- `BLANK_SET_PATH` module-level constant

Keep:
- `DocumentSpec` dataclass (unchanged)
- The `_clean_filename` helper (reused)

---

## PART 6 — Update `field_maps.py` imports (if needed)

If `FR217_MAP` is only imported in `resolver.py`, remove it from that import. If it is used elsewhere (e.g. in a filler that processes `DocumentSpec`), leave it where it is.

---

## PART 7 — Frontend: expose `document_language` in the audit set creation form

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx` or wherever the audit set creation form is.

For audit sets where `accreditation_body` is `"TÜRKAK"` or `"TURKAK"`, show a language selector before the download button or in the audit set creation form:

```tsx
{(auditSet.accreditation_body === 'TÜRKAK' || auditSet.accreditation_body === 'TURKAK') && (
  <div className="flex items-center gap-2">
    <label className="text-sm font-medium">Document Language</label>
    <select
      value={auditSet.document_language ?? 'turkish'}
      onChange={e => updateAuditSet({ document_language: e.target.value })}
      className="text-sm border rounded px-2 py-1"
    >
      <option value="turkish">Turkish</option>
      <option value="english">English</option>
    </select>
  </div>
)}
```

Where `updateAuditSet` calls the existing PATCH/PUT endpoint that saves `document_language` to the audit set. If there is no PATCH endpoint for audit sets, add `document_language` to the existing update payload.

For UAF audit sets, do not show this selector at all (UAF always uses English docs with Turkish folder names — no choice to make).

---

## DO NOT CHANGE

- `backend/audit_set/field_maps.py` — coordinates are correct
- `build_audit_set_zip` ZIP assembly logic — only update it to use the new resolver output shape if needed
- The existing `MISSING_TEMPLATES.txt` logic — keep it exactly as is
- All other files not mentioned above

---

## VERIFICATION

After all changes:

1. **UAF initial audit with ISO 9001**: Download package → ZIP must contain:
   - `Stage_1/` with FR.211, FR.218, FR.220, FR.221, FR.222, FR.223, FR.224, FR.225, FR.230, FR.231
   - `Stage_2/` with FR.211, FR.223, FR.224, FR.225, FR.230, FR.232
   - No FR.217 anywhere
   - No `MISSING_TEMPLATES.txt`

2. **UAF surveillance_1 with ISO 9001**: Download → ZIP must contain:
   - `Surveillance/` with FR.211, FR.223, FR.224, FR.225, FR.230, FR.232, FR.234
   - No Stage_1 or Stage_2 folders

3. **UAF initial with ISO 27001**: Download → ZIP must contain:
   - `Stage_2/` with FR.229 (not FR.232)
   - `Stage_1/` with FR.231 (not FR.231-1)

4. **UAF initial with ISO 13485**: Download → ZIP must contain:
   - `Stage_1/` with FR.231-1 (not FR.231)
   - `Stage_2/` with FR.232-1 (not FR.232)

5. **UAF recertification with ISO 9001**: Download → ZIP must contain:
   - `Stage_1/` and `Stage_2/` (same folders as initial, no "Recertification" folder)
   - `Stage_2/` files are from `uaf_blank_set/9-14-45-22-5001/İlk Belgelendirme/Aşama 2/`

6. **TÜRKAK Turkish audit with ISO 9001**: Download → ZIP must contain:
   - Templates sourced from `turkak_blank_set/turkish/9-14-45-22-5001/`
   - Turkish-language filename variants (e.g. FR.232_Denetim_Raporu, FR.225_Acilis_Kapanis...)

7. **TÜRKAK English audit with ISO 27001**: Download → ZIP must contain:
   - `Stage_1/` with FR.231 (not FR.231-1)
   - `Stage_2/` with FR.229 (not FR.232)
   - Templates sourced from `turkak_blank_set/english/27001/`

8. **TÜRKAK audit with ISO 13485 (MDQMS)**: Download → ZIP must NOT crash — instead log a warning and skip the 13485 group. If no other standards are selected, ZIP may be empty but no exception is thrown.

9. **GET /api/audit-sets/{id}** response must include `document_language` field.

10. **`document_language` selector** appears in the UI for TÜRKAK audit sets, defaults to "turkish", and is absent for UAF audit sets.
