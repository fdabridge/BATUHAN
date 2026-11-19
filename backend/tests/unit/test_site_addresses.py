from types import SimpleNamespace
from datetime import datetime

from audit_set.schemas import AuditSetResponse
from site_addresses import additional_sites, is_primary_address


def test_primary_address_matches_formatting_and_extended_location():
    assert is_primary_address(
        "1 MAIN STREET — ISTANBUL",
        "1 Main Street, Istanbul",
    )
    assert is_primary_address(
        "1 Main Street, Istanbul, Turkey",
        "1 Main Street, Istanbul",
    )


def test_short_or_different_addresses_are_not_treated_as_primary():
    assert not is_primary_address("Istanbul", "Istanbul, Turkey")
    assert not is_primary_address(
        "2 Warehouse Road, Gebze",
        "1 Main Street, Istanbul",
    )


def test_additional_sites_preserves_dicts_and_objects_but_removes_main_facility():
    main = {"name": "Head office", "address": "1 Main Street, Istanbul, Turkey"}
    warehouse = {"name": "Warehouse", "address": "2 Warehouse Road, Gebze"}
    laboratory = SimpleNamespace(name="Laboratory", address="3 Lab Avenue, Ankara")

    assert additional_sites(
        [main, warehouse, laboratory],
        "1 Main Street, Istanbul",
    ) == [warehouse, laboratory]


def test_audit_set_response_exposes_only_additional_sites_for_legacy_records():
    now = datetime(2026, 11, 19)
    response = AuditSetResponse.model_validate({
        "id": "case-1",
        "plan_number": 1700,
        "status": "planning",
        "company_name": "Example Co",
        "company_address": "1 Main Street, Istanbul",
        "sites": [
            {"name": "Main", "address": "1 Main Street, Istanbul, Turkey"},
            {"name": "Warehouse", "address": "2 Warehouse Road, Gebze"},
        ],
        "standards": ["QMS"],
        "audit_type": "initial",
        "cycle_number": 1,
        "accreditation_body": "UAF",
        "scope_tr": None,
        "scope_en": "Manufacturing",
        "stages": [],
        "created_at": now,
        "updated_at": now,
        "effective_employees": None,
        "man_day_result": None,
        "ea_code": None,
        "ea_category": None,
        "certification_fee": None,
        "surveillance_fee": None,
    })

    assert [site.address for site in response.sites] == ["2 Warehouse Road, Gebze"]
