from types import SimpleNamespace

from auditors.qualification_scope import (
    compute_covered_scope,
    matching_qualifications,
    normalize_scope_code,
    normalize_standard,
)


def qualification(
    standard,
    codes=(),
    *,
    body="UAF",
    category=None,
    qualified=True,
):
    return SimpleNamespace(
        standard_code=standard,
        accreditation_body=body,
        ea_codes=list(codes),
        scope_category=category,
        is_qualified=qualified,
    )


def test_standard_and_ea_formats_are_normalized():
    assert normalize_standard("QMS") == normalize_standard("ISO 9001:2015")
    assert normalize_standard("ISO/IEC 27001:2022") == normalize_standard("ISMS")
    assert normalize_scope_code(23, "ea") == normalize_scope_code("EA 23", "ea")
    assert normalize_scope_code("EA23", "ea") == normalize_scope_code("23", "ea")


def test_legacy_scalar_numeric_ea_value_is_accepted():
    legacy = SimpleNamespace(
        standard_code="ISO 9001",
        accreditation_body="UAF",
        ea_codes=23,
        scope_category=None,
        is_qualified=True,
    )

    assert compute_covered_scope(
        [legacy],
        {"ISO 9001": {"type": "ea", "codes": ["EA 23"]}},
        accreditation_body="UAF",
    ) == {"ISO 9001": ["EA 23"]}


def test_all_matching_rows_are_combined_for_requested_body():
    qualifications = [
        qualification("ISO 9001", ["EA 29"], body="TURKAK"),
        qualification("ISO 9001:2015", ["23"], body="UAF"),
        qualification("QMS", ["EA 29"], body="UAF"),
    ]

    covered = compute_covered_scope(
        qualifications,
        {"ISO 9001": {"type": "ea", "codes": ["EA 23", "EA 29"]}},
        accreditation_body="UAF",
    )

    assert covered == {"ISO 9001": ["EA 23", "EA 29"]}
    assert len(
        matching_qualifications(qualifications, "ISO 9001", "UAF")
    ) == 2


def test_different_standard_code_does_not_cover_iso_9001():
    covered = compute_covered_scope(
        [qualification("ISO 14001", ["EA 23"])],
        {"ISO 9001": {"type": "ea", "codes": ["EA 23"]}},
        accreditation_body="UAF",
    )

    assert covered == {}


def test_wrong_accreditation_body_does_not_cover():
    covered = compute_covered_scope(
        [qualification("ISO 9001", ["EA 23"], body="TURKAK")],
        {"ISO 9001": {"type": "ea", "codes": ["EA 23"]}},
        accreditation_body="UAF",
    )

    assert covered == {}


def test_integrated_standards_are_evaluated_independently():
    qualifications = [
        qualification("ISO 9001", ["EA 23"]),
        qualification("ISO 14001", ["EA 29"]),
    ]
    required = {
        "ISO 9001": {"type": "ea", "codes": ["23", "29"]},
        "ISO 14001": {"type": "ea", "codes": ["23", "29"]},
    }

    assert compute_covered_scope(
        qualifications,
        required,
        accreditation_body="UAF",
    ) == {
        "ISO 9001": ["23"],
        "ISO 14001": ["29"],
    }


def test_missing_per_standard_codes_are_not_silently_unrestricted():
    covered = compute_covered_scope(
        [qualification("ISO 9001", [])],
        {"ISO 9001": {"type": "ea", "codes": ["EA 23"]}},
        accreditation_body="UAF",
    )

    assert covered == {}


def test_unambiguous_legacy_global_codes_remain_compatible():
    covered = compute_covered_scope(
        [qualification("QMS", [], body=None)],
        {"ISO 9001:2015": {"type": "ea", "codes": ["EA 23"]}},
        accreditation_body="UAF",
        legacy_ea_codes=[23],
        legacy_accreditation_bodies=["UAF"],
    )

    assert covered == {"ISO 9001:2015": ["EA 23"]}


def test_ambiguous_legacy_global_codes_do_not_cross_standards():
    qualifications = [
        qualification("ISO 9001", [], body=None),
        qualification("ISO 14001", [], body=None),
    ]
    required = {
        "ISO 9001": {"type": "ea", "codes": ["EA 23"]},
        "ISO 14001": {"type": "ea", "codes": ["EA 23"]},
    }

    covered = compute_covered_scope(
        qualifications,
        required,
        accreditation_body="UAF",
        legacy_ea_codes=["EA 23"],
        legacy_accreditation_bodies=["UAF"],
    )

    assert covered == {}


def test_category_codes_use_exact_case_and_spacing_normalization():
    covered = compute_covered_scope(
        [qualification("ISO 22000", category="C I, C IV")],
        {"ISO 22000": {"type": "food", "codes": ["CI", "CIV", "D"]}},
        accreditation_body="UAF",
    )

    assert covered == {"ISO 22000": ["CI", "CIV"]}
