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
from audit_set.postprocess import (
    apply_audit_type_highlighting,
    apply_standard_highlighting,
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


# Forms that carry legacy Word form-field checkboxes for the standards grid.
CHECKBOX_FORMS = {"FR.220", "FR.221"}

# ISO standard label (as printed in the template) → internal standard code.
_STANDARD_LABEL_TO_CODE = [
    ("ISO 9001:2015",       "QMS"),
    ("ISO 14001:2015",      "EMS"),
    ("ISO 45001:2018",      "OHSMS"),
    ("ISO 22000:2018",      "FSMS"),
    ("ISO/IEC 27001:2022",  "ISMS"),
    ("ISO 50001:2018",      "ENMS"),
    ("ISO 13485:2016",      "MDQMS"),
    ("ISO 37001:2016",      "ABMS"),
]

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def apply_checkbox_selection(docx_bytes: bytes, standards_codes: list[str]) -> bytes:
    """Tick the legacy form-field checkboxes for the audit's selected standards.

    docxtpl cannot fill `<w:checkBox>` form fields, so we post-process the
    rendered DOCX: each checkbox is paired with the ISO label that follows it in
    the same cell, and its checked/default state is set from `standards_codes`.
    Unmapped checkboxes (non-standard fields) are left untouched. Failures are
    swallowed so a checkbox issue never breaks the package.
    """
    from lxml import etree

    def q(tag: str) -> str:
        return f"{{{_W_NS}}}{tag}"

    selected = set(standards_codes or [])
    try:
        zin = zipfile.ZipFile(io.BytesIO(docx_bytes))
        root = etree.fromstring(zin.read("word/document.xml"))

        # Walk in document order, pairing each checkBox with the text that
        # follows it (up to the next checkBox) so we can read its ISO label.
        pairs: list[tuple] = []          # (checkBox_elem, selected_bool)
        current_cb = None
        buf: list[str] = []

        def _flush(cb, text: str) -> None:
            if cb is None:
                return
            for label, code in _STANDARD_LABEL_TO_CODE:
                if label in text:
                    pairs.append((cb, code in selected))
                    return

        for el in root.iter():
            if el.tag == q("checkBox"):
                _flush(current_cb, "".join(buf))
                current_cb, buf = el, []
            elif el.tag == q("t") and el.text:
                buf.append(el.text)
        _flush(current_cb, "".join(buf))

        for cb, is_sel in pairs:
            val = "1" if is_sel else "0"
            for child_tag in ("default", "checked"):
                child = cb.find(q(child_tag))
                if child is None:
                    child = etree.SubElement(cb, q(child_tag))
                child.set(q("val"), val)

        new_xml = etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for item in zin.namelist():
                zo.writestr(
                    item,
                    new_xml if item == "word/document.xml" else zin.read(item),
                )
        return out.getvalue()
    except Exception:  # pragma: no cover - defensive
        logger.warning("[Packager] checkbox post-process failed", exc_info=True)
        return docx_bytes


def _blank_org_attendee_rows(n: int = 3) -> list[dict]:
    """Portal 57 — placeholder rows so FR.225 always renders signature lines.
    The BLANK sig_keys do not match the viewer's ORG_SIG_RE (which requires a
    UUID), so they remain unsignable but produce visible empty cells."""
    return [
        {"name": "", "role": "", "sig_key": f"ORG_EMP_BLANK_{i}"}
        for i in range(n)
    ]


def _resolve_org_attendees(audit_set, db) -> list[dict]:
    """Portal 49a — resolve the client's active ClientOrgEmployee roster for
    FR.225 docxtpl injection. The template wraps ``emp.sig_key`` with
    ``ORG_OPENING_`` / ``ORG_CLOSING_`` prefixes per row, so this function
    must return the bare ``ORG_EMP_<uuid>`` token.

    Falls back to 3 blank placeholder rows when no client is linked, the
    employees table is missing, or no employees are registered yet, so the
    rendered form never collapses to zero participant rows (Portal 57)."""
    if db is None or audit_set is None:
        return _blank_org_attendee_rows()
    try:
        from audit_set.db_models import ClientOrgEmployee
        from auth.db_models import PlatformUser, SessionLocal as AuthSessionLocal
        auth_db = AuthSessionLocal()
        try:
            client = (
                auth_db.query(PlatformUser)
                .filter_by(role="client", audit_set_id=audit_set.id)
                .first()
            )
            if not client:
                return _blank_org_attendee_rows()
            employees = (
                db.query(ClientOrgEmployee)
                .filter_by(client_user_id=client.id, is_active=True)
                .order_by(ClientOrgEmployee.created_at)
                .all()
            )
            if not employees:
                return _blank_org_attendee_rows()
            return [
                {"name": e.full_name, "role": e.role_title, "sig_key": f"ORG_EMP_{e.id}"}
                for e in employees
            ]
        finally:
            auth_db.close()
    except Exception:  # pragma: no cover — defensive: never break the packager
        logger.warning("[Packager] org_attendees resolution failed", exc_info=True)
        return _blank_org_attendee_rows()


def build_audit_set_zip(audit_set, db) -> bytes:
    """Build the full rendered-document ZIP for an `AuditSet`."""
    document_set, missing_templates = resolve_document_set(audit_set)
    stages_by_type = {s.stage_type: s for s in (audit_set.stages or [])}
    required_scope = audit_set.required_scope or {}
    standards_codes = audit_set.standards or []
    auditor_lookup = _build_auditor_lookup(audit_set)
    org_attendees = _resolve_org_attendees(audit_set, db)

    raw_name = (audit_set.company_name or "Unknown")[:20].replace(" ", "_")
    company_slug = f"Set_{audit_set.plan_number}_{raw_name}"

    render_errors: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for output_folder, doc_specs in document_set.items():
            stage = stages_by_type.get(FOLDER_TO_STAGE_TYPE.get(output_folder))
            if stage is None:
                continue

            ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
            ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
            # EA-code fallback for FR.224 display when the auditor profile is incomplete.
            if not ctx.get("lead_auditor_codes"):
                ctx["lead_auditor_codes"] = audit_set.ea_code or ""
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
                        # Portal 58 — FR.211 (per-stage auditor assessment):
                        # pre-fill `assessed_person_name` with the stage lead
                        # auditor; client uploads + signs one per stage.
                        if doc.fr_number == "FR.211":
                            rctx = {
                                **ctx,
                                "assessed_person_name": ctx.get("lead_auditor_name", "") or "",
                            }
                        else:
                            rctx = ctx
                        data = render_docx(doc.template_path, rctx)
                        if doc.fr_number in CHECKBOX_FORMS:
                            data = apply_checkbox_selection(data, standards_codes)
                            data = apply_standard_highlighting(data, standards_codes)
                            data = apply_audit_type_highlighting(
                                data, audit_set.audit_type or ""
                            )
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
