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
from lxml import etree
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSetCommitteeMember, AuditSetStage
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


def _build_committee_payload(audit_set, db: Session) -> dict:
    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    chair = next((m for m in members if m.role == "decision_maker"), None)
    regulars = [m for m in members if m is not chair]

    def ea(m):
        codes = m.ea_codes_at_appointment or []
        return codes[0] if codes else ""

    return {
        "chair_name":    chair.user_name if chair else "",
        "chair_ea":      ea(chair) if chair else "",
        "member1_name":  regulars[0].user_name if len(regulars) > 0 else "",
        "member1_ea":    ea(regulars[0]) if len(regulars) > 0 else "",
        "member2_name":  regulars[1].user_name if len(regulars) > 1 else "",
        "member2_ea":    ea(regulars[1]) if len(regulars) > 1 else "",
    }


def _resolve_fr233_template(audit_set):
    document_set, _missing = resolve_document_set(audit_set)
    for folder, specs in document_set.items():
        for spec in specs:
            if spec.fr_number == "FR.233":
                return spec.template_path
    return None


def render_fr233_bytes(audit_set, db: Session) -> bytes:
    template_path = _resolve_fr233_template(audit_set)
    if template_path is None:
        raise RuntimeError("FR.233 template not found for this audit set")

    doc = Document(str(template_path))
    committee = _build_committee_payload(audit_set, db)

    stages = {s.stage_type: s for s in (audit_set.stages or [])}
    stage1 = stages.get("stage_1")
    stage2 = stages.get("stage_2")
    auditors = [p for p in (audit_set.personnel or {}).get("auditors", []) if p.get("name")]
    team_str = ", ".join(
        f"{a['name']} (Lead Auditor)" if a.get("is_lead") else a["name"]
        for a in auditors
    )

    if len(doc.tables) >= 1:
        t0 = doc.tables[0]
        _safe_fill_table0(t0, audit_set, team_str, stage1, stage2)

    # Portal 57 — committee block lives in the LAST table (index 4 in current
    # templates). Earlier code targeted tables[3], which is the Decision
    # checklist, so the committee names + [SIG:...] markers were never written.
    if len(doc.tables) >= 5:
        _fill_committee_table(doc.tables[4], committee)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


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


def _fill_committee_table(t, c: dict) -> None:
    """Portal 57 — fill the FR.233 committee signature table.

    Template layout (verified in uaf_blank_set FR.233 R5&09.10.2025):
      Row 0: header  ['', 'Name Surname', 'EA/IAF Code', 'Sign']    (4 cells)
      Row 1: chairperson    cells = [label, name, ea, sign]         (4 cells)
      Row 2: member 1       cells = [label, name, ea, sign]         (4 cells)
      Row 3: member 2       cells = [label, name, ea, sign]         (4 cells)
      Row 4: spacer
      Row 5: 'To Endorse the Decision on Behalf of …'
      Row 6: cert manager   cells = ['Certification Manager Approval', sign, 'Sign']  (3 cells)
    """
    rows = t.rows
    triples = [
        (1, c["chair_name"],   c["chair_ea"],   "[SIG:COMMITTEE_CHAIR]"),
        (2, c["member1_name"], c["member1_ea"], "[SIG:COMMITTEE_MEMBER_1]"),
        (3, c["member2_name"], c["member2_ea"], "[SIG:COMMITTEE_MEMBER_2]"),
    ]
    for ri, name, ea, sig in triples:
        if ri >= len(rows):
            continue
        cells = rows[ri].cells
        if len(cells) > 1: _set_cell_text(cells[1]._tc, name)
        if len(cells) > 2: _set_cell_text(cells[2]._tc, ea)
        if len(cells) > 3: _set_cell_text(cells[3]._tc, sig)

    if len(rows) > 6:
        cm_cells = rows[6].cells
        # CM row has fewer cells (label, sig, 'Sign' label). Drop the SIG
        # marker into the middle cell, which is the empty signature box.
        if len(cm_cells) > 1:
            _set_cell_text(cm_cells[1]._tc, "[SIG:CERT_MANAGER_FR233]")
