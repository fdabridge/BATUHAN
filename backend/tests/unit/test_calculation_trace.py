from calculator.engine import calculate
from calculator.models import ExtractedFormData, SiteInfo, StandardClassification


def test_calculation_exposes_auditable_steps_and_site_breakdown():
    result = calculate(ExtractedFormData(
        org_name="Example",
        standards=["ISO 9001", "ISO 14001"],
        scope="Manufacturing of metal components",
        total_employees=40,
        office_employees=10,
        repetitive_employees=15,
        classifications=[
            StandardClassification(standard="ISO 9001", sector_name="Metal", category="High"),
            StandardClassification(standard="ISO 14001", sector_name="Metal", category="High"),
        ],
        sites=[SiteInfo(name="Plant 2", address="200 Factory Road", employee_count=12)],
        scope_integration_level="Medium",
    ))

    assert [step.step for step in result.calculation_trace] == [
        "Individual standards and additional sites",
        "Integrated audit adjustment",
        "Preparation and reporting treatment",
        "Controlled rounding",
    ]
    assert result.calculation_trace[-1].result_days == result.final_total
    assert result.site_breakdown[0].name == "Plant 2"
    assert result.site_breakdown[0].total_days > 0
    assert set(result.site_breakdown[0].standard_days) == {"ISO 9001", "ISO 14001"}
