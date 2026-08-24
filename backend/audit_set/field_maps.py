"""
BATUHAN — Audit Set: DOCX field coordinate maps.

Each FR<NNN>_MAP dict maps a logical field name to an exact cell coordinate
(table_idx, row_idx, col_idx) inside the corresponding blank IFC template.

Coordinates were derived by inspecting the actual templates under
/Users/batuhan/BATUHAN/uaf_blank_set/ with python-docx.  The blank forms have
NO placeholder strings — they rely on label + empty-cell pairs inside tables,
so the filler writes values directly into those empty cells.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# FR.250 — Transfer Application Control Form
# ---------------------------------------------------------------------------
FR250_MAP = {}


# ---------------------------------------------------------------------------
# FR.217 — Certification Application Form
# ---------------------------------------------------------------------------
FR217_MAP = {
    "company_name":        (0, 0, 1),
    "company_address":     (0, 1, 1),
    "phone":               (0, 2, 1),
    "email":               (0, 3, 1),
    "website":             (0, 4, 1),
    "scope_en":            (3, 0, 1),
    "effective_employees": (4, 0, 1),   # Total number of employees
    "subcontractors":      (4, 2, 1),
    "representative":      (10, 0, 1),
    "today_date":          (10, 1, 1),
}


# ---------------------------------------------------------------------------
# FR.218 — Application Review Form
# ---------------------------------------------------------------------------
FR218_MAP = {
    "today_date":          (0, 0, 1),   # Review Date
    "company_name":        (0, 1, 1),
    "company_address":     (0, 2, 1),
    "standards_str":       (0, 3, 1),
    "scope_en":            (3, 0, 1),
    # R9 uses full per-standard classification matrices instead of the old
    # three-cell EA summary. Selections are instrumented from required_scope.
    "effective_employees": (1, 6, 6),   # Number of Effective Employee value cell
    "decision_committee_chair_name": (29, 1, 1),  # Recommended Auditor/Technical Expert for Decision
}


# ---------------------------------------------------------------------------
# FR.222 — Audit Program (multi-standard)
# Header is in Table 0; per-standard date rows are in Tables 0 (QMS) … 7 (ABMS).
# ---------------------------------------------------------------------------
FR222_MAP = {
    # Header
    "today_date":            (0, 0, 2),
    "plan_number":           (0, 0, 9),
    "company_name":          (0, 1, 2),
    "company_address":       (0, 2, 2),
    "phone":                 (0, 3, 2),
    "email":                 (0, 3, 7),
    "representative":        (0, 4, 2),
    "effective_employees":   (0, 5, 2),
    "shift_count":           (0, 5, 9),
    "standards_str":         (0, 7, 2),
    "ea_code":               (0, 9, 2),
    "ea_category":           (0, 9, 4),
    "ea_technical_area":     (0, 9, 9),
    "scope_en":              (0, 10, 2),
    "non_applicable_clauses": (0, 12, 2),

    # ISO 9001 (QMS) — restored "Possible Audit Dates" row inside Table 0.
    "stage_1_date_qms":          (0, 44, 1),
    "stage_2_date_qms":          (0, 44, 3),
    "surveillance_date_qms":     (0, 44, 6),
    "surveillance_1_date_qms":   (0, 44, 6),
    "surveillance_2_date_qms":   (0, 44, 8),
    "recertification_date_qms":  (0, 44, 11),

    # Per-standard sub-tables: row 3 cols 1..5 = S1, S2, Surv1, Surv2, Recert.
    "stage_1_date_ems":          (1, 3, 1),
    "stage_2_date_ems":          (1, 3, 2),
    "surveillance_date_ems":     (1, 3, 3),
    "surveillance_1_date_ems":   (1, 3, 3),
    "surveillance_2_date_ems":   (1, 3, 4),
    "recertification_date_ems":  (1, 3, 5),

    "stage_1_date_ohsms":          (2, 3, 1),
    "stage_2_date_ohsms":          (2, 3, 2),
    "surveillance_date_ohsms":     (2, 3, 3),
    "surveillance_1_date_ohsms":   (2, 3, 3),
    "surveillance_2_date_ohsms":   (2, 3, 4),
    "recertification_date_ohsms":  (2, 3, 5),

    "stage_1_date_fsms":          (3, 3, 1),
    "stage_2_date_fsms":          (3, 3, 2),
    "surveillance_date_fsms":     (3, 3, 3),
    "surveillance_1_date_fsms":   (3, 3, 3),
    "surveillance_2_date_fsms":   (3, 3, 4),
    "recertification_date_fsms":  (3, 3, 5),

    "stage_1_date_isms":          (4, 3, 1),
    "stage_2_date_isms":          (4, 3, 2),
    "surveillance_date_isms":     (4, 3, 3),
    "surveillance_1_date_isms":   (4, 3, 3),
    "surveillance_2_date_isms":   (4, 3, 4),
    "recertification_date_isms":  (4, 3, 5),

    "stage_1_date_enms":          (5, 3, 1),
    "stage_2_date_enms":          (5, 3, 2),
    "surveillance_date_enms":     (5, 3, 3),
    "surveillance_1_date_enms":   (5, 3, 3),
    "surveillance_2_date_enms":   (5, 3, 4),
    "recertification_date_enms":  (5, 3, 5),

    "stage_1_date_mdqms":          (6, 3, 1),
    "stage_2_date_mdqms":          (6, 3, 2),
    "surveillance_date_mdqms":     (6, 3, 3),
    "surveillance_1_date_mdqms":   (6, 3, 3),
    "surveillance_2_date_mdqms":   (6, 3, 4),
    "recertification_date_mdqms":  (6, 3, 5),

    "stage_1_date_abms":          (7, 3, 1),
    "stage_2_date_abms":          (7, 3, 2),
    "surveillance_date_abms":     (7, 3, 3),
    "surveillance_1_date_abms":   (7, 3, 3),
    "surveillance_2_date_abms":   (7, 3, 4),
    "recertification_date_abms":  (7, 3, 5),
}


# ---------------------------------------------------------------------------
# FR.223 — Audit Plan
# ---------------------------------------------------------------------------
FR223_MAP = {
    "today_date":            (0, 0, 1),
    "plan_number":           (0, 0, 4),
    "company_name":          (0, 1, 1),
    "company_address":       (0, 2, 1),
    "phone":                 (0, 3, 1),
    "email":                 (0, 3, 3),
    "representative":        (0, 4, 1),
    "standards_str":         (0, 5, 1),
    "ea_code":               (0, 7, 1),
    "ea_category":           (0, 7, 2),
    "ea_technical_area":     (0, 7, 4),
    "scope_en":              (0, 8, 1),
    "non_applicable_clauses": (0, 9, 1),
    "audit_type_str":        (0, 10, 1),
    "audit_dates":           (0, 10, 4),   # Audit Date/s (current stage)
    "effective_employees":   (0, 11, 1),
    "audit_days":            (0, 11, 4),
    "shift_count":           (0, 12, 1),

    # Audit team — Table 1
    "lead_auditor_name":      (1, 6, 1),
    "lead_auditor_standard":  (1, 6, 2),
    "lead_auditor_ea":        (1, 6, 4),
    "auditor_1_name":         (1, 7, 1),
    "auditor_1_standard":     (1, 7, 2),
    "auditor_1_ea":           (1, 7, 4),
    "auditor_2_name":         (1, 8, 1),
    "auditor_2_standard":     (1, 8, 2),
    "auditor_2_ea":           (1, 8, 4),
    "technical_expert_1_name": (1, 9, 1),
    "observer_1_name":         (1, 10, 1),
}



# ---------------------------------------------------------------------------
# FR.224 — Audit Team Information Form
# ---------------------------------------------------------------------------
FR224_MAP = {
    # Header (Table 0)
    "today_date":            (0, 0, 1),
    "plan_number":           (0, 0, 4),
    "company_name":          (0, 1, 1),
    "company_address":       (0, 2, 1),
    "phone":                 (0, 3, 1),
    "email":                 (0, 3, 3),
    "representative":        (0, 4, 1),
    "standards_str":         (0, 5, 1),
    "ea_code":               (0, 7, 1),
    "ea_category":           (0, 7, 2),
    "ea_technical_area":     (0, 7, 4),
    "scope_en":              (0, 8, 1),
    "non_applicable_clauses": (0, 9, 1),
    "audit_type_str":        (0, 10, 1),
    "audit_dates":           (0, 10, 4),   # Audit Date/s (current stage)
    "effective_employees":   (0, 11, 1),
    "audit_days":            (0, 11, 4),

    # Audit team — Table 4
    "lead_auditor_name":      (4, 1, 1),
    "lead_auditor_standard":  (4, 1, 2),
    "lead_auditor_ea":        (4, 1, 3),
    "auditor_1_name":         (4, 2, 1),
    "auditor_1_standard":     (4, 2, 2),
    "auditor_1_ea":           (4, 2, 3),
    "auditor_2_name":         (4, 3, 1),
    "auditor_2_standard":     (4, 3, 2),
    "auditor_2_ea":           (4, 3, 3),
    "technical_expert_1_name": (4, 4, 1),
    "observer_1_name":         (4, 5, 1),
}


# ---------------------------------------------------------------------------
# FR.225 — Opening / Closing Meeting Form
# Table 0: header (company, standards, audit type)
# Table 1: meeting dates row
# Table 2: participants
#   rows 0-1  : "Organization Personnel" header + column labels
#   rows 2-5  : REPLACED by docxtpl {%tr for emp in org_attendees %} loop
#               Each loop row: col0={{ emp.name }}, col1={{ emp.role }},
#               col2=[SIG:ORG_OPENING_{{ emp.sig_key }}],
#               col3=[SIG:ORG_CLOSING_{{ emp.sig_key }}]
#   row 6     : "Audit Team" separator
#   rows 7+   : lead auditor + auditors/TEs (existing Jinja2 rows, unchanged)
# ---------------------------------------------------------------------------
FR225_MAP = {
    "company_name":          (0, 0, 1),
    "standards_str":         (0, 1, 1),
    "audit_type_str":        (0, 1, 3),
    "opening_meeting_date":  (1, 0, 1),    # Table 1 row 0 col 1
    "closing_meeting_date":  (1, 0, 4),    # Table 1 row 0 col 4
    # org_attendees is a list[dict] passed as a docxtpl context variable (not a cell coord):
    # [{"name": str, "role": str, "sig_key": str}, ...]
    # The template loop handles it — no coordinate entry here.
}


# ---------------------------------------------------------------------------
# FR.230 — Nonconformity Notification Form
# Body table is empty rows for NCs; no organisation-info header to populate.
# ---------------------------------------------------------------------------
FR230_MAP: dict = {}


# ---------------------------------------------------------------------------
# FR.231 — Stage 1 Report
# Table 1 row 1 = single cell for organisation info block.
# ---------------------------------------------------------------------------
FR231_MAP = {
    "organisation_block":    (1, 1, 0),
    "scope_en":              (2, 1, 0),
    "plan_number":           (3, 0, 1),    # Report No
    "today_date":            (3, 1, 1),    # Report Date
    "standards_str":         (3, 2, 1),
    "lead_auditor_name":     (3, 3, 1),
    "auditor_1_name":        (3, 4, 1),
    "auditor_2_name":        (3, 5, 1),
    "technical_expert_1_name": (3, 6, 1),
    "observer_1_name":       (3, 9, 1),
    "representative":        (3, 10, 1),
    "audit_dates":           (4, 0, 1),    # Audit Date/s (current stage)
    "audit_days":            (4, 0, 3),    # Audit/Day Number

    # GENERAL section (Table 12)
    "effective_employees":   (12, 3, 1),
    "subcontractor_employees": (12, 2, 1),
    "total_employees":       (12, 1, 1),
}


# ---------------------------------------------------------------------------
# FR.232 — Stage 2 / Audit Report
# Same overall structure as FR.231 with GENERAL in Table 11.
# ---------------------------------------------------------------------------
FR232_MAP = {
    "organisation_block":    (1, 1, 0),
    "scope_en":              (2, 1, 0),
    "plan_number":           (3, 0, 1),
    "today_date":            (3, 1, 1),
    "standards_str":         (3, 2, 1),
    "lead_auditor_name":     (3, 3, 1),
    "auditor_1_name":        (3, 4, 1),
    "auditor_2_name":        (3, 5, 1),
    "technical_expert_1_name": (3, 6, 1),
    "observer_1_name":       (3, 9, 1),
    "representative":        (3, 10, 1),
    "audit_dates":           (4, 0, 1),   # Audit Date/s (current stage — Stage 2 or Surveillance)
    "audit_days":            (4, 0, 3),

    "effective_employees":     (11, 3, 1),
    "subcontractor_employees": (11, 2, 1),
    "total_employees":         (11, 1, 1),
}


# ---------------------------------------------------------------------------
# FR.234 — Surveillance / Recertification Audit Notification Form
# ---------------------------------------------------------------------------
FR234_MAP = {
    "today_date":          (0, 0, 1),
    "plan_number":         (0, 0, 3),
    "company_name":        (0, 1, 1),
    "company_address":     (0, 2, 1),
    "phone":               (0, 3, 1),
    "email":               (0, 3, 3),

    "standards_str":       (2, 0, 1),
    "scope_en":            (3, 0, 1),

    # Detailed organisation block (Table 4)
    "company_name_repeat": (4, 0, 1),
    "company_address_repeat": (4, 1, 1),
    "representative":      (4, 2, 1),
    "scope_repeat":        (4, 3, 1),
    "effective_employees": (4, 5, 1),
    "surveillance_date":   (4, 7, 1),
}


# ---------------------------------------------------------------------------
# FR.211 — Lead Auditor / Auditor Assessment Form
# NOTE: FR.211 is included in the blank set ZIP for the client to fill manually.
# It is NOT auto-generated or uploaded by the system.
# UPLOAD FLOW: Client uploads one filled FR.211 per auditor/TE:
#   - Stage 1 batch: after Cert Manager clicks "Stage 1 appropriate"
#   - Stage 2 batch: after Cert Manager approves certification decision
# VISIBILITY: CB can see; auditors/TEs CANNOT see this document.
# SIGNING: Client signs only (visual signature). No auditor signature.
# ---------------------------------------------------------------------------
FR211_MAP = {
    "lead_auditor_name":     (0, 0, 1),
    "audit_dates":           (0, 1, 1),    # Audit Date/s (current stage)
    "company_name":          (0, 2, 1),
    "standards_str":         (0, 3, 1),
}


# ---------------------------------------------------------------------------
# FR.233 — Review and Decision Form
# Table 0: audit header (14 rows × 4 cols)
# Table 1: scope (2 rows × 1 col)
# Table 2: review checklist — filled manually by reviewer, no pre-fill coords
# Table 3: committee signatures (7 rows × 6 cols)
#   row 1: Chairperson  row 2: Member  row 3: Member
#   row 6: Certification Manager approval
# ---------------------------------------------------------------------------
FR233_MAP = {
    # Table 0 — audit header
    "plan_number":            (0, 0, 1),   # Project Number
    "company_name":           (0, 1, 1),   # Organization
    "company_address":        (0, 2, 1),   # Address
    "standards_str":          (0, 3, 1),   # Standard(s)
    "ea_code":                (0, 4, 1),   # EA/IAF Code / Category / Technical Area
    "audit_team_str":         (0, 6, 1),   # Audit Team (lead auditor + team member names)
    "stage_1_date":           (0, 7, 1),   # Stage 1 Audit Date
    "stage_2_date":           (0, 7, 3),   # Stage 2 / Surveillance / Re-cert Audit Date
    "stage_1_report_date":    (0, 8, 1),   # Stage 1 Report Date
    "stage_2_report_date":    (0, 8, 3),   # Stage 2 / Surveillance Report Date
    "decision_date":          (0, 9, 1),   # Decision Date
    # Table 1 — scope
    "scope_en":               (1, 1, 0),   # Scope value cell (row 1, only column)
    # Table 3 — committee members (name col=1, EA col=3, sign col=5 handled by viewer [SIG:])
    "committee_chair_name":   (3, 1, 1),
    "committee_chair_ea":     (3, 1, 3),
    "committee_member1_name": (3, 2, 1),
    "committee_member1_ea":   (3, 2, 3),
    "committee_member2_name": (3, 3, 1),
    "committee_member2_ea":   (3, 3, 3),
    # Signature slots in Table 3: [SIG:COMMITTEE_CHAIR], [SIG:COMMITTEE_MEMBER_1],
    # [SIG:COMMITTEE_MEMBER_2], [SIG:CERT_MANAGER] — placed by viewer at col 5.
}
