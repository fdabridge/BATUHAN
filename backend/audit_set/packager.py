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
from types import SimpleNamespace

from audit_set.filler import (
    PER_PERSON_FORMS,
    build_auditor_scope_strings,
    build_base_context,
    build_team_members,
    render_docx,
)
from audit_set.fr222_postprocess import ensure_fr222_possible_audit_dates
from audit_set.fr233_generator import render_fr233_bytes
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
    "Recertification": "recertification",
}

STAGE_COPY_ATTRS = (
    "id",
    "audit_set_id",
    "stage_type",
    "stage_order",
    "status",
    "audit_days",
    "lead_auditor_id",
    "lead_auditor_name",
    "audit_date_start",
    "audit_date_end",
    "auditors",
    "technical_experts",
    "observers",
    "trainees",
    "ik_experts",
    "evaluators",
)


def _stage_with_type(stage, stage_type: str):
    if stage is None or getattr(stage, "stage_type", None) == stage_type:
        return stage
    data = {name: getattr(stage, name, None) for name in STAGE_COPY_ATTRS}
    data["stage_type"] = stage_type
    return SimpleNamespace(**data)


def _stage_for_type(audit_set, stages_by_type: dict, stage_type: str):
    stage = stages_by_type.get(stage_type)
    if stage is not None:
        return stage

    # Production compatibility: older recertification records were mistakenly
    # created as stage_1 + stage_2. Render them as one recertification stage
    # until their rows are corrected.
    if stage_type == "recertification" and (audit_set.audit_type or "").lower() == "recertification":
        return _stage_with_type(stages_by_type.get("stage_2") or stages_by_type.get("stage_1"), "recertification")
    return None


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
    must return the bare ``ORG_EMP_N`` token (Portal 73: 1-based row index,
    ordered by created_at — must stay in sync with viewer_router lookup).

    Falls back to 3 blank placeholder rows when no client is linked, the
    employees table is missing, or no employees are registered yet, so the
    rendered form never collapses to zero participant rows (Portal 57)."""
    if db is None or audit_set is None:
        logger.warning("[FR225] _resolve_org_attendees called with db=%r audit_set=%r", db, audit_set)
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
                logger.warning("[FR225] No client user found for audit_set_id=%s", audit_set.id)
                return _blank_org_attendee_rows()
            employees = (
                db.query(ClientOrgEmployee)
                .filter_by(client_user_id=client.id, is_active=True)
                .order_by(ClientOrgEmployee.created_at)
                .all()
            )
            logger.info(
                "[FR225] Found %d employees for client_id=%s (audit_set=%s)",
                len(employees), client.id, audit_set.id,
            )
            if not employees:
                logger.warning("[FR225] Zero employees registered — using blank placeholders")
                return _blank_org_attendee_rows()
            return [
                {"name": e.full_name, "role": e.role_title, "sig_key": f"ORG_EMP_{i}"}
                for i, e in enumerate(employees, 1)
            ]
        finally:
            auth_db.close()
    except Exception:  # pragma: no cover — defensive: never break the packager
        logger.warning("[FR225] org_attendees resolution failed", exc_info=True)
        return _blank_org_attendee_rows()


# Portal 60 — reverse map for single-document regeneration.
STAGE_TYPE_TO_FOLDER = {v: k for k, v in FOLDER_TO_STAGE_TYPE.items()}


def render_single_document(audit_set, db, fr_number: str, stage_type: str) -> tuple[str, bytes]:
    """Portal 60 — render one DOCX from the resolved document set, using the
    current org-employee roster + auditor context. Returns
    ``(output_filename, docx_bytes)`` or raises ``ValueError`` when the
    template isn't part of this audit set's document set.

    Used by the FR.225 regeneration endpoint; mirrors the once-per-stage
    branch of :func:`build_audit_set_zip`."""
    document_set, _ = resolve_document_set(audit_set)
    target_folder = STAGE_TYPE_TO_FOLDER.get(stage_type)
    if not target_folder:
        raise ValueError(f"Unknown stage_type {stage_type!r}")

    specs = document_set.get(target_folder) or []
    spec = next((s for s in specs if s.fr_number == fr_number), None)
    if spec is None:
        raise ValueError(
            f"{fr_number} is not part of this audit set's document set "
            f"for {stage_type}",
        )

    stages_by_type = {s.stage_type: s for s in (audit_set.stages or [])}
    stage = _stage_for_type(audit_set, stages_by_type, stage_type)
    if stage is None:
        raise ValueError(f"Audit set has no {stage_type} stage")

    org_attendees = _resolve_org_attendees(audit_set, db)
    auditor_lookup = _build_auditor_lookup(audit_set)
    required_scope = audit_set.required_scope or {}
    standards_codes = audit_set.standards or []

    ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
    ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
    if not ctx.get("lead_auditor_codes"):
        ctx["lead_auditor_codes"] = audit_set.ea_code or ""
    # FSMS fallback: ea_code and ea_category are not stored on AuditSet for
    # ISO 22000 (required_scope uses type="food" which _first_ea_code_from_scope
    # ignores; the frontend sends no ea_category field). Derive both from the
    # food-chain codes already stored in required_scope.
    if "FSMS" in standards_codes:
        _fsms_entry = required_scope.get("ISO 22000:2018") or required_scope.get("FSMS") or {}
        _fsms_codes = _fsms_entry.get("codes") or []
        if not ctx.get("ea_code") and _fsms_codes:
            ctx["ea_code"] = ", ".join(_fsms_codes)
        if not ctx.get("ea_category") and _fsms_codes:
            ctx["ea_category"] = ", ".join(_fsms_codes)

    if fr_number == "FR.211":
        ctx["assessed_person_name"] = ctx.get("lead_auditor_name", "") or ""

    if fr_number == "FR.233":
        data = render_fr233_bytes(
            audit_set, db, template_path=spec.template_path,
        )
    else:
        data = render_docx(spec.template_path, ctx)
    if fr_number == "FR.222":
        data = ensure_fr222_possible_audit_dates(data, ctx)
    # Always apply colour highlighting (safe no-op on forms without standard/audit-type cells).
    data = apply_standard_highlighting(data, standards_codes)
    data = apply_audit_type_highlighting(data, audit_set.audit_type or "")
    # Tick legacy Word checkboxes only on FR.220 / FR.221.
    if fr_number in CHECKBOX_FORMS:
        data = apply_checkbox_selection(data, standards_codes)
    return spec.output_filename, data


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
            stage_type = FOLDER_TO_STAGE_TYPE.get(output_folder)
            stage = _stage_for_type(audit_set, stages_by_type, stage_type) if stage_type else None
            if stage is None:
                continue

            ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
            ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
            # EA-code fallback for FR.224 display when the auditor profile is incomplete.
            if not ctx.get("lead_auditor_codes"):
                ctx["lead_auditor_codes"] = audit_set.ea_code or ""
            # FSMS fallback: ea_code and ea_category are not stored on AuditSet for
            # ISO 22000 (required_scope uses type="food" which _first_ea_code_from_scope
            # ignores; the frontend sends no ea_category field). Derive both from the
            # food-chain codes already stored in required_scope.
            if "FSMS" in standards_codes:
                _fsms_entry = required_scope.get("ISO 22000:2018") or required_scope.get("FSMS") or {}
                _fsms_codes = _fsms_entry.get("codes") or []
                if not ctx.get("ea_code") and _fsms_codes:
                    ctx["ea_code"] = ", ".join(_fsms_codes)
                if not ctx.get("ea_category") and _fsms_codes:
                    ctx["ea_category"] = ", ".join(_fsms_codes)
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
                        # Fallback only: normal FR.211 packaging is per team
                        # member via PER_PERSON_FORMS when the stage has a team.
                        if doc.fr_number == "FR.211":
                            rctx = {
                                **ctx,
                                "assessed_person_name": ctx.get("lead_auditor_name", "") or "",
                            }
                        else:
                            rctx = ctx
                        if doc.fr_number == "FR.233":
                            data = render_fr233_bytes(
                                audit_set, db, template_path=doc.template_path,
                            )
                        else:
                            data = render_docx(doc.template_path, rctx)
                        if doc.fr_number == "FR.222":
                            data = ensure_fr222_possible_audit_dates(data, rctx)
                        # Always apply colour highlighting (safe no-op on forms without
                        # standard/audit-type cells).
                        data = apply_standard_highlighting(data, standards_codes)
                        data = apply_audit_type_highlighting(data, audit_set.audit_type or "")
                        # Tick legacy Word checkboxes only on FR.220 / FR.221.
                        if doc.fr_number in CHECKBOX_FORMS:
                            data = apply_checkbox_selection(data, standards_codes)
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
