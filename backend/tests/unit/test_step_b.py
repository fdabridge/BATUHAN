"""
BATUHAN — Unit Tests: Step B Report Generation
Tests the context builder, report parser, and safety checker
without making any real API calls.
"""

import pytest
from schemas.models import (
    ISOStandard, AuditStage, TemplateSection, TemplateMap,
    StyleGuidance, GeneratedReport, ReportSection,
)
from pipeline.step_b.context_builder import (
    get_stage_instructions, get_standard_instructions, build_prompt_b_context,
)
from pipeline.step_b.report_parser import (
    parse_report_output, _split_blocks, _parse_block, _has_placeholder, _is_weak_section,
)
from pipeline.step_b.safety_checker import (
    check_report_safety, format_violations, get_sections_needing_retry, SafetyViolation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_REPORT_OUTPUT = """
Section Title:
Introduction and Scope

Content:
The audit was conducted at the organisation's primary facility. The scope of the management
system covers design, manufacture, and distribution of industrial components. The quality
management system is documented and implemented across all relevant departments.

---

Section Title:
Documented Information Review

Content:
The organisation maintains a Quality Manual (QM-001) and supporting procedures.
Based on the documented information provided, the internal audit programme is established.
The management review process is evidenced by minutes dated Q3.

---

Section Title:
Key Findings

Content:
The audit team identified conformance with the majority of the standard requirements.
Limited documented evidence was observed for risk register maintenance.
Corrective action records are maintained and up to date.

---
"""

MISSING_SEPARATOR_OUTPUT = """
Section Title:
Introduction

Content:
Some content here without any separators between sections.

Section Title:
Second Section

Content:
More content.
"""

PLACEHOLDER_OUTPUT = """
Section Title:
Introduction

Content:
[INSERT COMPANY NAME HERE] is a manufacturer. The scope TBD.

---
"""

TEMPLATE_MAP = TemplateMap(
    source_path="template.docx",
    sections=[
        TemplateSection(title="Introduction and Scope", order_index=0),
        TemplateSection(title="Documented Information Review", order_index=1),
        TemplateSection(title="Key Findings", order_index=2),
    ],
)

STYLE_GUIDANCE = StyleGuidance(
    tone_notes=["Formal, objective language throughout."],
    structure_notes=["Each section is a narrative paragraph."],
    blocked_company_names=["SampleCorp", "ExampleLtd"],
    blocked_phrases=["SampleCorp achieved certification in 2023"],
)

# ---------------------------------------------------------------------------
# Tests: context_builder (T16 + T17)
# ---------------------------------------------------------------------------

def test_stage_1_instructions_contain_documentation():
    instr = get_stage_instructions(AuditStage.STAGE_1)
    assert "document" in instr.lower()
    assert "readiness" in instr.lower() or "ready" in instr.lower()

def test_stage_2_instructions_contain_implementation():
    instr = get_stage_instructions(AuditStage.STAGE_2)
    assert "implement" in instr.lower()
    assert "effectiveness" in instr.lower() or "effective" in instr.lower()

def test_all_standards_have_instructions():
    for standard in ISOStandard:
        instr = get_standard_instructions(standard)
        assert instr, f"No instructions for {standard}"
        assert len(instr) > 50, f"Instructions too short for {standard}"

def test_qms_instructions_mention_customer():
    instr = get_standard_instructions(ISOStandard.QMS)
    assert "customer" in instr.lower()

def test_ems_instructions_mention_environmental():
    instr = get_standard_instructions(ISOStandard.EMS)
    assert "environmental" in instr.lower()

def test_ohsms_instructions_mention_hazard():
    instr = get_standard_instructions(ISOStandard.OHSMS)
    assert "hazard" in instr.lower()

def test_build_prompt_b_context_returns_all_keys():
    ctx = build_prompt_b_context(
        standard=ISOStandard.QMS,
        stage=AuditStage.STAGE_1,
        template_map=TEMPLATE_MAP,
        style_guidance=STYLE_GUIDANCE,
        evidence_text="## Company Overview\n- Acme Ltd\n",
    )
    required_keys = {
        "standard", "stage", "stage_instructions",
        "standard_instructions", "template_sections",
        "extracted_evidence", "style_guidance",
    }
    assert required_keys.issubset(ctx.keys())
    assert ctx["standard"] == "QMS"
    assert ctx["stage"] == "Stage 1"

# ---------------------------------------------------------------------------
# Tests: report_parser
# ---------------------------------------------------------------------------

def test_split_blocks_returns_correct_count():
    blocks = _split_blocks(VALID_REPORT_OUTPUT)
    assert len(blocks) == 3

def test_parse_block_extracts_title_and_content():
    block = "Section Title:\nIntroduction\n\nContent:\nThis is the content."
    result = _parse_block(block)
    assert result is not None
    title, content = result
    assert title == "Introduction"
    assert "content" in content.lower()

def test_parse_block_inline_title():
    block = "Section Title: My Section\n\nContent: Some content here."
    result = _parse_block(block)
    assert result is not None
    title, content = result
    assert title == "My Section"

def test_parse_block_returns_none_on_empty():
    assert _parse_block("") is None
    assert _parse_block("just some random text") is None

def test_has_placeholder_detects_brackets():
    assert _has_placeholder("[INSERT HERE]") is True
    assert _has_placeholder("Normal text") is False
    assert _has_placeholder("TO BE COMPLETED") is True

def test_is_weak_section_detects_phrases():
    assert _is_weak_section("Limited documented evidence was observed") is True
    assert _is_weak_section("The system is fully implemented") is False

def test_parse_report_output_valid():
    report = parse_report_output(
        VALID_REPORT_OUTPUT, "job-b-1",
        ISOStandard.QMS, AuditStage.STAGE_1,
        expected_titles=["Introduction and Scope", "Documented Information Review", "Key Findings"],
    )
    assert report.job_id == "job-b-1"
    assert len(report.sections) == 3
    assert report.standard == ISOStandard.QMS
    assert report.stage == AuditStage.STAGE_1

def test_parse_report_output_flags_weak_sections():
    report = parse_report_output(
        VALID_REPORT_OUTPUT, "job-b-2",
        ISOStandard.QMS, AuditStage.STAGE_2,
    )
    weak_sections = [s for s in report.sections if s.has_weak_evidence]
    assert len(weak_sections) >= 1

def test_parse_report_output_respects_template_order():
    expected = ["Introduction and Scope", "Documented Information Review", "Key Findings"]
    report = parse_report_output(
        VALID_REPORT_OUTPUT, "job-b-3",
        ISOStandard.QMS, AuditStage.STAGE_1, expected_titles=expected,
    )
    for i, section in enumerate(report.sections):
        assert section.order_index == i

def test_parse_report_output_empty_raises():
    with pytest.raises(ValueError, match="empty output"):
        parse_report_output("", "job-b-4", ISOStandard.QMS, AuditStage.STAGE_1)

def test_parse_report_output_no_sections_raises():
    with pytest.raises(ValueError):
        parse_report_output("completely unparseable garbage", "job-b-5", ISOStandard.QMS, AuditStage.STAGE_1)

# ---------------------------------------------------------------------------
# Tests: safety_checker (T18)
# ---------------------------------------------------------------------------

def test_safety_check_passes_clean_report():
    report = parse_report_output(
        VALID_REPORT_OUTPUT, "job-b-6",
        ISOStandard.QMS, AuditStage.STAGE_1,
        expected_titles=["Introduction and Scope", "Documented Information Review", "Key Findings"],
    )
    violations = check_report_safety(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    assert violations == []

def test_safety_check_detects_placeholder():
    report = parse_report_output(
        PLACEHOLDER_OUTPUT, "job-b-7",
        ISOStandard.QMS, AuditStage.STAGE_1,
    )
    # Inject a template that matches the section title
    tm = TemplateMap(source_path="t.docx", sections=[
        TemplateSection(title="Introduction", order_index=0),
    ])
    violations = check_report_safety(report, tm, StyleGuidance())
    rules = [v.rule for v in violations]
    assert "PLACEHOLDER_PRESENT" in rules

def test_safety_check_detects_missing_section():
    # Report only has 2 of the 3 template sections
    report = GeneratedReport(
        job_id="job-b-8",
        standard=ISOStandard.QMS,
        stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="Content A", order_index=0),
            ReportSection(title="Key Findings", content="Content C", order_index=2),
        ],
        raw_output="raw",
    )
    violations = check_report_safety(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    rules = [v.rule for v in violations]
    assert "MISSING_SECTION" in rules

def test_safety_check_detects_extra_section():
    report = GeneratedReport(
        job_id="job-b-9",
        standard=ISOStandard.QMS,
        stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="Content A", order_index=0),
            ReportSection(title="Documented Information Review", content="Content B", order_index=1),
            ReportSection(title="Key Findings", content="Content C", order_index=2),
            ReportSection(title="Invented Extra Section", content="Not in template", order_index=3),
        ],
        raw_output="raw",
    )
    violations = check_report_safety(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    rules = [v.rule for v in violations]
    assert "EXTRA_SECTION" in rules

def test_safety_check_detects_blocked_company_name():
    report = GeneratedReport(
        job_id="job-b-10",
        standard=ISOStandard.QMS,
        stage=AuditStage.STAGE_1,
        sections=[
            ReportSection(title="Introduction and Scope", content="SampleCorp is the auditee.", order_index=0),
            ReportSection(title="Documented Information Review", content="Fine content.", order_index=1),
            ReportSection(title="Key Findings", content="All good.", order_index=2),
        ],
        raw_output="raw",
    )
    violations = check_report_safety(report, TEMPLATE_MAP, STYLE_GUIDANCE)
    rules = [v.rule for v in violations]
    assert "SAMPLE_LEAKAGE" in rules

def test_get_sections_needing_retry():
    violations = [
        SafetyViolation("Intro", "PLACEHOLDER_PRESENT", "detail"),
        SafetyViolation("Findings", "MISSING_SECTION", "detail"),
        SafetyViolation("Scope", "SAMPLE_LEAKAGE", "detail"),
    ]
    retry_set = get_sections_needing_retry(violations)
    assert "Intro" in retry_set
    assert "Scope" in retry_set
    assert "Findings" not in retry_set  # MISSING_SECTION is not retryable

def test_format_violations_no_violations():
    assert "No safety violations" in format_violations([])

def test_format_violations_with_violations():
    v = SafetyViolation("Intro", "PLACEHOLDER_PRESENT", "Has [INSERT] marker.")
    result = format_violations([v])
    assert "1 violation" in result
    assert "Intro" in result

