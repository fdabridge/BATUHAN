"""
BATUHAN — Unit Tests: Step C Validation & Correction
Tests pre_validator, response_parser, and post_validator
without any real API calls.
"""

import pytest
from backend.schemas.models import (
    ISOStandard, AuditStage,
    TemplateSection, TemplateMap, StyleGuidance,
    GeneratedReport, ReportSection,
    ValidatedReport, CorrectionLog, CorrectionEntry,
)
from backend.pipeline.step_c.pre_validator import (
    run_pre_validation, format_issues_for_prompt,
    format_report_for_prompt, PreValidationIssue,
)
from backend.pipeline.step_c.response_parser import (
    parse_validation_output, _split_top_level, _parse_corrections,
)
from backend.pipeline.step_c.post_validator import (
    run_post_validation, PostValidationError,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TEMPLATE_MAP = TemplateMap(
    source_path="template.docx",
    sections=[
        TemplateSection(title="Introduction and Scope", order_index=0),
        TemplateSection(title="Documented Information Review", order_index=1),
        TemplateSection(title="Key Findings", order_index=2),
    ],
)

STYLE_GUIDANCE = StyleGuidance(
    blocked_company_names=["SampleCorp", "ExampleLtd"],
    blocked_phrases=["SampleCorp achieved certification in 2022"],
)

CLEAN_REPORT = GeneratedReport(
    job_id="job-c-1",
    standard=ISOStandard.QMS,
    stage=AuditStage.STAGE_1,
    sections=[
        ReportSection(title="Introduction and Scope", content="The audit covered the main site.", order_index=0),
        ReportSection(title="Documented Information Review", content="The QMS documentation was reviewed.", order_index=1),
        ReportSection(title="Key Findings", content="The processes are generally conforming.", order_index=2),
    ],
    raw_output="raw",
)

VALID_PROMPT_C_OUTPUT = """
## Final Corrected Report

Section Title:
Introduction and Scope

Content:
The audit was conducted at the organisation's primary site. The scope covers manufacture of components.

---

Section Title:
Documented Information Review

Content:
The organisation maintains a Quality Manual and supporting SOPs. Limited documented evidence was observed
for some supplementary procedures.

---

Section Title:
Key Findings

Content:
The audit team observed conformance with the majority of requirements. Corrective actions are maintained.

---

## List of Corrections Made

- [Introduction and Scope] Removed placeholder text and added factual scope statement.
- No corrections required for Key Findings.
"""

NO_CORRECTIONS_OUTPUT = """
## Final Corrected Report

Section Title:
Introduction and Scope

Content:
Audit conducted at primary facility.

---

## List of Corrections Made

- No corrections required.
"""

# ---------------------------------------------------------------------------
# Tests: pre_validator (T20)
# ---------------------------------------------------------------------------

def test_pre_validation_passes_clean_report():
    issues = run_pre_validation(CLEAN_REPORT, TEMPLATE_MAP, STYLE_GUIDANCE)
    assert issues == []

def test_pre_validation_detects_missing_section():
    partial = GeneratedReport(
        job_id="j", standard=ISOStandard.QMS, stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="Content A", order_index=0),
            ReportSection(title="Key Findings", content="Content C", order_index=2),
        ],
        raw_output="raw",
    )
    issues = run_pre_validation(partial, TEMPLATE_MAP, STYLE_GUIDANCE)
    codes = [i.code for i in issues]
    assert "MISSING_SECTION" in codes

