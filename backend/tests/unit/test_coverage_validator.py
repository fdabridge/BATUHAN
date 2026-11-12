from types import SimpleNamespace

from assembly import coverage_validator
from assembly.coverage_validator import validate_and_repair_coverage


def _scope_analysis(*clause_ids):
    return SimpleNamespace(
        standards={
            "QMS": SimpleNamespace(applicable_clause_ids=list(clause_ids)),
        }
    )


def test_validate_and_repair_coverage_adds_repaired_cells(monkeypatch):
    structure = "\n".join(
        [
            "TABLE 1",
            "  T1_R1_C1: Clause [LABEL — DO NOT MODIFY]",
            "  T1_R1_C2: Findings [LABEL — DO NOT MODIFY]",
            "  T1_R2_C1: 4.1 Context of the organisation [LABEL — DO NOT MODIFY]",
            "  T1_R2_C2: [EMPTY]",
        ]
    )

    def fake_repair_clause_cells(**kwargs):
        return {"T1_R2_C2": "Evidence confirms the organisation understands internal and external issues."}

    monkeypatch.setattr(coverage_validator, "_repair_clause_cells", fake_repair_clause_cells)

    mapping, report = validate_and_repair_coverage(
        cell_mapping={},
        template_structure_text=structure,
        scope_analysis=_scope_analysis("4.1"),
        report_content="report content",
        client=object(),
        model="test-model",
        max_tokens=100,
        temperature=0,
        selected_standards=["QMS"],
    )

    assert mapping["T1_R2_C2"].startswith("Evidence confirms")
    assert any("Coverage repair verified" in line for line in report)


def test_validate_and_repair_coverage_reports_remaining_empty_cells(monkeypatch):
    structure = "\n".join(
        [
            "TABLE 1",
            "  T1_R1_C1: Clause [LABEL — DO NOT MODIFY]",
            "  T1_R1_C2: Findings [LABEL — DO NOT MODIFY]",
            "  T1_R2_C1: 4.1 Context of the organisation [LABEL — DO NOT MODIFY]",
            "  T1_R2_C2: [EMPTY]",
        ]
    )

    monkeypatch.setattr(coverage_validator, "_repair_clause_cells", lambda **kwargs: {})

    mapping, report = validate_and_repair_coverage(
        cell_mapping={},
        template_structure_text=structure,
        scope_analysis=_scope_analysis("4.1"),
        report_content="report content",
        client=object(),
        model="test-model",
        max_tokens=100,
        temperature=0,
        selected_standards=["QMS"],
    )

    assert mapping == {}
    assert any("Coverage repair incomplete" in line for line in report)
    assert any("T1_R2_C2" in line for line in report)


def test_integrated_coverage_repairs_same_clause_per_standard_without_cross_contamination(monkeypatch):
    structure = "\n".join(
        [
            "TABLE 1 [SELECTED STANDARD — ISO 9001 Quality Management System] [STANDARD_CODE=QMS]",
            "  T1_R1_C1: Requirements [LABEL — DO NOT MODIFY]",
            "  T1_R1_C2: Findings [LABEL — DO NOT MODIFY]",
            "  T1_R1_C3: Conclusion [LABEL — DO NOT MODIFY]",
            "  T1_R2_C1: 4.1 Context of the organisation [LABEL — DO NOT MODIFY]",
            "  T1_R2_C2: [EMPTY]",
            "  T1_R2_C3: [EMPTY]",
            "TABLE 2 [SELECTED STANDARD — ISO 14001 Environmental Management System] [STANDARD_CODE=EMS]",
            "  T2_R1_C1: Requirements [LABEL — DO NOT MODIFY]",
            "  T2_R1_C2: Findings [LABEL — DO NOT MODIFY]",
            "  T2_R1_C3: Conclusion [LABEL — DO NOT MODIFY]",
            "  T2_R2_C1: 4.1 Context of the organisation [LABEL — DO NOT MODIFY]",
            "  T2_R2_C2: [EMPTY]",
            "  T2_R2_C3: [EMPTY]",
        ]
    )
    scope = SimpleNamespace(
        standards={
            "QMS": SimpleNamespace(applicable_clause_ids=["4.1"]),
            "EMS": SimpleNamespace(applicable_clause_ids=["4.1"]),
        }
    )
    calls = []

    def fake_repair_clause_cells(**kwargs):
        calls.append(kwargs)
        coordinate = kwargs["coords"][0]
        return {coordinate: f"{kwargs['standard_code']} evidence for clause 4.1"}

    monkeypatch.setattr(coverage_validator, "_repair_clause_cells", fake_repair_clause_cells)

    mapping, _report = validate_and_repair_coverage(
        cell_mapping={},
        template_structure_text=structure,
        scope_analysis=scope,
        report_content="integrated report content",
        client=object(),
        model="test-model",
        max_tokens=100,
        temperature=0,
        selected_standards=["QMS", "EMS"],
    )

    assert mapping == {
        "T2_R2_C2": "EMS evidence for clause 4.1",
        "T1_R2_C2": "QMS evidence for clause 4.1",
    }
    assert {call["standard_code"] for call in calls} == {"QMS", "EMS"}
    assert all(call["coords"][0].endswith("_C2") for call in calls)
