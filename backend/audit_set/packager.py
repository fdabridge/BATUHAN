"""
BATUHAN — Audit Set: ZIP packager.

Combines `resolver.resolve_document_set` and `filler.fill_document` to produce
one ZIP archive per AuditSet, organised as:

    Set_<plan_number>_<company_slug>/
        Stage_1/<FR.xxx>.docx
        Stage_2/<FR.xxx>.docx
        Surveillance/<FR.xxx>.docx
"""
from __future__ import annotations

import io
import zipfile

from audit_set.filler import build_values, fill_document
from audit_set.resolver import resolve_document_set


# Map output folder name → AuditSetStage.stage_type value
FOLDER_TO_STAGE_TYPE = {
    "Stage_1":      "stage_1",
    "Stage_2":      "stage_2",
    "Surveillance": "surveillance",
}


def build_audit_set_zip(audit_set, db) -> bytes:
    """
    Build the full filled-document ZIP for an `AuditSet`.

    Args:
        audit_set: AuditSet ORM instance (with `.stages` loaded).
        db:        SQLAlchemy session (currently unused, kept for symmetry
                   with other service-layer signatures and future-proofing).
    Returns:
        ZIP archive as raw bytes.
    """
    del db  # not needed today; kept in signature per service convention

    document_set, missing_templates = resolve_document_set(audit_set)

    # Index stages by stage_type for O(1) lookup
    stages_by_type = {s.stage_type: s for s in (audit_set.stages or [])}

    # Build company slug for the top-level folder inside the ZIP
    raw_name = (audit_set.company_name or "Unknown")[:20].replace(" ", "_")
    company_slug = f"Set_{audit_set.plan_number}_{raw_name}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for output_folder, doc_specs in document_set.items():
            stage_type = FOLDER_TO_STAGE_TYPE.get(output_folder)
            stage_obj = stages_by_type.get(stage_type) if stage_type else None

            for doc in doc_specs:
                stage_for_values = stage_obj if doc.stage_context != "all" else None

                if not doc.field_map:
                    # Templates with no field map (e.g. FR.220 quotation) are
                    # copied verbatim from disk.
                    file_bytes = doc.template_path.read_bytes()
                else:
                    values = build_values(audit_set, stage=stage_for_values)
                    file_bytes = fill_document(doc.template_path, doc.field_map, values)

                arcname = f"{company_slug}/{output_folder}/{doc.output_filename}"
                zf.writestr(arcname, file_bytes)

        # If any template files were not found on disk, include a manifest so the
        # coordinator knows which documents are missing from this package.
        if missing_templates:
            manifest_lines = [
                "The following templates were not found on disk and are missing from this package:",
                "",
            ] + [f"  - {m}" for m in missing_templates]
            zf.writestr(f"{company_slug}/MISSING_TEMPLATES.txt", "\n".join(manifest_lines))

    return buf.getvalue()
