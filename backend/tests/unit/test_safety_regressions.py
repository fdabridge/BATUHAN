"""
BATUHAN — Safety & Leakage Regression Tests (T35)
Ensures all safety guards remain effective and no regression is introduced.
"""

import pytest
from unittest.mock import patch, MagicMock

from backend.schemas.models import (
    ExtractedEvidence, EvidenceItem,
    GeneratedReport, ReportSection, ValidatedReport, CorrectionLog,
    TemplateMap, TemplateSection, StyleGuidance,
    ISOStandard, AuditStage,
)
from backend.pipeline.step_a.evidence_parser import (
    REQUIRED_SECTIONS, _is_weak,
)
from backend.safety.leakage_detector import (
    scan_report_for_leakage, _scan_placeholders, _scan_company_names, _scan_phrase_copy,
)
from backend.safety.failure_handler import (
    PipelineAbort, filter_readable_documents, assert_template_valid,
    assert_evidence_valid, step_c_fallback,
)
from backend.pipeline.step_b.safety_checker import (
    check_report_safety, _has_placeholder,
)


# ---------------------------------------------------------------------------
# T35-1 — REQUIRED_SECTIONS always has exactly 7 sections
# ---------------------------------------------------------------------------

class TestRequiredSections:
    def test_exactly_seven_sections(self):
        assert len(REQUIRED_SECTIONS) == 7

    def test_section_names_match_spec(self):
        expected = {
            "Company Overview",
            "Scope of Activities",
            "Documented Information Identified",
            "Key Processes and Functions",
            "Evidence of System Implementation",
            "Audit-Relevant Records",
            "Identified Gaps or Unclear Areas",
        }
        assert set(REQUIRED_SECTIONS) == expected


# ---------------------------------------------------------------------------
# T35-2 — Weak evidence detection
# ---------------------------------------------------------------------------

class TestWeakEvidenceDetection:
    @pytest.mark.parametrize("phrase", [
        "limited evidence of implementation",
        "no evidence found",
        "not available",
        "unclear evidence",
        "insufficient documentation",
    ])
    def test_is_weak_flags_cautious_phrase(self, phrase):
        assert _is_weak(phrase) is True

    def test_is_weak_does_not_flag_strong_evidence(self):
        strong = "The organisation maintains a documented quality manual."
        assert _is_weak(strong) is False


# ---------------------------------------------------------------------------
# T35-3 — Leakage: placeholder patterns caught as CRITICAL
# ---------------------------------------------------------------------------

class TestLeakagePlaceholders:
    @pytest.mark.parametrize("content", [
        "The company [Insert Name Here] has a policy.",
        "Status: {variable_placeholder}",
        "TODO: complete this section",
        "TBD",
        "lorem ipsum dolor sit amet",
        "PLACEHOLDER text in report",
    ])
    def test_placeholder_detected_as_critical(self, content):
        violations = _scan_placeholders("Test Section", content)
        assert len(violations) >= 1
        assert all(v.severity == "CRITICAL" for v in violations)
        assert all(v.category == "PLACEHOLDER" for v in violations)

    def test_clean_content_has_no_violations(self):
        clean = "The organisation demonstrated effective implementation of its QMS."
        assert _scan_placeholders("Section", clean) == []


# ---------------------------------------------------------------------------
# T35-4 — Leakage: blocked company names caught as CRITICAL
# ---------------------------------------------------------------------------

class TestLeakageCompanyNames:
    def test_blocked_name_in_content_is_critical(self):
        violations = _scan_company_names(
            "Introduction", "The organisation Acme Ltd operates a QMS.",
            blocked_names=["Acme Ltd"]
        )
        assert len(violations) == 1
        assert violations[0].severity == "CRITICAL"
        assert violations[0].category == "COMPANY_NAME"

    def test_name_not_in_content_has_no_violation(self):
        violations = _scan_company_names(
            "Section", "Clean content here.", blocked_names=["Acme Ltd"]
        )
        assert violations == []

    def test_empty_blocked_list_never_violates(self):
        violations = _scan_company_names("S", "Any content at all.", blocked_names=[])
        assert violations == []


# ---------------------------------------------------------------------------
# T35-5 — Leakage: full report scan integration
# ---------------------------------------------------------------------------

