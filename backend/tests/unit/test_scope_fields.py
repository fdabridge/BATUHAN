from audit_set.scope_fields import (
    ea_code_from_required_scope,
    effective_ea_code,
)


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
