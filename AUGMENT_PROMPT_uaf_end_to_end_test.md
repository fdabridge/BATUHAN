# Augment Prompt — UAF End-to-End Integration Test

## Goal

Run a full end-to-end test of the UAF audit package generation pipeline using a synthetic but realistic audit set. The test must verify:

1. The backend generates a ZIP with all expected documents
2. Every rendered `.docx` contains zero leftover `{{ }}` or `{%` tags (all placeholders filled)
3. Conditional rows work correctly (site rows, standard rows, per-person documents)
4. Date math is correct (plan_date, report_date, estimated cycle dates)
5. The download endpoint responds correctly

Do NOT use production data. Use the synthetic fixture below.

---

## Synthetic Test Fixture

Use this data to create (or mock) an `AuditSet` and its stages. You can either:
- Insert directly into the test DB via a pytest fixture, OR
- Construct the ORM objects in memory and pass them directly to `build_audit_set_zip()`

```python
from datetime import date

AUDIT_SET = {
    "company_name": "Acme Foods Ltd",
    "company_address": "123 Industrial Blvd, Istanbul, Turkey",
    "country": "Turkey",
    "phone": "+90 212 000 0000",
    "email": "info@acmefoods.com",
    "website": "www.acmefoods.com",
    "representative": "Ahmet Yılmaz",
    "standards": ["QMS", "EMS"],            # ISO 9001 + ISO 14001 — tests 2-standard rows
    "audit_type": "initial",
    "accreditation_body": "UAF",
    "scope_en": "Manufacturing of packaged food products",
    "non_applicable_clauses": "8.3 Design and Development",
    "audit_language": "Turkish",
    "document_language": "english",
    "plan_number": "IFC-2026-001",
    "certification_fee": 5000,
    "surveillance_fee": 2500,
    "ea_code": "EA 3",
    "ea_category": "Food and Drink",
    "ea_technical_area": "Manufacturing",
    "effective_employees": 85,
    "risk_category": "Low",
    "scope_integration_level": "Partial",
    "personnel": {
        "full_time": 70,
        "part_time": 10,
        "unskilled": 5,
        "seasonal": 0,
        "subcontractors": 8,
        "shift_count": 2,
        "shift_same_process": True,
        "shift_1_count": 45,
        "shift_2_count": 40,
        "shift_3_count": 0,
        "repetitive_roles": [{"role": "Line Worker", "employee_count": 30}],
        "office_employees": 55,       # written back by calculator
        "repetitive_employees": 30,   # written back by calculator
    },
    "sites": [
        {
            "address": "123 Industrial Blvd, Istanbul, Turkey",
            "process_description": "Primary production and packaging",
            "employee_count": 70,
            "energy_tj": 12.5,
            "energy_types": 3,
            "seu_count": 4,
        },
        {
            "address": "45 Warehouse St, Gebze, Turkey",  # 2nd site — tests conditional site rows
            "process_description": "Storage and distribution",
            "employee_count": 15,
            "energy_tj": 2.1,
            "energy_types": 1,
            "seu_count": 1,
        },
    ],
    "integration_level": {
        "document_management": True,
        "management_review": True,
        "internal_audit": True,
        "policy_objectives": True,
        "process_approach": False,
        "improvement_mechanism": True,
        "management_support": False,
        "risk_based_thinking": True,
    },  # 6 out of 8 = 75%
    "man_day_result": {
        "standard_results": [
            {
                "standard": "ISO 9001:2015",
                "category": "Low",
                "eps": 85,
                "base_init": 4.0,
                "base_ph1": 1.5,
                "base_ph2": 2.5,
                "base_surv": 1.5,
                "base_recert": 3.0,
                "base_recert_ph1": 1.0,
                "base_recert_ph2": 2.0,
                "site_addition": 0.5,
                "haccp_addition": None,
            },
            {
                "standard": "ISO 14001:2015",
                "category": "Low",
                "eps": 85,
                "base_init": 1.5,
                "base_ph1": 0.5,
                "base_ph2": 1.0,
                "base_surv": 0.5,
                "base_recert": 1.0,
                "base_recert_ph1": 0.5,
                "base_recert_ph2": 0.5,
                "site_addition": 0.0,
                "haccp_addition": None,
            },
        ],
        "combined_base": 5.5,
        "integration_reduction": 0.5,
        "reporting_reduction": 0.0,
        "final_total": 5.0,
        "final_ph1": 2.0,
        "final_ph2": 3.0,
        "final_surv1": 1.5,
        "final_surv2": 1.5,
        "final_recert": 4.0,
        "final_recert_ph1": 1.5,
        "final_recert_ph2": 2.5,
        "total_employees": 85,
        "office_employees": 55,
        "repetitive_employees": 30,
        "eps": 85,
        "enms_k": None,
        "enms_complexity": None,
        "enms_range_ec": None,
        "enms_range_et": None,
        "enms_range_seu": None,
        "enms_fec": None,
        "enms_fet": None,
        "enms_fseu": None,
        "isms_business_score": None,
        "isms_it_score": None,
        "scope_integration_level": "Partial",
        "md11_floor_applied": False,
        "md11_floor_value": None,
        "fssc_reporting_surcharge": 0.0,
        "warning": None,
    },
}

STAGE_1 = {
    "stage_type": "stage_1",
    "stage_order": 1,
    "audit_date_start": date(2026, 6, 10),
    "audit_date_end": date(2026, 6, 11),
    "audit_days": 2.0,
    "notification_date": date(2026, 4, 10),
    "lead_auditor_id": 1,
    "lead_auditor_name": "John Smith",
    "auditors": [
        {"id": 2, "name": "Jane Auditor", "covered_scope": {}},
    ],
    "technical_experts": [
        {"id": 3, "name": "Tom Expert", "covered_scope": {}},
    ],
    "observers": [],
}

STAGE_2 = {
    "stage_type": "stage_2",
    "stage_order": 2,
    "audit_date_start": date(2026, 7, 14),
    "audit_date_end": date(2026, 7, 16),
    "audit_days": 3.0,
    "notification_date": date(2026, 5, 14),
    "lead_auditor_id": 1,
    "lead_auditor_name": "John Smith",
    "auditors": [
        {"id": 2, "name": "Jane Auditor", "covered_scope": {}},
    ],
    "technical_experts": [],
    "observers": [],
}
```