class TestScanReportForLeakage:
    def _make_report(self, content: str) -> ValidatedReport:
        log = CorrectionLog(job_id="j1", corrections=[], correction_count=0)
        section = ReportSection(title="Introduction", content=content, order_index=0)
        return ValidatedReport(job_id="j1", sections=[section], correction_log=log, raw_output="")

    def test_clean_report_is_clean(self):
        report = self._make_report(
            "The audit team confirmed effective QMS implementation per ISO 9001:2015."
        )
        guidance = StyleGuidance(blocked_company_names=[])
        result = scan_report_for_leakage(report, guidance)
        assert result.is_clean is True
        assert result.has_critical is False

    def test_placeholder_in_report_marks_has_critical(self):
        report = self._make_report("The company [INSERT NAME] operates a QMS.")
        guidance = StyleGuidance(blocked_company_names=[])
        result = scan_report_for_leakage(report, guidance)
        assert result.has_critical is True

    def test_blocked_company_name_marks_has_critical(self):
        report = self._make_report("The organisation TechCorp GmbH has records.")
        guidance = StyleGuidance(blocked_company_names=["TechCorp GmbH"])
        result = scan_report_for_leakage(report, guidance)
        assert result.has_critical is True


# ---------------------------------------------------------------------------
# T35-6 — Failure handler guards
# ---------------------------------------------------------------------------

class TestFailureHandlerGuards:
    def test_filter_readable_docs_raises_on_all_empty(self):
        from backend.schemas.models import ParsedDocument
        docs = [ParsedDocument(filename="a.txt", text="", char_count=0)]
        with pytest.raises(PipelineAbort, match="unreadable"):
            filter_readable_documents(["a.txt"], docs)

    def test_filter_readable_docs_skips_empty_keeps_readable(self):
        from backend.schemas.models import ParsedDocument
        docs = [
            ParsedDocument(filename="a.txt", text="", char_count=0),
            ParsedDocument(filename="b.txt", text="Readable content here.", char_count=22),
        ]
        result = filter_readable_documents(["a.txt", "b.txt"], docs)
        assert len(result) == 1
        assert result[0].filename == "b.txt"

    def test_assert_template_valid_raises_on_empty_template(self):
        tm = TemplateMap(sections=[], source_path="/tmp/t.docx")
        with pytest.raises(PipelineAbort, match="no detectable sections"):
            assert_template_valid(tm)

    def test_assert_evidence_valid_raises_on_zero_items(self, tmp_path):
        evidence = ExtractedEvidence(job_id="j1", raw_output="")
        with patch("backend.safety.failure_handler.save_text_artifact"):
            with pytest.raises(PipelineAbort, match="returned no sections"):
                assert_evidence_valid(evidence, "j1")

    def test_step_c_fallback_returns_valid_report_and_log(self, tmp_path):
        sec = ReportSection(title="Introduction", content="Content.", order_index=0)
        report = GeneratedReport(
            job_id="j1", standard=ISOStandard.QMS,
            stage=AuditStage.STAGE_2, sections=[sec], raw_output="",
        )
        with patch("backend.safety.failure_handler.save_text_artifact"):
            validated, log = step_c_fallback("j1", report, RuntimeError("Step C crashed"))
        assert validated.job_id == "j1"
        assert log.correction_count == 0
        assert "FALLBACK" in validated.raw_output


# ---------------------------------------------------------------------------
# T35-7 — Step B safety checker: placeholder detection
# ---------------------------------------------------------------------------

class TestStepBSafetyChecker:
    def test_placeholder_detected_in_section(self):
        assert _has_placeholder("[PLACEHOLDER]") is True
        assert _has_placeholder("[INSERT date here]") is True
        assert _has_placeholder("{variable}") is True
        assert _has_placeholder("TO BE COMPLETED") is True
        assert _has_placeholder("TBD") is True

    def test_clean_content_passes_placeholder_check(self):
        assert _has_placeholder("The organisation maintains documented procedures.") is False

    def test_check_report_safety_finds_missing_template_section(self):
        tm = TemplateMap(sections=[
            TemplateSection(title="Introduction", order_index=0, placeholder_text=""),
            TemplateSection(title="Key Findings", order_index=1, placeholder_text=""),
        ], source_path="/tmp/t.docx")
        report = GeneratedReport(
            job_id="j1", standard=ISOStandard.QMS, stage=AuditStage.STAGE_2,
            sections=[
                ReportSection(title="Introduction", content="Intro content.", order_index=0),
                # "Key Findings" is missing
            ],
            raw_output="",
        )
        guidance = StyleGuidance(blocked_company_names=[])
        violations = check_report_safety(report, tm, guidance)
        rules = [v.rule for v in violations]
        assert any("missing" in r.lower() for r in rules)

