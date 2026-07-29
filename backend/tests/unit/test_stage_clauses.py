from types import SimpleNamespace

import pytest

from audit_set.filler import STAGE_CLAUSES, build_team_members


STAGE_1_CLAUSES = {
    "ISO 9001:2015": "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.1-8.2-8.5 / 9.1-9.2-9.3",
    "ISO 14001:2015": "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.1 / 9.1-9.2-9.3",
    "ISO 45001:2018": "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3-5.4 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.2 / 9.1-9.2-9.3 / 10.1",
    "ISO 22000:2018": "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.1-8.2-8.5-8.7-8.8 / 9.2-9.3",
    "ISO/IEC 27001:2022": "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2 / Annex A: 5-6-7-8",
    "ISO 50001:2018": "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3-6.4-6.5-6.6 / 7.2-7.3-7.5 / 8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    "ISO 13485:2016": "4.1-4.2 / 5.1-5.2-5.3-5.4-5.5-5.6 / 6.1-6.2-6.3-6.4 / 7.1-7.2-7.3-7.4-7.5-7.6 / 8.1-8.2-8.3-8.4-8.5",
    "ISO 37001:2016": "4.1-4.2-4.3-4.4-4.5 / 5.2-5.3 / 6.1-6.2 / 7.2-7.3-7.5 / 8.1 / 9.1-9.2-9.3",
}


@pytest.mark.parametrize(("standard", "clauses"), STAGE_1_CLAUSES.items())
def test_stage_1_clauses_match_fr222(standard, clauses):
    assert STAGE_CLAUSES[(standard, "stage_1")] == clauses


def test_stage_1_team_member_receives_stage_1_clauses():
    stage = SimpleNamespace(
        stage_type="stage_1",
        lead_auditor_id=7,
        lead_auditor_name="Lead Auditor",
        auditors=[],
        technical_experts=[],
    )

    members = build_team_members(stage, {}, ["QMS"])

    assert members == [
        {
            "name": "Lead Auditor",
            "person_standards": ["ISO 9001:2015"],
            "person_clauses": [STAGE_1_CLAUSES["ISO 9001:2015"]],
        }
    ]
