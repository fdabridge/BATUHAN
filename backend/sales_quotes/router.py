from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from audit_set.apply_router import ClientApplicationSchema
from auth.db_models import PlatformUser
from auth.dependencies import require_role
from calculator.advanced import AdvancedCalculationRequest, AdvancedSiteInput, calculate_advanced

from .documents import build_agreement, build_quotation
from .models import SalesQuotationCase, SalesQuotationDocument, get_db


router = APIRouter(prefix="/sales-quotations", tags=["sales quotations"])
require_sales_manager = require_role("sales_manager")


class CommercialDetails(BaseModel):
    solicitation_source: str = "direct_inquiry"
    solicitation_method: str = "email"
    solicitation_date: str = ""
    solicitation_reference: str = ""
    coverage: Literal["single_audit", "three_year_cycle", "custom"] = "three_year_cycle"
    coverage_label: str = "Three-year certification cycle"
    included_stage_keys: list[str] = Field(default_factory=lambda: [
        "initial_stage_1", "initial_stage_2", "surveillance_1", "surveillance_2",
    ])
    notes: str = ""


class DayLine(BaseModel):
    key: str
    label: str
    recommended_days: float = Field(ge=0)
    quoted_days: float = Field(ge=0)
    override_reason: str = ""

    @model_validator(mode="after")
    def override_requires_reason(self):
        if abs(self.recommended_days - self.quoted_days) > 0.001 and len(self.override_reason.strip()) < 5:
            raise ValueError("A reason is required whenever calculated audit days are overridden.")
        return self


class PricingLine(BaseModel):
    key: str
    label: str
    day_rate: float = Field(ge=0)
    amount: float = Field(ge=0)


class PricingDetails(BaseModel):
    currency: str = Field(default="USD", min_length=3, max_length=3)
    line_items: list[PricingLine] = Field(default_factory=list)
    application_fee: float = Field(default=0, ge=0)
    certificate_fee: float = Field(default=0, ge=0)
    travel_fee: float = Field(default=0, ge=0)
    other_fee: float = Field(default=0, ge=0)
    discount: float = Field(default=0, ge=0)


class QuotePreparation(BaseModel):
    day_breakdown: list[DayLine]
    commercial_details: CommercialDetails
    pricing: PricingDetails


