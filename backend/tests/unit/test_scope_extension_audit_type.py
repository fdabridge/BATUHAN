from types import SimpleNamespace

import pytest

from audit_plan.clause_map import normalize_audit_type
from audit_set.apply_router import ALLOWED_AUDIT_TYPES
from audit_set.audit_types import audit_type_display, is_surveillance_like_audit_type
from audit_set.service import _create_auto_stages


@pytest.mark.parametrize(
    "audit_type",
    ["scope_extension", "surveillance_1_scope_extension"],
)
def test_scope_extension_types_are_accepted_and_surveillance_like(audit_type):
    assert audit_type in ALLOWED_AUDIT_TYPES
    assert is_surveillance_like_audit_type(audit_type) is True


def test_scope_extension_labels_remain_distinct():
    assert audit_type_display("scope_extension") == "Scope Extension"
    assert audit_type_display("surveillance_1_scope_extension") == "Surveillance 1 + Scope Extension"


@pytest.mark.parametrize(
    "raw",
    ["Scope Extension", "scope_extension", "Surveillance 1 + Scope Extension", "surveillance_1_scope_extension"],
)
def test_scope_extension_uses_surveillance_one_clause_map(raw):
    assert normalize_audit_type(raw) == "Surveillance 1"


@pytest.mark.parametrize(
    "audit_type",
    ["scope_extension", "surveillance_1_scope_extension"],
)
def test_scope_extension_creates_one_surveillance_stage(audit_type):
    added = []
    db = SimpleNamespace(add=added.append)
    audit_set = SimpleNamespace(id="scope-1", audit_type=audit_type)

    _create_auto_stages(db, audit_set, {"final_surv1": 1.5})

    assert len(added) == 1
    assert added[0].stage_type == "surveillance"
    assert added[0].stage_order == 1
    assert added[0].audit_days == 1.5
