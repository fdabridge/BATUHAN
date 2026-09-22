from types import SimpleNamespace

import pytest

from audit_set.pipeline_triggers import _trigger_fr218_phase
from audit_set.resolver import _apply_workflow_document_gate
from audit_set.workflow_policy import (
    FR218_BEFORE_COMMERCIAL_VERSION,
    commercial_documents_unlocked,
    quotation_source_status,
    status_at_least,
    transition_matches_version,
    uses_fr218_before_commercial,
    workflow_version,
)


def _application(version=None, status="in_planning", audit_type="initial"):
    values = {
        "standards": ["QMS"],
        "audit_type": audit_type,
        "accreditation_body": "UAF",
        "is_transfer": False,
        "workflow_status": status,
    }
    if version is not None:
        values["workflow_version"] = version
    return SimpleNamespace(**values)


def _fr_numbers(application):
    document_set = {
        "Stage_1": [
            SimpleNamespace(fr_number="FR.218"),
            SimpleNamespace(fr_number="FR.220"),
            SimpleNamespace(fr_number="FR.221"),
            SimpleNamespace(fr_number="FR.222"),
        ],
    }
    _apply_workflow_document_gate(document_set, application)
    return {
        spec.fr_number
        for specs in document_set.values()
        for spec in specs
    }


def test_missing_workflow_version_is_legacy_for_existing_records():
    application = _application()

    assert workflow_version(application) == 1
    assert uses_fr218_before_commercial(application) is False
    assert transition_matches_version(application, "in_planning", "quotation_sent") is True
    assert commercial_documents_unlocked(application) is True
    assert quotation_source_status(application) == "in_planning"
    assert {"FR.218", "FR.220", "FR.221"}.issubset(_fr_numbers(application))


def test_existing_completed_application_keeps_legacy_state_and_documents():
    application = _application(version=1, status="certified")

    assert transition_matches_version(application, "agreement_signed", "fr218_in_progress") is True
    assert status_at_least("certified", "fr218_complete", version=1) is True
    assert {"FR.220", "FR.221"}.issubset(_fr_numbers(application))


def test_new_application_requires_fr218_branch_before_quotation():
    application = _application(version=FR218_BEFORE_COMMERCIAL_VERSION)

    assert uses_fr218_before_commercial(application) is True
    assert transition_matches_version(application, "in_planning", "quotation_sent") is False
    assert transition_matches_version(application, "in_planning", "fr218_in_progress") is True
    assert transition_matches_version(application, "fr218_complete", "quotation_sent") is True
    assert transition_matches_version(application, "fr218_complete", "stage1_in_progress") is False
    assert commercial_documents_unlocked(application) is False
    assert quotation_source_status(application) == "fr218_complete"


def test_new_application_early_package_excludes_quotation_and_agreement():
    fr_numbers = _fr_numbers(
        _application(version=FR218_BEFORE_COMMERCIAL_VERSION, status="fr218_in_progress")
    )

    assert "FR.218" in fr_numbers
    assert "FR.220" not in fr_numbers
    assert "FR.221" not in fr_numbers


def test_new_application_package_unlocks_commercial_documents_after_fr218():
    application = _application(
        version=FR218_BEFORE_COMMERCIAL_VERSION, status="fr218_complete"
    )
    fr_numbers = _fr_numbers(application)

    assert commercial_documents_unlocked(application) is True
    assert {"FR.218", "FR.220", "FR.221"}.issubset(fr_numbers)


def test_agreement_trigger_does_not_move_new_application_back_to_fr218():
    application = _application(
        version=FR218_BEFORE_COMMERCIAL_VERSION,
        status="agreement_signed",
    )
    db = SimpleNamespace(add=lambda _value: pytest.fail("no event should be added"))

    _trigger_fr218_phase(application, "tester", db)

    assert application.workflow_status == "agreement_signed"


@pytest.mark.parametrize("audit_type", ["surveillance", "surveillance_1", "surveillance_2"])
def test_surveillance_path_is_not_changed_by_version_two(audit_type):
    application = _application(
        version=FR218_BEFORE_COMMERCIAL_VERSION,
        audit_type=audit_type,
    )

    assert uses_fr218_before_commercial(application) is False
