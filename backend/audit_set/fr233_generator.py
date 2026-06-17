"""
Portal 49a Part 3 — FR.233 Review & Decision Form generator.

Renders an FR.233 DOCX for an audit set by:
  1. Resolving the correct blank template via the existing resolver.
  2. Filling project metadata (Table 0) and committee names (Table 3).
  3. Inserting ``[SIG:COMMITTEE_*]`` and ``[SIG:CERT_MANAGER_FR233]`` markers
     so the viewer's lazy field-extraction pipeline can place signatures.
"""
from __future__ import annotations

import copy
from datetime import date
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docxtpl import DocxTemplate
from lxml import etree
from sqlalchemy.orm import Session

from audit_set.resolver import resolve_document_set


def _set_cell_text(tc_el, text: str) -> None:
    """Clear all paragraphs in a <w:tc> and write `text` into a single run on
    the first paragraph, preserving paragraph + run formatting where possible."""
    paragraphs = tc_el.findall(qn("w:p"))
    if not paragraphs:
        return
    for extra in paragraphs[1:]:
        tc_el.remove(extra)
    p = paragraphs[0]
    pPr = p.find(qn("w:pPr"))
    saved_rPr = None
    for r in p.findall(qn("w:r")):
        if saved_rPr is None:
            rPr = r.find(qn("w:rPr"))
            if rPr is not None:
                saved_rPr = copy.deepcopy(rPr)
        p.remove(r)
    if text == "":
        return
    new_r = etree.SubElement(p, qn("w:r"))
    if saved_rPr is not None:
        new_r.append(saved_rPr)
    new_t = etree.SubElement(new_r, qn("w:t"))
    new_t.text = text
    new_t.set(qn("xml:space"), "preserve")


def _fmt_d(d) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def _build_committee_context(audit_set) -> list[dict]:
    """Portal 62 — context for the docxtpl `{%tr for member in committee_members %}`
    loop. Reads the denormalized snapshot stored on AuditSet.committee_members.

    Falls back to 3 blank placeholder rows (id ``BLANK_<n>``) when the
    committee has not yet been appointed so the template still renders
    readable rows. The viewer treats `COMMITTEE_MEMBER_BLANK_*` sig_keys as
    non-signable "awaiting committee appointment" placeholders.
    """
    raw = audit_set.committee_members or []
    members = list(raw) if isinstance(raw, list) else []

    # Chairperson first.
    members.sort(key=lambda m: 0 if m.get("role") == "chairperson" else 1)

    ctx = [
        {
            "id":            m.get("id", ""),
            "name":          m.get("name") or m.get("full_name") or "",
            "ea_codes_str":  ", ".join(m.get("ea_codes") or []),
            "role":          m.get("role", "member"),
        }
        for m in members
    ]

    if not ctx:
        ctx = [
            {"id": f"BLANK_{i}", "name": "", "ea_codes_str": "", "role": "member"}
            for i in range(3)
        ]

    return ctx


def _resolve_fr233_template(audit_set):
    document_set, _missing = resolve_document_set(audit_set)
    for folder, specs in document_set.items():
        for spec in specs:
            if spec.fr_number == "FR.233":
                return spec.template_path
    return None


def render_fr233_bytes(audit_set, db: Session) -> bytes:
    """Render FR.233 bytes.

    Portal 62 — two-pass render:
      1. docxtpl pass expands the committee-rows ``{%tr for member ... %}``
         loop in the patched template using ``committee_members`` context.
      2. python-docx pass fills Table 0 metadata (project number, dates, etc.)
         on the docxtpl output.

    The legacy static committee-row fill (`_fill_committee_table`) is gone:
    committee rows are now generated dynamically by docxtpl.
    """
    template_path = _resolve_fr233_template(audit_set)
    if template_path is None:
        raise RuntimeError("FR.233 template not found for this audit set")

    # Pass 1 — docxtpl committee loop expansion.
    tpl = DocxTemplate(str(template_path))
    tpl.render({"committee_members": _build_committee_context(audit_set)})
    buf1 = BytesIO()
    tpl.save(buf1)
    buf1.seek(0)

    # Pass 2 — python-docx Table 0 metadata fill on the docxtpl output.
    doc = Document(buf1)

    stages = {s.stage_type: s for s in (audit_set.stages or [])}
    stage1 = stages.get("stage_1")
    stage2 = stages.get("stage_2")
    auditors = [p for p in (audit_set.personnel or {}).get("auditors", []) if p.get("name")]
    team_str = ", ".join(
        f"{a['name']} (Lead Auditor)" if a.get("is_lead") else a["name"]
        for a in auditors
    )

    if len(doc.tables) >= 1:
        _safe_fill_table0(doc.tables[0], audit_set, team_str, stage1, stage2)

    buf2 = BytesIO()
    doc.save(buf2)
    return buf2.getvalue()


def _safe_fill_table0(t0, audit_set, team_str: str, stage1, stage2) -> None:
    """Best-effort fill of FR.233 Table 0 — silently skips rows that don't match."""
    rows = t0.rows
    pairs = [
        (0, 1, audit_set.plan_number or ""),
        (1, 1, audit_set.company_name or ""),
        (2, 1, audit_set.company_address or ""),
        (3, 1, ", ".join(audit_set.standards or [])),
        (4, 1, audit_set.ea_code or ""),
        (6, 1, team_str),
        (7, 1, _fmt_d(stage1.audit_date_start if stage1 else None)),
        (7, 3, _fmt_d(stage2.audit_date_start if stage2 else None)),
        (8, 1, _fmt_d(getattr(stage1, "report_date", None))),
        (8, 3, _fmt_d(getattr(stage2, "report_date", None))),
        (9, 1, _fmt_d(date.today())),
    ]
    for ri, ci, value in pairs:
        if ri < len(rows) and ci < len(rows[ri].cells):
            _set_cell_text(rows[ri].cells[ci]._tc, value)



