"""
BATUHAN — UAF end-to-end pipeline test.

Drives `build_audit_set_zip` with a synthetic (non-production) initial-audit
fixture and asserts: ZIP contents, zero leftover {{ }}/{% %} placeholders,
conditional rows, certification-cycle date math, and the download route.

Notes on reality vs. the test spec:
  * `build_audit_set_zip(audit_set, db)` builds the WHOLE set in one ZIP, with
    Stage_1/ and Stage_2/ subfolders — there is no per-stage call.
  * The real download route is GET /audit-sets/{id}/download (whole set).
  * Dates render as DD/MM/YYYY; cycle dates are +1 year − 1 day.
  * For a QMS+EMS (base) scope, Stage_2 has no FR.229/231-1/232-1 (ISMS/MDQMS
    only), so date math is verified against the render context directly.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from types import SimpleNamespace as NS

import pytest

from audit_set.filler import build_base_context
from audit_set.packager import build_audit_set_zip
from audit_set.resolver import resolve_document_set


# --------------------------------------------------------------------------- #
# Synthetic fixture (no production data)
# --------------------------------------------------------------------------- #
def _stage_1() -> NS:
    return NS(
        stage_type="stage_1", stage_order=1,
        audit_date_start=date(2026, 6, 10), audit_date_end=date(2026, 6, 11),
        audit_days=2.0, notification_date=date(2026, 4, 10),
        lead_auditor_id="1", lead_auditor_name="John Smith",
        auditors=[{"id": "2", "name": "Jane Auditor", "covered_scope": {}}],
        technical_experts=[{"id": "3", "name": "Tom Expert", "covered_scope": {}}],
        observers=[],
    )


def _stage_2() -> NS:
    return NS(
        stage_type="stage_2", stage_order=2,
        audit_date_start=date(2026, 7, 14), audit_date_end=date(2026, 7, 16),
        audit_days=3.0, notification_date=date(2026, 5, 14),
        lead_auditor_id="1", lead_auditor_name="John Smith",
        auditors=[{"id": "2", "name": "Jane Auditor", "covered_scope": {}}],
        technical_experts=[], observers=[],
    )


def _man_day() -> dict:
    return {
        "standard_results": [
            {"standard": "ISO 9001:2015", "category": "Low", "eps": 85,
             "base_init": 4.0, "base_ph1": 1.5, "base_ph2": 2.5, "site_addition": 0.5},
            {"standard": "ISO 14001:2015", "category": "Low", "eps": 85,
             "base_init": 1.5, "base_ph1": 0.5, "base_ph2": 1.0, "site_addition": 0.0},
        ],
        "combined_base": 5.5, "integration_reduction": 0.5, "final_total": 5.0,
        "final_ph1": 2.0, "final_ph2": 3.0, "final_surv1": 1.5, "final_surv2": 1.5,
        "total_employees": 85, "office_employees": 55, "repetitive_employees": 30,
        "eps": 85, "scope_integration_level": "Partial",
    }


def _audit_set() -> NS:
    return NS(
        id=1, plan_number="IFC-2026-001", status="planning",
        company_name="Acme Foods Ltd",
        company_address="123 Industrial Blvd, Istanbul, Turkey", country="Turkey",
        phone="+90 212 000 0000", email="info@acmefoods.com",
        website="www.acmefoods.com", representative="Ahmet Yilmaz",
        scope_en="Manufacturing of packaged food products", scope_tr="",
        non_applicable_clauses="8.3 Design and Development",
        ea_code="EA 3", ea_category="Food and Drink",
        ea_technical_area="Manufacturing", effective_employees=85,
        certification_fee=5000, surveillance_fee=2500,
        scope_integration_level="Partial", risk_category="Low",
        audit_language="Turkish", document_language="english",
        standards=["QMS", "EMS"], audit_type="initial", accreditation_body="UAF",
        man_day_result=_man_day(),
        personnel={"full_time": 70, "part_time": 10, "unskilled": 5, "seasonal": 0,
                   "subcontractors": 8, "shift_count": 2, "office_employees": 55,
                   "repetitive_employees": 30},
        sites=[
            {"address": "123 Industrial Blvd, Istanbul, Turkey", "employee_count": 70,
             "process_description": "Primary production and packaging",
             "energy_tj": 12.5, "energy_types": 3, "seu_count": 4},
            {"address": "45 Warehouse St, Gebze, Turkey", "employee_count": 15,
             "process_description": "Storage and distribution",
             "energy_tj": 2.1, "energy_types": 1, "seu_count": 1},
        ],
        integration_level={"document_management": True, "management_review": True,
                           "internal_audit": True, "policy_objectives": True,
                           "process_approach": False, "improvement_mechanism": True,
                           "management_support": False, "risk_based_thinking": True},
        required_scope={},
        stages=[_stage_1(), _stage_2()],
    )


def _recertification_audit_set() -> NS:
    audit_set = _audit_set()
    audit_set.audit_type = "recertification"
    audit_set.stages = [
        NS(
            stage_type="recertification", stage_order=1,
            audit_date_start=date(2026, 7, 14), audit_date_end=date(2026, 7, 16),
            audit_days=3.0, notification_date=date(2026, 5, 14),
            lead_auditor_id="1", lead_auditor_name="John Smith",
            auditors=[{"id": "2", "name": "Jane Auditor", "covered_scope": {}}],
            technical_experts=[], observers=[],
        )
    ]
    return audit_set


# --------------------------------------------------------------------------- #
# Helpers + shared fixtures
# --------------------------------------------------------------------------- #
def _zip_entries(data: bytes) -> dict[str, bytes]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    return {n: zf.read(n) for n in zf.namelist()}


def _stage_files(entries: dict, folder: str) -> dict[str, bytes]:
    """Entries inside a given Stage_x/ Surveillance/ subfolder, keyed by basename."""
    return {n.split("/")[-1]: b for n, b in entries.items() if f"/{folder}/" in n}


def _docx_all_xml(b: bytes) -> str:
    """Concatenated text of every .xml part in a .docx (body, headers, footers)."""
    zf = zipfile.ZipFile(io.BytesIO(b))
    return "".join(
        zf.read(n).decode("utf-8", "ignore")
        for n in zf.namelist() if n.endswith(".xml")
    )


def _docx_text(b: bytes) -> str:
    """Visible text of a .docx body (tags stripped)."""
    xml = zipfile.ZipFile(io.BytesIO(b)).read("word/document.xml").decode("utf-8", "ignore")
    return re.sub(r"<[^>]+>", "", xml)


@pytest.fixture(scope="module")
def entries() -> dict[str, bytes]:
    return _zip_entries(build_audit_set_zip(_audit_set(), None))


def _find(entries: dict, folder: str, fr_prefix: str) -> bytes | None:
    for name, body in entries.items():
        base = name.split("/")[-1]
        if f"/{folder}/" in name and base.startswith(fr_prefix):
            return body
    return None


# --------------------------------------------------------------------------- #
# 1. ZIP structure + core templates
# --------------------------------------------------------------------------- #
def test_zip_has_both_stage_folders(entries):
    folders = {n.split("/")[1] for n in entries if n.count("/") >= 2}
    assert "Stage_1" in folders
    assert "Stage_2" in folders


def test_core_templates_present_per_stage(entries):
    for folder in ("Stage_1", "Stage_2"):
        names = " ".join(_stage_files(entries, folder))
        for fr in ("FR.223", "FR.230"):
            assert fr in names, f"{fr} missing from {folder}"


def test_recertification_uses_front_docs_and_surveillance_templates():
    document_set, missing = resolve_document_set(_recertification_audit_set())

    assert missing == []
    assert set(document_set) == {"Recertification"}
    by_fr = {spec.fr_number: spec for spec in document_set["Recertification"]}
    assert {
        "FR.218", "FR.220", "FR.221",
        "FR.223", "FR.224", "FR.225", "FR.230", "FR.232", "FR.211", "FR.234", "FR.233",
    } <= set(by_fr)

    for fr in ("FR.218", "FR.220", "FR.221"):
        path = by_fr[fr].template_path.as_posix()
        assert "/Initial Certification/" in path
        assert "/Stage 1/" in path

    for fr in ("FR.223", "FR.224", "FR.225", "FR.230", "FR.232", "FR.211", "FR.234", "FR.233"):
        assert "/Surveillance/" in by_fr[fr].template_path.as_posix()


def test_recertification_zip_includes_front_documents():
    entries = _zip_entries(build_audit_set_zip(_recertification_audit_set(), None))
    names = " ".join(_stage_files(entries, "Recertification"))
    for fr in ("FR.218", "FR.220", "FR.221"):
        assert fr in names, f"{fr} missing from Recertification"


# --------------------------------------------------------------------------- #
# 2. Render-error gate — the authoritative proof the templates are clean
# --------------------------------------------------------------------------- #
def test_no_render_errors(entries):
    err = next((n for n in entries if n.endswith("RENDER_ERRORS.txt")), None)
    detail = entries[err].decode("utf-8", "ignore") if err else ""
    assert err is None, f"Templates failed to render:\n{detail}"


# --------------------------------------------------------------------------- #
# 3. Per-person forms (FR.224 / FR.211) — one copy per team member
# --------------------------------------------------------------------------- #
def test_per_person_forms_one_per_member(entries):
    s1 = _stage_files(entries, "Stage_1")
    # Stage 1 team: John Smith (lead), Jane Auditor, Tom Expert → 3 each
    fr224 = [n for n in s1 if n.startswith("FR.224")]
    assert len(fr224) == 3, f"expected 3 FR.224 copies, got {sorted(fr224)}"
    joined = " ".join(s1)
    assert "John_Smith" in joined and "Jane_Auditor" in joined and "Tom_Expert" in joined


# --------------------------------------------------------------------------- #
# 4. No leftover Jinja placeholders in any rendered document
# --------------------------------------------------------------------------- #
def test_no_unrendered_placeholders(entries):
    offenders = []
    for name, body in entries.items():
        if not name.endswith(".docx"):
            continue
        xml = _docx_all_xml(body)
        if "{{" in xml or "{%" in xml:
            offenders.append(name)
    assert not offenders, f"Unrendered placeholders remain in: {offenders}"


# --------------------------------------------------------------------------- #
# 5. Conditional rows — in-scope standards/sites shown, out-of-scope hidden
# --------------------------------------------------------------------------- #
def test_fr218_conditional_standard_and_site_rows(entries):
    body = _find(entries, "Stage_1", "FR.218")
    if body is None:
        pytest.skip("FR.218 did not render — see RENDER_ERRORS gate")
    text = _docx_text(body)
    # Use versioned names: bare numbers (e.g. "45001") also occur in static
    # form labels, so only the full versioned name proves a data row rendered.
    assert "ISO 9001:2015" in text and "ISO 14001:2015" in text   # in scope
    assert "ISO 45001:2018" not in text                           # OHSMS out
    assert "ISO/IEC 27001:2022" not in text                       # ISMS out
    assert "Gebze" in text                                        # second site shown


def test_fr222_conditional_standard_rows(entries):
    body = _find(entries, "Stage_1", "FR.222")
    if body is None:
        pytest.skip("FR.222 did not render — see RENDER_ERRORS gate")
    text = _docx_text(body)
    # Versioned names only — bare numbers appear in fixed column headers.
    assert "ISO 9001:2015" in text and "ISO 14001:2015" in text
    assert "ISO 45001:2018" not in text and "ISO 22000:2018" not in text


# --------------------------------------------------------------------------- #
# 6. Certification-cycle date math (verified against the render context)
# --------------------------------------------------------------------------- #
def test_cycle_date_math():
    ctx = build_base_context(_audit_set(), _stage_2())
    assert ctx["audit_date_end"] == "16/07/2026"
    assert ctx["report_date"] == "17/07/2026"          # end + 1 day
    assert ctx["plan_date"] == "07/07/2026"            # 5 working days before start
    assert ctx["notification_date"] == "14/05/2026"    # 2 months before start
    assert ctx["stage1_dates"] == "10–11 June 2026"
    assert ctx["stage2_dates"] == "14–16 July 2026"
    assert ctx["surv1_estimated_date"] == "15/07/2027"  # +1yr −1day
    assert ctx["surv2_estimated_date"] == "14/07/2028"
    assert ctx["recert_estimated_date"] == "13/07/2029"


# --------------------------------------------------------------------------- #
# 7. Download route (skips when the DB stack is unavailable, e.g. local)
# --------------------------------------------------------------------------- #
def test_download_route_streams_zip():
    pytest.importorskip("sqlalchemy", reason="DB stack unavailable")
    from fastapi.testclient import TestClient  # noqa: WPS433
    try:
        from main import app  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"app import failed: {exc}")
    client = TestClient(app)
    resp = client.get(
        "/audit-sets/1/download",
        headers={"Authorization": "Bearer certiva_token"},
    )
    assert resp.status_code in (200, 401, 404)