---

## What to test

### Test 1 — Stage 1 ZIP contents

Call `build_audit_set_zip(audit_set, stage_1, template_dir)` where `template_dir` points to:
```
uaf_blank_set copy/9-14-45-22-5001/Initial Certification /Stage 1/
```

Assert the ZIP contains at minimum:
```
FR.218_...docx
FR.222_...docx
FR.223_...docx
FR.224_John_Smith.docx
FR.224_Jane_Auditor.docx
FR.224_Tom_Expert.docx
FR.211_John_Smith.docx
FR.211_Jane_Auditor.docx
FR.211_Tom_Expert.docx
FR.225_...docx
FR.230_...docx
FR.234_...docx
```

### Test 2 — Stage 2 ZIP contents

Call `build_audit_set_zip(audit_set, stage_2, template_dir)` where template_dir points to Stage 2.

Assert the ZIP contains:
```
FR.229_...docx
FR.231_...docx
FR.231-1_...docx
FR.232_...docx
FR.232-1_...docx (if applicable)
FR.224_John_Smith.docx
FR.224_Jane_Auditor.docx   (no TE in stage 2 → only 2 copies)
FR.211_John_Smith.docx
FR.211_Jane_Auditor.docx
```

Assert there is NO `FR.224_Tom_Expert.docx` (TE is not on Stage 2 team).

### Test 3 — Zero leftover placeholders

For every `.docx` in both ZIPs, extract its text and assert:
```python
assert '{{' not in full_text, f"Unfilled placeholder in {filename}"
assert '{%' not in full_text, f"Unfilled tag in {filename}"
```

### Test 4 — Conditional rows work

Open the rendered FR.222 with python-docx and verify:
- The ISO 9001:2015 clause block is present (QMS is in standards)
- The ISO 14001:2015 clause block is present (EMS is in standards)
- No ISO 45001:2018, ISO 22000:2018, etc. rows appear (those standards are not in scope)
- The second site row IS present (we have 2 sites)
- There is no third site row (we only have 2 sites)

### Test 5 — Date math

Open the rendered FR.222 and verify:
- `plan_date` = 2026-06-03 (10 June minus 5 working days)
- `surv1_estimated_date` = 2026-07-15 (Stage 2 end 16 Jul + 1 year - 1 day)
- `surv2_estimated_date` = 2026-07-14 (surv1 + 1 year - 1 day)
- `recert_estimated_date` = 2026-07-13 (surv2 + 1 year - 1 day)
- `report_date` in FR.231-1 = 2026-07-17 (Stage 2 end + 1 day)
- `integration_pct` = 75 (6 of 8 true)

### Test 6 — Download endpoint

Make a GET request to `/audit-sets/{id}/stages/{stage_id}/download` with a real (seeded) audit set and stage. Assert:
- HTTP 200
- Content-Type: `application/zip`
- Response body is a valid ZIP (can be opened)
- ZIP is non-empty

---

## How to run

Write this as a pytest file at `backend/tests/test_uaf_pipeline.py`. Use the synthetic fixture data above — no network calls, no real DB required for tests 1–5. Test 6 requires the test DB (use the existing conftest pattern).

After all tests pass, report:
- Which tests passed
- The full file listing of both ZIPs
- Any placeholder that was NOT filled (if any) — list the filename and the unfilled tag
- Whether the RENDER_ERRORS.txt is empty