def test_pre_validation_detects_empty_content():
    report = GeneratedReport(
        job_id="j", standard=ISOStandard.QMS, stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="", order_index=0),
            ReportSection(title="Documented Information Review", content="Content", order_index=1),
            ReportSection(title="Key Findings", content="Content C", order_index=2),
        ],
        raw_output="raw",
    )
    issues = run_pre_validation(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    codes = [i.code for i in issues]
    assert "EMPTY_CONTENT" in codes

def test_pre_validation_detects_placeholder():
    report = GeneratedReport(
        job_id="j", standard=ISOStandard.QMS, stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="[INSERT COMPANY NAME HERE]", order_index=0),
            ReportSection(title="Documented Information Review", content="Fine.", order_index=1),
            ReportSection(title="Key Findings", content="Fine.", order_index=2),
        ],
        raw_output="raw",
    )
    issues = run_pre_validation(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    codes = [i.code for i in issues]
    assert "PLACEHOLDER_PRESENT" in codes

def test_pre_validation_detects_sample_leakage():
    report = GeneratedReport(
        job_id="j", standard=ISOStandard.QMS, stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="SampleCorp is the auditee.", order_index=0),
            ReportSection(title="Documented Information Review", content="Fine.", order_index=1),
            ReportSection(title="Key Findings", content="Fine.", order_index=2),
        ],
        raw_output="raw",
    )
    issues = run_pre_validation(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    codes = [i.code for i in issues]
    assert "SAMPLE_LEAKAGE" in codes

def test_format_issues_for_prompt_no_issues():
    text = format_issues_for_prompt([])
    assert "no issues" in text.lower()

def test_format_issues_for_prompt_with_issues():
    issues = [PreValidationIssue("Intro", "PLACEHOLDER_PRESENT", "Has placeholder.")]
    text = format_issues_for_prompt(issues)
    assert "1 issue" in text
    assert "PLACEHOLDER_PRESENT" in text

def test_format_report_for_prompt():
    text = format_report_for_prompt(CLEAN_REPORT)
    assert "Introduction and Scope" in text
    assert "Key Findings" in text
    assert "---" in text

# ---------------------------------------------------------------------------
# Tests: response_parser (T21)
# ---------------------------------------------------------------------------

def test_split_top_level_separates_report_and_corrections():
    report_block, corrections_block = _split_top_level(VALID_PROMPT_C_OUTPUT)
    assert "Introduction and Scope" in report_block
    assert "corrections" in corrections_block.lower() or "placeholder" in corrections_block.lower()

def test_split_top_level_missing_corrections_heading():
    # Should fall back gracefully
    report_block, corrections_block = _split_top_level("Some raw output with no headings.")
    assert "Some raw output" in report_block
    assert corrections_block == ""

def test_parse_corrections_extracts_entries():
    log = _parse_corrections(
        "- [Intro] Removed placeholder.\n- Fixed weak phrasing in findings.",
        "job-c-2",
    )
    assert log.correction_count == 2
    assert log.corrections[0].section_title == "Intro"
    assert "placeholder" in log.corrections[0].description.lower()

def test_parse_corrections_no_corrections():
    log = _parse_corrections("- No corrections required.", "job-c-3")
    assert log.correction_count == 1
    assert "No corrections required" in log.corrections[0].description

def test_parse_validation_output_valid():
    report, log = parse_validation_output(
        VALID_PROMPT_C_OUTPUT, "job-c-4",
        ISOStandard.QMS, AuditStage.STAGE_1,
        expected_titles=["Introduction and Scope", "Documented Information Review", "Key Findings"],
    )
    assert report.job_id == "job-c-4"
    assert len(report.sections) == 3
    assert log.correction_count >= 1

def test_parse_validation_output_empty_raises():
    with pytest.raises(ValueError, match="empty output"):
        parse_validation_output("", "job-c-5", ISOStandard.QMS, AuditStage.STAGE_1)

def test_parse_validation_output_no_corrections_required():
    report, log = parse_validation_output(
        NO_CORRECTIONS_OUTPUT, "job-c-6",
        ISOStandard.QMS, AuditStage.STAGE_1,
        expected_titles=["Introduction and Scope"],
    )
    assert len(report.sections) == 1
    assert "No corrections required" in log.corrections[0].description

def test_parse_validation_output_flags_weak_evidence():
    report, _ = parse_validation_output(
        VALID_PROMPT_C_OUTPUT, "job-c-7",
        ISOStandard.QMS, AuditStage.STAGE_1,
    )
    weak = [s for s in report.sections if s.has_weak_evidence]
    assert len(weak) >= 1  # "Limited documented evidence" section

# ---------------------------------------------------------------------------
# Tests: post_validator (T22)
# ---------------------------------------------------------------------------

def _make_validated(sections: list[ReportSection]) -> ValidatedReport:
    return ValidatedReport(
        job_id="job-c-pv",
        sections=sections,
        correction_log=CorrectionLog(job_id="job-c-pv", corrections=[], correction_count=0),
        raw_output="raw",
    )

def test_post_validation_passes_complete_report():
    vr = _make_validated([
        ReportSection(title="Introduction and Scope", content="Content A", order_index=0),
        ReportSection(title="Documented Information Review", content="Content B", order_index=1),
        ReportSection(title="Key Findings", content="Content C", order_index=2),
    ])
    violations = run_post_validation(vr, TEMPLATE_MAP)
    assert violations == []

def test_post_validation_raises_on_missing_section():
    vr = _make_validated([
        ReportSection(title="Introduction and Scope", content="Content A", order_index=0),
        ReportSection(title="Key Findings", content="Content C", order_index=2),
    ])
    with pytest.raises(PostValidationError) as exc_info:
        run_post_validation(vr, TEMPLATE_MAP)
    assert any("MISSING_SECTION" in v for v in exc_info.value.violations)

def test_post_validation_raises_on_extra_section():
    vr = _make_validated([
        ReportSection(title="Introduction and Scope", content="Content A", order_index=0),
        ReportSection(title="Documented Information Review", content="Content B", order_index=1),
        ReportSection(title="Key Findings", content="Content C", order_index=2),
        ReportSection(title="Invented Section", content="Not in template", order_index=3),
    ])
    with pytest.raises(PostValidationError) as exc_info:
        run_post_validation(vr, TEMPLATE_MAP)
    assert any("EXTRA_SECTION" in v for v in exc_info.value.violations)

def test_post_validation_raises_on_placeholder():
    vr = _make_validated([
        ReportSection(title="Introduction and Scope", content="[INSERT HERE]", order_index=0),
        ReportSection(title="Documented Information Review", content="Fine", order_index=1),
        ReportSection(title="Key Findings", content="Fine", order_index=2),
    ])
    with pytest.raises(PostValidationError) as exc_info:
        run_post_validation(vr, TEMPLATE_MAP)
    assert any("PLACEHOLDER_PRESENT" in v for v in exc_info.value.violations)

def test_post_validation_raises_on_empty_content():
    vr = _make_validated([
        ReportSection(title="Introduction and Scope", content="", order_index=0),
        ReportSection(title="Documented Information Review", content="Fine", order_index=1),
        ReportSection(title="Key Findings", content="Fine", order_index=2),
    ])
    with pytest.raises(PostValidationError) as exc_info:
        run_post_validation(vr, TEMPLATE_MAP)
    assert any("EMPTY_CONTENT" in v for v in exc_info.value.violations)

def test_post_validation_error_carries_violations():
    vr = _make_validated([
        ReportSection(title="Introduction and Scope", content="", order_index=0),
        ReportSection(title="Key Findings", content="Fine", order_index=2),
    ])
    with pytest.raises(PostValidationError) as exc_info:
        run_post_validation(vr, TEMPLATE_MAP)
    # Should carry at least MISSING_SECTION + EMPTY_CONTENT
    assert len(exc_info.value.violations) >= 2

