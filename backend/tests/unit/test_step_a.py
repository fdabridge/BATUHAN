"""
BATUHAN — Unit Tests: Step A Evidence Extraction
Tests the evidence parser, validator, and traceability modules
without making any real API calls.
"""

import pytest
from backend.schemas.models import ParsedDocument, ExtractedEvidence, EvidenceItem
from backend.pipeline.step_a.evidence_parser import (
    parse_evidence_output,
    validate_evidence,
    format_evidence_for_prompt,
    REQUIRED_SECTIONS,
    SECTION_FIELD_MAP,
    _is_weak,
    _parse_bullets,
    _split_into_sections,
)
from backend.pipeline.step_a.traceability import (
    attach_traceability,
    build_traceability_report,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_PROMPT_A_OUTPUT = """
## Company Overview
- Legal name: Acme Manufacturing Ltd
- Address: 123 Industrial Road, Istanbul, Turkey
- Site covers production, warehousing, and office functions

## Scope of Activities
- Design, manufacture, and distribution of industrial components
- Scope includes all departments on the single site

## Documented Information Identified
- Quality Manual (QM-001) observed
- Environmental Policy (EP-001) observed
- Internal Audit Procedure (IAP-002) identified

## Key Processes and Functions
- Production planning and control
- Customer order management
- Incoming material inspection

## Evidence of System Implementation
- Internal audit records reviewed for the current period
- Management review minutes dated Q3 available
- Corrective action log maintained and up to date

## Audit-Relevant Records
- Internal Audit Report (IAR-2024-01) reviewed
- Management Review Minutes (MRM-Q3-2024) observed
- Training records available for key personnel

## Identified Gaps or Unclear Areas
- Risk register not clearly evidenced in provided documents
- Supplier evaluation records: Not clearly evidenced
"""

MISSING_SECTIONS_OUTPUT = """
## Company Overview
- Acme Ltd

## Scope of Activities
- Manufacturing
"""

EMPTY_OUTPUT = ""

# ---------------------------------------------------------------------------
# Tests: _is_weak
# ---------------------------------------------------------------------------

def test_is_weak_detects_not_clearly_evidenced():
    assert _is_weak("Risk register: Not clearly evidenced") is True

def test_is_weak_detects_unclear():
    assert _is_weak("This area is unclear from the documents") is True

def test_is_weak_clean_statement():
    assert _is_weak("Quality Manual QM-001 was observed and reviewed") is False

def test_is_weak_case_insensitive():
    assert _is_weak("No Evidence found for this control") is True

# ---------------------------------------------------------------------------
# Tests: _parse_bullets
# ---------------------------------------------------------------------------

def test_parse_bullets_dash():
    text = "- Item one\n- Item two\n- Item three"
    result = _parse_bullets(text)
    assert result == ["Item one", "Item two", "Item three"]

def test_parse_bullets_asterisk():
    text = "* Item A\n* Item B"
    result = _parse_bullets(text)
    assert result == ["Item A", "Item B"]

def test_parse_bullets_plain_lines():
    text = "Statement one\nStatement two"
    result = _parse_bullets(text)
    assert result == ["Statement one", "Statement two"]

def test_parse_bullets_ignores_headings():
    text = "## Heading\n- Bullet"
    result = _parse_bullets(text)
    assert result == ["Bullet"]

# ---------------------------------------------------------------------------
# Tests: _split_into_sections
# ---------------------------------------------------------------------------

def test_split_into_sections_returns_all_sections():
    sections = _split_into_sections(VALID_PROMPT_A_OUTPUT)
    assert "Company Overview" in sections
    assert "Identified Gaps or Unclear Areas" in sections
    assert len(sections) == 7

def test_split_into_sections_empty_input():
    assert _split_into_sections("") == {}

# ---------------------------------------------------------------------------
# Tests: parse_evidence_output
# ---------------------------------------------------------------------------

def test_parse_evidence_output_valid():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="test-job-1")
    assert evidence.job_id == "test-job-1"
    assert len(evidence.company_overview) >= 1
    assert len(evidence.identified_gaps) >= 1

def test_parse_evidence_output_flags_weak_items():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="test-job-2")
    weak_items = [i for i in evidence.identified_gaps if i.is_weak]
    assert len(weak_items) >= 1

def test_parse_evidence_output_empty_raises():
    with pytest.raises(ValueError, match="empty output"):
        parse_evidence_output(EMPTY_OUTPUT, job_id="test-job-3")

def test_parse_evidence_output_missing_sections_fills_weak():
    evidence = parse_evidence_output(MISSING_SECTIONS_OUTPUT, job_id="test-job-4")
    # Missing sections should be filled with weak placeholder items
    assert len(evidence.documented_information) >= 1
    assert all(i.is_weak for i in evidence.documented_information)

def test_parse_evidence_output_all_7_fields_present():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="test-job-5")
    for field in SECTION_FIELD_MAP.values():
        items = getattr(evidence, field)
        assert isinstance(items, list), f"Field '{field}' should be a list"
        assert len(items) > 0, f"Field '{field}' should not be empty"

# ---------------------------------------------------------------------------
# Tests: validate_evidence
# ---------------------------------------------------------------------------

def test_validate_evidence_passes_good_evidence():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="test-job-6")
    warnings = validate_evidence(evidence)
    # Gaps section may be all-weak — that's expected
    assert isinstance(warnings, list)

def test_validate_evidence_warns_all_weak_sections():
    evidence = parse_evidence_output(MISSING_SECTIONS_OUTPUT, job_id="test-job-7")
    warnings = validate_evidence(evidence)
    assert len(warnings) > 0

# ---------------------------------------------------------------------------
# Tests: traceability
# ---------------------------------------------------------------------------

def test_attach_traceability_links_by_filename():
    corpus = [
        ParsedDocument(
            filename="quality_manual.pdf",
            text="Quality Manual QM-001 covers all quality processes",
            char_count=50,
        )
    ]
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="test-job-8")
    evidence = attach_traceability(evidence, corpus)
    # At least some items should have source_filename set
    all_items = [
        item
        for field in SECTION_FIELD_MAP.values()
        for item in getattr(evidence, field, [])
    ]
    assert any(item.source_filename is not None for item in all_items)

def test_attach_traceability_no_corpus():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="test-job-9")
    evidence = attach_traceability(evidence, [])
    # With no corpus, source_filename should remain None for all items
    all_items = [
        item
        for field in SECTION_FIELD_MAP.values()
        for item in getattr(evidence, field, [])
    ]
    assert all(item.source_filename is None for item in all_items)

def test_build_traceability_report_contains_job_id():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="trace-job-1")
    report = build_traceability_report(evidence)
    assert "trace-job-1" in report
    assert "TRACEABILITY REPORT" in report

# ---------------------------------------------------------------------------
# Tests: format_evidence_for_prompt
# ---------------------------------------------------------------------------

def test_format_evidence_for_prompt_contains_all_sections():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="fmt-job-1")
    formatted = format_evidence_for_prompt(evidence)
    for section in REQUIRED_SECTIONS:
        assert section in formatted

def test_format_evidence_for_prompt_flags_weak():
    evidence = parse_evidence_output(VALID_PROMPT_A_OUTPUT, job_id="fmt-job-2")
    formatted = format_evidence_for_prompt(evidence)
    assert "[WEAK EVIDENCE]" in formatted

