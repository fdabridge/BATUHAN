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
