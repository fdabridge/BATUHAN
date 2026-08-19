from audit_set.scope_fields import (
    ea_code_from_required_scope,
    effective_ea_code,
)
from audit_set.service import derive_required_scope
from audit_set.committee_router import _merge_isms_application_scope


def test_revised_scope_code_overrides_initial_legacy_code():
    required_scope = {
        "ISO 9001:2015": {
            "type": "ea",
            "codes": ["EA 17"],
            "risk": "Medium",
        },
    }

    assert effective_ea_code(required_scope, "EA 2") == "EA 17"


def test_multiple_scope_codes_are_normalised_and_deduplicated():
    required_scope = {
        "ISO 9001:2015": {"type": "ea", "codes": ["2", "EA 17"]},
        "ISO 14001:2015": {"type": "ea_codes", "codes": ["IAF 17", "EA 28"]},
    }

    assert ea_code_from_required_scope(required_scope) == "EA 2, EA 17, EA 28"


def test_explicitly_cleared_ea_scope_does_not_restore_stale_code():
    required_scope = {
        "ISO 9001:2015": {"type": "ea", "codes": []},
    }

    assert ea_code_from_required_scope(required_scope) == ""
    assert effective_ea_code(required_scope, "EA 2") == ""


def test_non_ea_scope_keeps_legacy_fallback_for_older_records():
    required_scope = {
        "ISO 13485:2016": {"type": "medical", "codes": ["MD9"]},
    }

    assert ea_code_from_required_scope(required_scope) is None
    assert effective_ea_code(required_scope, "EA 2") == "EA 2"


def test_iso27001_scope_preserves_multiple_selected_categories():
    required_scope = derive_required_scope(
        standards=["ISMS"],
        scope_tr=None,
        scope_en="Industrial cloud and telecom services",
        ea_code=None,
        application_data={"isms_technical_areas": ["A", "B", "C", "B"]},
    )

    assert required_scope["ISO 27001"] == {
        "type": "isms",
        "codes": ["A", "B", "C"],
    }


def test_iso27001_legacy_single_category_remains_supported():
    required_scope = derive_required_scope(
        standards=["ISMS"],
        scope_tr=None,
        scope_en="Information security management",
        ea_code=None,
        application_data={"isms_technical_area": "D"},
    )

    assert required_scope["ISO 27001"]["codes"] == ["D"]


def test_committee_keeps_planner_edited_multiple_isms_categories():
    required_scope = {
        "ISO 27001": {"type": "isms", "codes": ["A", "C"]},
    }

    merged = _merge_isms_application_scope(
        required_scope,
        {"ISO 27001"},
        {"isms_technical_area": "A"},
    )

    assert merged["ISO 27001"]["codes"] == ["A", "C"]


def test_committee_repairs_legacy_isms_scope_from_multiple_categories():
    merged = _merge_isms_application_scope(
        {"ISO 27001": {"type": "ea", "codes": ["EA 33"]}},
        {"ISO 27001"},
        {"isms_technical_areas": ["B", "D", "B"]},
    )

    assert merged["ISO 27001"] == {"type": "isms", "codes": ["B", "D"]}
