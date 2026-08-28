"""Cross-feature contract tests for Certiv.AI integrated audits."""

import pytest
from pathlib import Path

from audit_plan.clause_map import CLAUSE_MAP
from audit_plan.routes import _parse_standards
from config.clause_configs.loader import load_clause_config
from config.review_profiles.loader import load_review_profile
from schemas.certivai import (
    company_name_matches_target, normalize_iso_standard_inputs, review_stage_key,
    submitted_scope_text,
)
from schemas.models import AuditStage, ISOStandard, normalize_iso_standard


FULL_LABELS = {
    ISOStandard.QMS: "ISO 9001:2015",
    ISOStandard.EMS: "ISO 14001:2015",
    ISOStandard.OHSMS: "ISO 45001:2018",
    ISOStandard.FSMS: "ISO 22000:2018",
    ISOStandard.MDQMS: "ISO 13485:2016",
    ISOStandard.ISMS: "ISO/IEC 27001:2022",
    ISOStandard.ABMS: "ISO 37001:2016",
    ISOStandard.ENMS: "ISO 50001:2018",
}

_BACKEND_ROOT = Path(__file__).parents[2]
_DOCX_BUILDER_SOURCE = (_BACKEND_ROOT / "assembly" / "docx_builder.py").read_text()
_LLM_MAPPER_SOURCE = (_BACKEND_ROOT / "assembly" / "llm_mapper.py").read_text()


@pytest.mark.parametrize("standard, full_label", FULL_LABELS.items())
def test_every_certivai_feature_resolves_the_same_standard(standard, full_label):
    assert normalize_iso_standard(standard.value) is standard
    assert normalize_iso_standard(full_label) is standard
    assert load_clause_config(standard.value).standard_code == standard.value
    assert f'"{standard.value}"' in _DOCX_BUILDER_SOURCE
    assert f'"{standard.value}"' in _LLM_MAPPER_SOURCE
    assert full_label in CLAUSE_MAP


def test_every_standard_has_a_clause_plan_for_every_exact_cycle():
    expected_stages = {stage.value for stage in AuditStage}
    for clauses_by_stage in CLAUSE_MAP.values():
        assert set(clauses_by_stage) == expected_stages
        assert all(value.strip() for value in clauses_by_stage.values())


@pytest.mark.parametrize("profile_code", ["UAF", "IAF", "TURKAK"])
def test_specialized_integrated_rules_cover_high_context_standards(profile_code):
    rules = load_review_profile(profile_code).get("standard_specific_rules", {})
    assert {"FSMS", "ISMS", "MDQMS", "ENMS"}.issubset(rules)


def test_integrated_inputs_normalize_across_report_review_and_audit_plan_paths():
    expected_codes = ["QMS", "FSMS", "ISMS"]
    assert normalize_iso_standard_inputs(
        ["ISO 9001:2015 + FSMS", "ISO/IEC 27001:2022"],
    ) == expected_codes

    standards, _label = _parse_standards("QMS + ISO 22000:2018 + ISMS")
    assert standards == [
        "ISO 9001:2015",
        "ISO 22000:2018",
        "ISO/IEC 27001:2022",
    ]
    standards, _label = _parse_standards('["QMS + FSMS", "ISO 27001"]')
    assert standards == [
        "ISO 9001:2015",
        "ISO 22000:2018",
        "ISO/IEC 27001:2022",
    ]


def test_current_auditee_name_is_not_misclassified_as_cross_client_leakage():
    assert company_name_matches_target(
        "TMS FOODS B.V.",
        "TMS FOODS B.V. The Netherlands",
    )
    assert not company_name_matches_target("Unrelated Sample GmbH", "TMS FOODS B.V.")


def test_submitted_bilingual_scope_is_evidence_not_an_address_value():
    text = submitted_scope_text("Food production", "Gıda üretimi")
    assert text == (
        "Certification scope (English): Food production\n"
        "Belgelendirme kapsamı (Türkçe): Gıda üretimi"
    )


@pytest.mark.parametrize("stage", list(AuditStage))
def test_review_stage_mapping_preserves_all_five_user_cycles(stage):
    expected = {
        AuditStage.STAGE_1: "stage_1",
        AuditStage.STAGE_2: "stage_2",
        AuditStage.SURVEILLANCE_1: "surveillance",
        AuditStage.SURVEILLANCE_2: "surveillance",
        AuditStage.RECERTIFICATION: "recertification",
    }[stage]
    assert review_stage_key(stage.value) == expected