def _owned(case_id: str, user: PlatformUser, db: Session) -> SalesQuotationCase:
    case = db.query(SalesQuotationCase).filter_by(id=case_id, owner_user_id=user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Sales quotation case not found")
    return case


def _document_meta(document: SalesQuotationDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "kind": document.kind,
        "revision": document.revision,
        "file_name": document.file_name,
        "created_at": document.created_at,
    }


def _case_out(case: SalesQuotationCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "company_name": case.company_name,
        "representative_name": case.representative_name,
        "representative_email": case.representative_email,
        "status": case.status,
        "application_data": case.application_data,
        "calculation_result": case.calculation_result,
        "day_breakdown": case.day_breakdown,
        "commercial_details": case.commercial_details,
        "pricing": case.pricing,
        "quotation_revision": case.quotation_revision,
        "documents": [_document_meta(doc) for doc in case.documents],
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def _advanced_request(application: dict[str, Any], audit_type: str) -> AdvancedCalculationRequest:
    sites = [
        AdvancedSiteInput(
            id=f"site-{index + 1}",
            name=site.get("name", ""),
            address=site.get("address", ""),
            process_description=site.get("process", ""),
            employee_count=max(int(site.get("employee_count", 0) or 0), 0),
        )
        for index, site in enumerate(application.get("site_details") or [])
    ]
    standards = [str(value) for value in application.get("standards", [])]
    return AdvancedCalculationRequest(
        organization_name=application.get("company_name", ""),
        scope=application.get("scope_description") or "Scope pending commercial confirmation",
        standards=standards,
        audit_type=audit_type,
        accreditation_body="UAF",
        full_time_personnel=max(int(application.get("full_time_employees", 0) or application.get("total_employees", 0) or 1), 0),
        part_time_personnel=max(int(application.get("part_time_employees", 0) or 0), 0),
        subcontractors=max(int(application.get("subcontractor_employees", 0) or 0), 0),
        seasonal_temporary_personnel=max(int(application.get("seasonal_employees", 0) or 0), 0),
        shift_count=max(int(application.get("shift_count", 1) or 1), 1),
        same_process_all_shifts=bool(application.get("shift_same_process", False)),
        sites=sites,
        food_chain_categories=application.get("fsms_food_chain_categories") or [],
        fsms_haccp_studies=application.get("fsms_haccp_studies"),
        fsms_offsite_storage_count=int(application.get("fsms_offsite_storage_count", 0) or 0),
        fsms_separate_head_office=bool(application.get("fsms_separate_head_office", False)),
        fsms_fssc22000=bool(application.get("fsms_fssc22000", False)),
        annual_energy_tj=application.get("enms_annual_energy_tj"),
        num_energy_types=application.get("enms_num_energy_types"),
        num_seus=application.get("enms_num_seus"),
    )


def _pricing_payload(pricing: PricingDetails, days: list[DayLine]) -> dict[str, Any]:
    day_map = {line.key: line.quoted_days for line in days}
    items = []
    for line in pricing.line_items:
        amount = round(day_map.get(line.key, 0) * line.day_rate, 2)
        items.append({**line.model_dump(), "amount": amount})
    audit_subtotal = round(sum(line["amount"] for line in items), 2)
    extras = round(pricing.application_fee + pricing.certificate_fee + pricing.travel_fee + pricing.other_fee, 2)
    grand_total = round(max(0, audit_subtotal + extras - pricing.discount), 2)
    return {
        **pricing.model_dump(exclude={"line_items"}),
        "currency": pricing.currency.upper(),
        "line_items": items,
        "audit_subtotal": audit_subtotal,
        "additional_fees_total": extras,
        "grand_total": grand_total,
    }


@router.post("")
def create_case(
    application: ClientApplicationSchema,
    user: PlatformUser = Depends(require_sales_manager),
    db: Session = Depends(get_db),
):
    case = SalesQuotationCase(
        owner_user_id=user.id,
        company_name=application.company_name,
        representative_name=application.representative_name,
        representative_email=application.representative_email,
        application_data=application.model_dump(mode="json"),
        status="draft",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.get("")
def list_cases(
    user: PlatformUser = Depends(require_sales_manager),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SalesQuotationCase)
        .filter_by(owner_user_id=user.id)
        .order_by(SalesQuotationCase.updated_at.desc())
        .all()
    )
    return [_case_out(row) for row in rows]


@router.get("/{case_id}")
def get_case(case_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    return _case_out(_owned(case_id, user, db))


@router.post("/{case_id}/calculate")
def calculate_case(case_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    case = _owned(case_id, user, db)
    try:
        initial = calculate_advanced(_advanced_request(case.application_data, "initial"))
        surveillance = calculate_advanced(_advanced_request(case.application_data, "surveillance"))
        recertification = calculate_advanced(_advanced_request(case.application_data, "recertification"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = {
        "initial": initial.model_dump(mode="json"),
        "surveillance": surveillance.model_dump(mode="json"),
        "recertification": recertification.model_dump(mode="json"),
        "calculated_at": datetime.utcnow().isoformat(),
    }
    lines = [
        {"key": "initial_stage_1", "label": "Initial certification · Stage 1", "recommended_days": initial.stage_1_time or 0, "quoted_days": initial.stage_1_time or 0, "override_reason": ""},
        {"key": "initial_stage_2", "label": "Initial certification · Stage 2", "recommended_days": initial.stage_2_time or initial.final_audit_time, "quoted_days": initial.stage_2_time or initial.final_audit_time, "override_reason": ""},
        {"key": "surveillance_1", "label": "Surveillance 1", "recommended_days": surveillance.final_audit_time, "quoted_days": surveillance.final_audit_time, "override_reason": ""},
        {"key": "surveillance_2", "label": "Surveillance 2", "recommended_days": surveillance.final_audit_time, "quoted_days": surveillance.final_audit_time, "override_reason": ""},
        {"key": "recertification", "label": "Recertification", "recommended_days": recertification.final_audit_time, "quoted_days": recertification.final_audit_time, "override_reason": ""},
    ]
    case.calculation_result = result
    case.day_breakdown = lines
    case.status = "calculated"
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.put("/{case_id}/prepare")
def prepare_case(body: QuotePreparation, case_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    case = _owned(case_id, user, db)
    if not case.calculation_result:
        raise HTTPException(status_code=409, detail="Calculate audit days before preparing a quotation")
    case.day_breakdown = [line.model_dump(mode="json") for line in body.day_breakdown]
    case.commercial_details = body.commercial_details.model_dump(mode="json")
    case.pricing = _pricing_payload(body.pricing, body.day_breakdown)
    case.status = "quotation_ready"
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.post("/{case_id}/quotation")
def generate_quotation(case_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    case = _owned(case_id, user, db)
    if case.status == "agreed":
        raise HTTPException(status_code=409, detail="An agreed sales case is closed. Start a new case for a new commercial offer.")
    if not case.pricing or not case.day_breakdown:
        raise HTTPException(status_code=409, detail="Complete days, commercial details and pricing first")
    case.quotation_revision += 1
    content = build_quotation(case)
    doc = SalesQuotationDocument(
        case_id=case.id,
        kind="quotation",
        revision=case.quotation_revision,
        file_name=f"IFC_Quotation_{case.company_name}_R{case.quotation_revision}.docx".replace("/", "-"),
        content=content,
    )
    case.status = "quotation_generated"
    db.add(doc)
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.post("/{case_id}/reject")
def reject_quotation(case_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    case = _owned(case_id, user, db)
    if case.status != "quotation_generated":
        raise HTTPException(status_code=409, detail="Only the current generated quotation can be marked rejected")
    case.status = "quotation_rejected"
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.post("/{case_id}/approve")
def approve_quotation(case_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    case = _owned(case_id, user, db)
    if case.status != "quotation_generated":
        raise HTTPException(status_code=409, detail="Only the current generated quotation can be approved")
    content = build_agreement(case)
    agreement_revision = 1 + db.query(SalesQuotationDocument).filter_by(case_id=case.id, kind="agreement").count()
    doc = SalesQuotationDocument(
        case_id=case.id,
        kind="agreement",
        revision=agreement_revision,
        file_name=f"IFC_Agreement_{case.company_name}_R{agreement_revision}.docx".replace("/", "-"),
        content=content,
    )
    case.status = "agreed"
    db.add(doc)
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.get("/{case_id}/documents/{document_id}")
def download_document(case_id: str, document_id: str, user: PlatformUser = Depends(require_sales_manager), db: Session = Depends(get_db)):
    _owned(case_id, user, db)
    document = db.query(SalesQuotationDocument).filter_by(id=document_id, case_id=case_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return StreamingResponse(
        BytesIO(document.content),
        media_type=document.content_type,
        headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'},
    )
