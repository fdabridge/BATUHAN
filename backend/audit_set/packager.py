"""
BATUHAN — Audit Set: ZIP packager (docxtpl pipeline).

Combines `resolver.resolve_document_set` (which DOCX templates per stage) with
`filler` (Jinja2 context + docxtpl render) to produce one ZIP per AuditSet:

    Set_<plan_number>_<company_slug>/
        Stage_1/<FR.xxx>.docx
        Stage_2/<FR.xxx>.docx
        Surveillance/<FR.xxx>.docx

FR.224 (Audit Team Information) and FR.211 (Auditor Assessment) are rendered
once per team member: FR.224_<PersonName>.docx, FR.211_<PersonName>.docx.

Each template is rendered independently; a failure on one template is recorded
in RENDER_ERRORS.txt rather than aborting the whole package.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile

from audit_set.filler import (
    PER_PERSON_FORMS,
    build_auditor_scope_strings,
    build_base_context,
    build_team_members,
    render_docx,
)
from audit_set.resolver import resolve_document_set

logger = logging.getLogger(__name__)

# Map output folder name → AuditSetStage.stage_type value
FOLDER_TO_STAGE_TYPE = {
    "Stage_1":      "stage_1",
    "Stage_2":      "stage_2",
    "Surveillance": "surveillance",
}


def _safe_filename(name: str) -> str:
    """Make a person name safe for a file name."""
    return re.sub(r"[^\w\-]+", "_", (name or "").strip()).strip("_") or "Unknown"


def _collect_auditor_ids(audit_set) -> set[str]:
    ids: set[str] = set()
    for s in (audit_set.stages or []):
        if s.lead_auditor_id:
            ids.add(s.lead_auditor_id)
        for group in (s.auditors or [], s.technical_experts or []):
            for member in group:
                if member.get("id"):
                    ids.add(member["id"])
    return ids


def _build_auditor_lookup(audit_set) -> dict:
    """Fetch Auditor ORM objects (with qualifications) for all team members.
    Degrades to an empty lookup if the auditors DB is unavailable."""
    ids = _collect_auditor_ids(audit_set)
    if not ids:
        return {}
    try:
        from auditors.models import Auditor, SessionLocal
        db = SessionLocal()
        try:
            rows = db.query(Auditor).filter(Auditor.id.in_(ids)).all()
            # Touch qualifications while the session is open.
            return {a.id: a for a in rows if a.standard_qualifications is not None or True}
        finally:
            db.close()
    except Exception:  # pragma: no cover - defensive
        logger.warning("[Packager] auditor lookup failed", exc_info=True)
        return {}


def _person_output_name(base_name: str, person_name: str) -> str:
    safe = _safe_filename(person_name)
    stem, dot, ext = base_name.rpartition(".")
    return f"{stem}_{safe}.{ext}" if dot else f"{base_name}_{safe}"


def build_audit_set_zip(audit_set, db) -> bytes:
    """Build the full rendered-document ZIP for an `AuditSet`."""
    del db  # audit-sets session not needed; auditors use their own session

    document_set, missing_templates = resolve_document_set(audit_set)
    stages_by_type = {s.stage_type: s for s in (audit_set.stages or [])}
    required_scope = audit_set.required_scope or {}
    standards_codes = audit_set.standards or []
    auditor_lookup = _build_auditor_lookup(audit_set)

    raw_name = (audit_set.company_name or "Unknown")[:20].replace(" ", "_")
    company_slug = f"Set_{audit_set.plan_number}_{raw_name}"

    render_errors: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for output_folder, doc_specs in document_set.items():
            stage = stages_by_type.get(FOLDER_TO_STAGE_TYPE.get(output_folder))
            if stage is None:
                continue

            ctx = build_base_context(audit_set, stage)
            ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
            team = build_team_members(stage, auditor_lookup, standards_codes)

            for doc in doc_specs:
                base_out = doc.output_filename
                try:
                    if doc.fr_number in PER_PERSON_FORMS and team:
                        for person in team:
                            pctx = {
                                **ctx,
                                "assessed_person_name": person["name"],
                                "person_standards":     person["person_standards"],
                                "person_clauses":       person["person_clauses"],
                            }
                            data = render_docx(doc.template_path, pctx)
                            out = _person_output_name(base_out, person["name"])
                            zf.writestr(f"{company_slug}/{output_folder}/{out}", data)
                    else:
                        data = render_docx(doc.template_path, ctx)
                        zf.writestr(f"{company_slug}/{output_folder}/{base_out}", data)
                except Exception as exc:
                    logger.warning(
                        "[Packager] render failed %s/%s: %s",
                        output_folder, doc.fr_number, exc,
                    )
                    render_errors.append(f"{output_folder}/{base_out}: {exc}")

        if missing_templates:
            lines = ["Templates not found on disk (missing from this package):", ""]
            lines += [f"  - {m}" for m in missing_templates]
            zf.writestr(f"{company_slug}/MISSING_TEMPLATES.txt", "\n".join(lines))

        if render_errors:
            lines = ["Templates that failed to render (Jinja/template errors):", ""]
            lines += [f"  - {e}" for e in render_errors]
            zf.writestr(f"{company_slug}/RENDER_ERRORS.txt", "\n".join(lines))

    return buf.getvalue()
