"""
BATUHAN — Unit Tests: Phase 9 (Safety, Auditability & Error Handling)
Covers:
  - audit_trail.build_audit_trail  (T30)
  - failure_handler guards         (T31)
  - leakage_detector scanner       (T32)
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.schemas.models import (
    ParsedDocument, TemplateMap, TemplateSection,
    ExtractedEvidence, EvidenceItem, GeneratedReport, ValidatedReport,
    CorrectionLog, ReportSection, StyleGuidance,
    ISOStandard, AuditStage,
)
from backend.safety.failure_handler import (
    PipelineAbort,
    filter_readable_documents,
    assert_template_valid,
    assert_evidence_valid,
    step_c_fallback,
)
from backend.safety.leakage_detector import (
    scan_report_for_leakage,
    write_leakage_report,
    LeakageReport,
)
from backend.safety.audit_trail import build_audit_trail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_report(job_id: str, content: str = "Good content here.") -> ValidatedReport:
    section = ReportSection(title="Scope", content=content, order_index=0)
    log = CorrectionLog(job_id=job_id, corrections=[], correction_count=0)
    return ValidatedReport(
        job_id=job_id, sections=[section],
        correction_log=log, raw_output="raw",
    )


def _make_generated(job_id: str, content: str = "Good content.") -> GeneratedReport:
    section = ReportSection(title="Scope", content=content, order_index=0)
    return GeneratedReport(
        job_id=job_id,
        standard=ISOStandard.QMS,
        stage=AuditStage.STAGE_1,
        sections=[section],
        raw_output="raw",
    )


def _make_style(blocked: list[str] | None = None) -> StyleGuidance:
    return StyleGuidance(
        blocked_company_names=blocked or [],
        blocked_phrases=[],
    )


def _template_map(n: int = 2) -> TemplateMap:
    sections = [TemplateSection(title=f"Section {i}", order_index=i) for i in range(n)]
    return TemplateMap(sections=sections, source_path="template.docx")


# ---------------------------------------------------------------------------
# T31 — failure_handler
# ---------------------------------------------------------------------------

class TestFilterReadableDocuments:
    def test_removes_empty_docs(self):
        docs = [
            ParsedDocument(filename="a.pdf", text="real content", char_count=12),
            ParsedDocument(filename="b.pdf", text="   ", char_count=3),
        ]
        result = filter_readable_documents(["a.pdf", "b.pdf"], docs)
        assert len(result) == 1
        assert result[0].filename == "a.pdf"

    def test_aborts_when_all_empty(self):
        docs = [ParsedDocument(filename="a.pdf", text="", char_count=0)]
        with pytest.raises(PipelineAbort, match="unreadable or empty"):
            filter_readable_documents(["a.pdf"], docs)

    def test_passes_through_all_readable(self):
        docs = [
            ParsedDocument(filename="a.pdf", text="text a", char_count=6),
            ParsedDocument(filename="b.pdf", text="text b", char_count=6),
        ]
        result = filter_readable_documents(["a.pdf", "b.pdf"], docs)
        assert len(result) == 2


class TestAssertTemplateValid:
    def test_valid_template_passes(self):
        assert_template_valid(_template_map(3))  # should not raise

    def test_empty_template_aborts(self):
        with pytest.raises(PipelineAbort, match="no detectable sections"):
            assert_template_valid(TemplateMap(sections=[], source_path="empty.docx"))


class TestAssertEvidenceValid:
    def test_valid_evidence_passes(self):
        # Has at least one item in company_overview → valid
        ev = ExtractedEvidence(
            job_id="j1",
            company_overview=[EvidenceItem(statement="Company has a QMS.")],
            raw_output="x",
        )
        assert_evidence_valid(ev, "j1")  # should not raise

    def test_empty_evidence_aborts(self):
        # All named fields empty by default → zero evidence
        ev = ExtractedEvidence(job_id="j2", raw_output="")
        with patch("backend.safety.failure_handler.save_text_artifact"):
            with pytest.raises(PipelineAbort, match="no sections"):
                assert_evidence_valid(ev, "j2")


class TestStepCFallback:
    def test_returns_valid_report_and_log(self):
        gen = _make_generated("j3")
        exc = RuntimeError("Claude timed out")
        with patch("backend.safety.failure_handler.save_text_artifact"):
            report, log = step_c_fallback("j3", gen, exc)
        assert report.job_id == "j3"
        assert report.sections == gen.sections
        assert "[FALLBACK" in report.raw_output
        assert log.correction_count == 0

    def test_writes_warning_artifact(self):
        gen = _make_generated("j4")
        with patch("backend.safety.failure_handler.save_text_artifact") as mock_save:
            step_c_fallback("j4", gen, ValueError("boom"))
        mock_save.assert_called_once()
        filename = mock_save.call_args[0][1]
        assert "fallback_warning" in filename


# ---------------------------------------------------------------------------
# T32 — leakage_detector
# ---------------------------------------------------------------------------

class TestScanReportForLeakage:
    def test_clean_report_passes(self):
        report = _make_report("j5", "The organisation maintains documented procedures.")
        result = scan_report_for_leakage(report, _make_style())
        assert result.is_clean is True
        assert result.has_critical is False

    def test_placeholder_detected_as_critical(self):
        report = _make_report("j6", "The [COMPANY NAME] has implemented ISO.")
        result = scan_report_for_leakage(report, _make_style())
        assert result.has_critical is True
        cats = [v.category for v in result.violations]
        assert "PLACEHOLDER" in cats

    def test_blocked_company_name_is_critical(self):
        report = _make_report("j7", "Acme Corp maintains a quality manual.")
        result = scan_report_for_leakage(report, _make_style(blocked=["Acme Corp"]))
        assert result.has_critical is True
        cats = [v.category for v in result.violations]
        assert "COMPANY_NAME" in cats

    def test_phrase_copy_is_warning_not_critical(self):
        long_phrase = "the organisation has established and maintained a comprehensive " \
                      "management system that covers all relevant operational processes"
        report = _make_report("j8", long_phrase)
        result = scan_report_for_leakage(report, _make_style(), sample_texts=[long_phrase])
        phrase_viols = [v for v in result.violations if v.category == "PHRASE_COPY"]
        if phrase_viols:
            assert all(v.severity == "WARNING" for v in phrase_viols)
            assert result.has_critical is False

    def test_write_leakage_report_persists(self):
        report = _make_report("j9")
        leakage = LeakageReport(job_id="j9", is_clean=True, has_critical=False)
        with patch("backend.safety.leakage_detector.save_text_artifact") as mock_save:
            write_leakage_report("j9", leakage)
        mock_save.assert_called_once()
        assert mock_save.call_args[0][1] == "leakage_scan.json"


# ---------------------------------------------------------------------------
# T30 — audit_trail
# ---------------------------------------------------------------------------

class TestBuildAuditTrail:
    def _mock_read(self, bundle: dict, status: dict, evidence: dict, report_b: dict, corr: dict):
        """Return a side_effect function for read_text_artifact."""
        mapping = {
            "bundle.json": json.dumps(bundle),
            "status.json": json.dumps(status),
            "step_a_evidence.json": json.dumps(evidence),
            "step_b_report.json": json.dumps(report_b),
            "step_c_correction_log.json": json.dumps(corr),
        }
        return lambda job_id, fname: mapping[fname]

    def test_trail_contains_required_keys(self):
        bundle = {
            "standard": "QMS", "stage": "Stage 1",
            "company_document_paths": [], "sample_report_paths": [],
            "template_path": "/tmp/t.docx",
        }
        status = {"state": "COMPLETE", "step_timestamps": {}, "started_at": None, "completed_at": None}
        evidence = {"sections": {"key": []}}
        report_b = {"sections": [{}, {}]}
        corr = {"correction_count": 3, "validated_at": "2024-01-01T00:00:00"}

        read_fn = self._mock_read(bundle, status, evidence, report_b, corr)
        with patch("backend.safety.audit_trail.read_text_artifact", side_effect=read_fn), \
             patch("backend.safety.audit_trail.list_files", return_value=[]):
            trail = build_audit_trail("j10")

        assert trail["job_id"] == "j10"
        assert trail["standard"] == "QMS"
        assert trail["step_b"]["section_count"] == 2
        assert trail["step_c"]["correction_count"] == 3
        assert "prompt_version" in trail
        assert "claude_model" in trail

    def test_trail_handles_missing_artifacts_gracefully(self):
        with patch("backend.safety.audit_trail.read_text_artifact", side_effect=FileNotFoundError), \
             patch("backend.safety.audit_trail.list_files", return_value=[]):
            trail = build_audit_trail("j11")
        # Should not raise; should contain error keys instead
        assert "bundle_error" in trail or "status_error" in trail

