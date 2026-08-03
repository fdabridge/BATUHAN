from types import SimpleNamespace

from audit_set.report_signature_rules import (
    audit_report_has_all_required_approvals,
    audit_report_form_allowed_for_stage,
    audit_report_requires_appointed_reviewer,
    audit_report_requires_certification_manager,
)


def _report(**overrides):
    values = {
        "report_form": "FR.231-1",
        "la_signed_at": None,
        "appointed_reviewer_signed_at": None,
        "reviewer_signed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_mdqms_report_uses_stage_1_signature_route():
    report = _report()
    audit_set = SimpleNamespace(standards=["MDQMS"])

    assert audit_report_requires_appointed_reviewer(report, audit_set) is False
    assert audit_report_requires_certification_manager(report, audit_set) is True


def test_mdqms_report_requires_lead_auditor_and_certification_manager():
    audit_set = SimpleNamespace(standards=["MDQMS"])

    assert audit_report_has_all_required_approvals(_report(), audit_set) is False
    assert audit_report_has_all_required_approvals(
        _report(la_signed_at=object()),
        audit_set,
    ) is False
    assert audit_report_has_all_required_approvals(
        _report(la_signed_at=object(), reviewer_signed_at=object()),
        audit_set,
    ) is True


def test_mdqms_stage_2_report_uses_isms_signature_route():
    report = _report(report_form="FR.232-1")
    audit_set = SimpleNamespace(standards=["MDQMS"])

    assert audit_report_requires_appointed_reviewer(report, audit_set) is False
    assert audit_report_requires_certification_manager(report, audit_set) is True
    assert audit_report_has_all_required_approvals(
        _report(
            report_form="FR.232-1",
            la_signed_at=object(),
            reviewer_signed_at=object(),
        ),
        audit_set,
    ) is True


def test_report_forms_are_restricted_to_their_audit_stages():
    assert audit_report_form_allowed_for_stage("FR.231", "stage_1") is True
    assert audit_report_form_allowed_for_stage("FR.231", "stage_2") is False
    assert audit_report_form_allowed_for_stage("FR.231-1", "stage_1") is True
    assert audit_report_form_allowed_for_stage("FR.231-1", "stage_2") is False
    assert audit_report_form_allowed_for_stage("FR.232", "stage_1") is False
    assert audit_report_form_allowed_for_stage("FR.232", "stage_2") is True
    assert audit_report_form_allowed_for_stage("FR.232", "surveillance") is True
    assert audit_report_form_allowed_for_stage("FR.232-1", "stage_1") is False
    assert audit_report_form_allowed_for_stage("FR.232-1", "stage_2") is True
    assert audit_report_form_allowed_for_stage("FR.232-1", "surveillance") is True
    assert audit_report_form_allowed_for_stage("FR.232-1", "recertification") is True
    assert audit_report_form_allowed_for_stage("FR.229", "stage_1") is True
    assert audit_report_form_allowed_for_stage("FR.229", "stage_2") is True
