from __future__ import annotations

import pytest
from pydantic import ValidationError

from calculator.advanced import (
    AdvancedCalculationRequest,
    AdvancedSiteInput,
    IntegrationProfile,
    MultiSiteEligibility,
    calculate_advanced,
)


def _request(**updates) -> AdvancedCalculationRequest:
    values = {
        "organization_name": "Independent Example",
        "scope": "Design and development of cloud software and cybersecurity services",
        "standards": ["QMS"],
        "full_time_personnel": 50,
        "office_personnel": 50,
    }
    values.update(updates)
    return AdvancedCalculationRequest(**values)


def test_scope_drives_ea_category_and_uses_backend_table_without_reporting_cut():
    result = calculate_advanced(_request())

    qms = result.classifications[0]
    assert qms.codes == ["EA 33"]
    assert qms.code_names == ["Information technology"]
    assert qms.category == "Low"
    assert result.base_time == 4.0
    assert result.final_audit_time == 4.0
    assert result.md5_adjustment_days == 0
    assert result.md11_reduction_days == 0


def test_manual_ea_and_category_override_take_precedence():
    result = calculate_advanced(_request(
        manual_ea_codes=["EA 12"],
        category_overrides={"QMS": "High"},
    ))

    qms = result.classifications[0]
    assert qms.codes == ["EA 12"]
    assert qms.category == "High"
    assert qms.source == "manual category override"


def test_md1_initial_sample_uses_square_root_and_requires_eligibility():
    sites = [
        AdvancedSiteInput(
            id=f"site-{index}",
            name=f"Branch {index}",
            employee_count=10 + index,
        )
        for index in range(1, 10)
    ]
    eligibility = MultiSiteEligibility(
        single_management_system=True,
        central_function_identified=True,
        centralized_management_review=True,
        centralized_internal_audit=True,
        similar_processes=True,
    )
    result = calculate_advanced(_request(
        sites=sites,
        multi_site_sampling_requested=True,
        multi_site_eligibility=eligibility,
    ))

    assert result.multi_site_plan.sampling_permitted is True
    assert result.multi_site_plan.eligible_sites == 9
    assert result.multi_site_plan.required_sample_size == 3
    assert result.multi_site_plan.audited_additional_sites == 3
    assert result.multi_site_plan.minimum_random_sites == 1
    assert result.multi_site_plan.formula == "ceil(√eligible sites)"


def test_md1_ineligible_multi_site_request_includes_every_site():
    sites = [
        AdvancedSiteInput(id=f"site-{index}", employee_count=10)
        for index in range(1, 5)
    ]
    result = calculate_advanced(_request(
        sites=sites,
        multi_site_sampling_requested=True,
    ))

    assert result.multi_site_plan.sampling_permitted is False
    assert result.multi_site_plan.audited_additional_sites == 4
    assert any("every site was included" in warning for warning in result.warnings)


def test_md11_full_integration_is_matrix_based_and_capped_at_twenty_percent():
    integration = IntegrationProfile(
        enabled=True,
        integrated_documentation=True,
        integrated_management_review=True,
        integrated_internal_audits=True,
        integrated_policy_objectives=True,
        integrated_processes=True,
        integrated_improvement=True,
        integrated_responsibilities=True,
        combined_audit_capability_pct=100,
    )
    result = calculate_advanced(_request(
        standards=["QMS", "EMS"],
        integration=integration,
    ))

    assert result.integration_level_pct == 100
    assert result.md11_reduction_pct == 20
    assert result.md11_reduction_days == round(result.after_md5_adjustment * 0.20, 2)


def test_md5_reduction_requires_documented_justification():
    with pytest.raises(ValidationError, match="documented justification"):
        _request(md5_adjustment_pct=-10)


@pytest.mark.parametrize(
    ("audit_type", "mature_system", "expected_sample"),
    [
        ("surveillance", False, 3),
        ("recertification", False, 5),
        ("recertification", True, 4),
    ],
)
def test_md1_sample_formulas_by_audit_type(
    audit_type: str,
    mature_system: bool,
    expected_sample: int,
):
    sites = [
        AdvancedSiteInput(
            id=f"site-{index}",
            name=f"Branch {index}",
            employee_count=10,
        )
        for index in range(1, 26)
    ]
    eligibility = MultiSiteEligibility(
        single_management_system=True,
        central_function_identified=True,
        centralized_management_review=True,
        centralized_internal_audit=True,
        similar_processes=True,
    )

    result = calculate_advanced(_request(
        sites=sites,
        audit_type=audit_type,
        mature_management_system=mature_system,
        multi_site_sampling_requested=True,
        multi_site_eligibility=eligibility,
    ))

    assert result.multi_site_plan.required_sample_size == expected_sample
    assert result.multi_site_plan.minimum_random_sites >= 1


def test_effective_personnel_and_remote_share_do_not_reduce_total_time():
    values = {
        "full_time_personnel": 10,
        "part_time_personnel": 10,
        "part_time_hours_per_day": 4,
        "normal_hours_per_day": 8,
        "subcontractors": 3,
        "subcontractors_in_scope": True,
        "seasonal_temporary_personnel": 2,
    }
    result = calculate_advanced(_request(remote_audit_pct=20, **values))
    without_remote = calculate_advanced(_request(remote_audit_pct=0, **values))

    assert result.effective_personnel == 20
    assert result.remote_time == pytest.approx(result.final_audit_time * 0.2)
    assert result.on_site_time + result.remote_time == pytest.approx(result.final_audit_time)
    assert result.final_audit_time == without_remote.final_audit_time


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("md5_adjustment_pct", -31),
        ("remote_audit_pct", 21),
        ("sampled_site_reduction_pct", 51),
    ],
)
def test_compliance_caps_are_validated(field: str, value: int):
    with pytest.raises(ValidationError):
        _request(**{field: value})
