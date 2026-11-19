from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth.dependencies import get_current_user
from sales_quotes.models import Base, get_db
from sales_quotes.router import router


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="sales-user-1", role="sales_manager",
    )
    yield TestClient(app), app
    Base.metadata.drop_all(engine)
    engine.dispose()


def application(company="Example Components LLC"):
    return {
        "company_name": company,
        "company_address": "100 Industry Road",
        "city": "Chicago",
        "country": "United States",
        "representative_name": "Alex Example",
        "representative_email": "alex@example.test",
        "standards": ["QMS", "EMS"],
        "audit_type": "initial",
        "scope_description": "Manufacturing and sale of metal components",
        "full_time_employees": 40,
        "part_time_employees": 4,
        "subcontractor_employees": 2,
        "seasonal_employees": 0,
        "shift_count": 2,
        "site_details": [],
    }


def test_sales_case_is_private_and_does_not_create_operational_records(client):
    http, app = client
    created = http.post("/sales-quotations", json=application())
    assert created.status_code == 200, created.text
    case = created.json()
    assert case["status"] == "draft"
    assert http.get("/sales-quotations").json()[0]["company_name"] == "Example Components LLC"

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="another-sales-user", role="sales_manager",
    )
    assert http.get(f"/sales-quotations/{case['id']}").status_code == 404
    assert http.get("/sales-quotations").json() == []

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="planner", role="planner",
    )
    assert http.get("/sales-quotations").status_code == 403


def test_full_calculate_quote_reject_and_approve_flow(client):
    http, _ = client
    case = http.post("/sales-quotations", json=application()).json()
    calculated = http.post(f"/sales-quotations/{case['id']}/calculate")
    assert calculated.status_code == 200, calculated.text
    case = calculated.json()
    assert case["status"] == "calculated"
    assert set(case["calculation_result"]) >= {"initial", "surveillance", "recertification"}
    assert len(case["day_breakdown"]) == 5

    days = case["day_breakdown"]
    days[0]["quoted_days"] += 0.5
    bad = http.put(f"/sales-quotations/{case['id']}/prepare", json={
        "day_breakdown": days,
        "commercial_details": {},
        "pricing": {"currency": "USD", "line_items": []},
    })
    assert bad.status_code == 422
    days[0]["override_reason"] = "Additional readiness review required"
    included = [row["key"] for row in days[:4]]
    prepared = http.put(f"/sales-quotations/{case['id']}/prepare", json={
        "day_breakdown": days,
        "commercial_details": {
            "solicitation_source": "direct_inquiry",
            "solicitation_method": "email",
            "coverage": "three_year_cycle",
            "included_stage_keys": included,
        },
        "pricing": {
            "currency": "USD",
            "line_items": [
                {"key": row["key"], "label": row["label"], "day_rate": 1000, "amount": 0}
                for row in days[:4]
            ],
            "application_fee": 250,
        },
    })
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["pricing"]["grand_total"] > 250

    generated = http.post(f"/sales-quotations/{case['id']}/quotation")
    assert generated.status_code == 200, generated.text
    case = generated.json()
    assert case["quotation_revision"] == 1
    quotation = next(doc for doc in case["documents"] if doc["kind"] == "quotation")
    downloaded = http.get(f"/sales-quotations/{case['id']}/documents/{quotation['id']}")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"PK")

    assert http.post(f"/sales-quotations/{case['id']}/reject").json()["status"] == "quotation_rejected"
    assert http.post(f"/sales-quotations/{case['id']}/approve").status_code == 409
    regenerated = http.post(f"/sales-quotations/{case['id']}/quotation")
    assert regenerated.status_code == 200
    assert regenerated.json()["quotation_revision"] == 2
    approved = http.post(f"/sales-quotations/{case['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "agreed"
    assert [doc["kind"] for doc in approved.json()["documents"]].count("quotation") == 2
    assert {doc["kind"] for doc in approved.json()["documents"]} == {"quotation", "agreement"}
