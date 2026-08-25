from __future__ import annotations

import pytest

from calculator.engine import _eps_standard, _lookup_standard, calculate
from calculator.models import ExtractedFormData


def _food_form(**updates) -> ExtractedFormData:
    values = {
        "org_name": "Döner Factory",
        "standards": ["ISO 22000:2018"],
        "scope": "Manufacture of döner meat and prepared ready-to-eat products",
        "total_employees": 14,
        "office_employees": 2,
        "repetitive_employees": 10,
        "food_chain_categories": ["CI", "CIII"],
        "haccp_studies": 3,
    }
    values.update(updates)
    return ExtractedFormData(**values)


def test_doner_factory_uses_normative_td_th_tfte_formula():
    data = _food_form()
    result = _lookup_standard(data, "ISO 22000:2018")

    assert result.eps == 14
    assert result.fsms_category_codes == ["CI", "CIII"]
    assert result.fsms_basic_duration == 2.0
    assert result.haccp_addition == 1.0
    assert result.fsms_fte_addition == 0.5
    assert result.base_init == 3.5
    assert result.base_ph1 == 1.0
    assert result.base_ph2 == 2.5


def test_iso22000_total_is_not_reduced_for_reporting():
    result = calculate(_food_form())

    assert result.combined_base == 3.5
    assert result.reporting_reduction == 0
    assert result.final_total == 3.5
    assert result.final_ph1 == 1.0
    assert result.final_ph2 == 2.5


def test_first_haccp_study_is_included_in_td():
    result = _lookup_standard(
        _food_form(food_chain_categories=["CI"], haccp_studies=1),
        "ISO 22000",
    )

    assert result.fsms_basic_duration == 2.0
    assert result.haccp_addition == 0.0
    assert result.fsms_fte_addition == 0.5
    assert result.base_init == 2.5


def test_multiple_categories_use_highest_td_and_th():
    result = _lookup_standard(
        _food_form(
            total_employees=4,
            food_chain_categories=["AI", "G", "K"],
            haccp_studies=2,
        ),
        "ISO 22000",
    )

    assert result.fsms_basic_duration == 2.0
    assert result.haccp_addition == 0.5
    assert result.fsms_fte_addition == 0.0
    assert result.base_init == 2.5


def test_food_safety_fte_does_not_use_md5_repetitive_worker_reduction():
    data = _food_form(total_employees=49, office_employees=0, repetitive_employees=49)
    assert _eps_standard(data, "ISO 22000") == 49


def test_category_must_be_confirmed_before_calculation():
    with pytest.raises(ValueError, match="must be determined and confirmed"):
        _lookup_standard(_food_form(food_chain_categories=[]), "ISO 22000")
