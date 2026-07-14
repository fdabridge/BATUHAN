#!/usr/bin/env python3
"""
Create isolated Certiva demo data.

Run from the backend directory:
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --reset

This script is intentionally standalone. It is never imported by the app and
only creates/deletes rows with demo usernames/emails and DEMO plan references.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from audit_set.db_models import (  # noqa: E402
    AuditDocumentSignature,
    AuditSet,
    AuditSetAuditReport,
    AuditSetAuditorAssessment,
    AuditSetCommitteeMember,
    AuditSetFR233Record,
    AuditSetImpartialityDeclaration,
    AuditSetMeetingAttendee,
    AuditSetNCDecision,
    AuditSetNCEvidence,
    AuditSetNCForm,
    AuditSetNCItem,
    AuditSetNCReview,
    AuditSetSharedDocument,
    AuditSetStage,
    AuditSetStatusEvent,
    ClientOrgEmployee,
    DocumentSignatureField,
    SessionLocal as AuditSessionLocal,
    VisualSignaturePlacement,
    create_tables as create_audit_tables,
)
from auditors.models import (  # noqa: E402
    Auditor,
    AuditorStandardQualification,
    SessionLocal as AuditorSessionLocal,
    create_tables as create_auditor_tables,
)
from auth.db_models import (  # noqa: E402
    PlatformUser,
    SessionLocal as AuthSessionLocal,
    UserSignature,
    create_tables as create_auth_tables,
)
from auth.service import hash_password  # noqa: E402


DEMO_PASSWORD = "Demo1234!"
DEMO_PLAN_START = 2025001
PLACEHOLDER_SIG_IMAGE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@dataclass(frozen=True)
class DemoUser:
    key: str
    username: str
    email: str
    full_name: str
    role: str
    auditor_role: str | None = None
    qualifications: tuple[tuple[str, tuple[str, ...], str], ...] = ()


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("admin", "demo_admin", "demo_admin@certiva.com", "Demo Admin", "admin"),
    DemoUser("planner", "demo_planner", "demo_planner@certiva.com", "Ayşe Kaya (Planner)", "planner"),
    DemoUser("us_planner", "demo_usplanner", "demo_usplanner@certiva.com", "Mehmet Yıldız (US Planner)", "planner_us"),
    DemoUser("cm", "demo_cm", "demo_cm@certiva.com", "Dr. Hasan Eryılmaz (CM)", "certification_manager"),
    DemoUser(
        "lead", "demo_lead", "demo_lead@certiva.com", "Çiğdem Ergincan (Lead Auditor)", "auditor",
        auditor_role="Lead Auditor",
        qualifications=(
            ("ISO 9001", ("EA 17", "EA 28", "EA 30"), "Lead Auditor"),
            ("ISO 14001", ("EA 17", "EA 28", "EA 30"), "Lead Auditor"),
            ("ISO 45001", ("EA 17", "EA 28", "EA 30"), "Lead Auditor"),
        ),
    ),
    DemoUser(
        "auditor2", "demo_auditor2", "demo_auditor2@certiva.com", "Tarık Şahin (Auditor)", "auditor",
        auditor_role="Team Auditor",
        qualifications=(("ISO 9001", ("EA 17", "EA 29"), "Team Auditor"),),
    ),
    DemoUser(
        "te", "demo_te", "demo_te@certiva.com", "Prof. Leyla Arslan (Technical Expert)", "auditor",
        auditor_role="Technical Expert",
        qualifications=(("ISO 9001", ("EA 17",), "Technical Expert"),),
    ),
    DemoUser(
        "committee_chair", "demo_committee_chair", "demo_chair@certiva.com", "Kemal Doğan (Committee Chair)", "auditor",
        auditor_role="Lead Auditor",
        qualifications=(
            ("ISO 9001", ("EA 17", "EA 28"), "Lead Auditor"),
            ("ISO 14001", ("EA 17", "EA 28"), "Lead Auditor"),
        ),
    ),
    DemoUser(
        "committee_member", "demo_committee_member", "demo_member@certiva.com", "Selin Yurt (Committee Member)", "auditor",
        auditor_role="Team Auditor",
        qualifications=(("ISO 9001", ("EA 17",), "Team Auditor"),),
    ),
    DemoUser("consultant", "demo_consultant", "demo_consultant@certiva.com", "Barış Güneş (Consultant)", "consultant"),
    DemoUser("client", "demo_client", "demo_client@certiva.com", "Ali Öztürk (Client Contact)", "client"),
    DemoUser("client2", "demo_client2", "demo_client2@certiva.com", "Sara Demir (Client 2 Contact)", "client"),
)


def now() -> datetime:
    return datetime.utcnow()


def days_ago(days: int) -> datetime:
    return now() - timedelta(days=days)


def today_plus(days: int) -> date:
    return date.today() + timedelta(days=days)


def new_id() -> str:
    return str(uuid.uuid4())


def commit_quietly(db: Session) -> None:
    db.commit()


def create_platform_user(auth_db: Session, spec: DemoUser, auditor_id: str | None = None) -> PlatformUser:
    existing = auth_db.query(PlatformUser).filter(
        or_(PlatformUser.username == spec.username, PlatformUser.email == spec.email)
    ).first()
    if existing:
        return existing
    user = PlatformUser(
        id=new_id(),
        email=spec.email,
        username=spec.username,
        password_hash=hash_password(DEMO_PASSWORD),
        full_name=spec.full_name,
        role=spec.role,
        auditor_id=auditor_id,
        is_active=True,
    )
    auth_db.add(user)
    auth_db.flush()
    auth_db.add(UserSignature(
        id=new_id(),
        user_id=user.id,
        image_data=PLACEHOLDER_SIG_IMAGE,
        source="uploaded",
    ))
    return user


def create_auditor(auditor_db: Session, spec: DemoUser) -> Auditor | None:
    if spec.role != "auditor":
        return None
    existing = auditor_db.query(Auditor).filter(Auditor.email == spec.email).first()
    if existing:
        return existing
    all_ea = sorted({code for _, codes, _ in spec.qualifications for code in codes})
    auditor = Auditor(
        id=new_id(),
        name=spec.full_name.split(" (", 1)[0],
        email=spec.email,
        role=spec.auditor_role or "Team Auditor",
        field_of_expertise="DEMO profile for promotional walkthroughs.",
        ea_codes=all_ea,
        accreditation_bodies=["UAF"],
        is_active=True,
    )
    auditor_db.add(auditor)
    auditor_db.flush()
    for standard, ea_codes, depth in spec.qualifications:
        auditor_db.add(AuditorStandardQualification(
            auditor_id=auditor.id,
            standard_code=standard,
            accreditation_body="UAF",
            ea_codes=list(ea_codes),
            technical_depth=depth,
            experience_years=5,
            is_qualified=True,
            last_training_date="2026-01-15",
            last_verified_date="2026-06-01",
        ))
    return auditor


def create_users(auth_db: Session, auditor_db: Session) -> tuple[dict[str, PlatformUser], dict[str, Auditor]]:
    auditors: dict[str, Auditor] = {}
    for spec in DEMO_USERS:
        auditor = create_auditor(auditor_db, spec)
        if auditor:
            auditors[spec.key] = auditor
    commit_quietly(auditor_db)

    users: dict[str, PlatformUser] = {}
    for spec in DEMO_USERS:
        auditor = auditors.get(spec.key)
        users[spec.key] = create_platform_user(auth_db, spec, auditor.id if auditor else None)
    commit_quietly(auth_db)
    return users, auditors


def acme_base(users: dict[str, PlatformUser], n: int, status: str, title: str) -> AuditSet:
    return AuditSet(
        id=new_id(),
        plan_number=DEMO_PLAN_START + n - 1,
        client_reference=f"DEMO-2025-{n:03d}",
        consultant_id=users["consultant"].id if n in {1, 2} else None,
        status="planning" if status != "pending_review" else "draft",
        company_name=f"DEMO — Acme Metal Works Ltd. ({title})",
        company_address="Organize Sanayi Bölgesi, Bursa, Turkey",
        country="Turkey",
        city="Bursa",
        phone="+90 224 000 0000",
        email="info@acmemetal.demo",
        website="https://demo.acmemetal.local",
        representative="Ali Öztürk",
        standards=["QMS"],
        audit_type="initial",
        cycle_number=1,
        accreditation_body="UAF",
        scope_tr="Otomotiv sektörü için hassas metal bileşenlerin tasarımı, üretimi ve tedariki.",
        scope_en=(
            "Design, manufacture and supply of precision metal components for the automotive sector, "
            "including machined parts, stamped brackets, and welded assemblies."
        ),
        non_applicable_clauses="8.3 design and development may be not applicable if customer specifications control all design outputs.",
        personnel={"full_time": 48, "part_time": 0, "subcontractors": 0, "shift_count": 1},
        sites=[{"address": "Organize Sanayi Bölgesi, Bursa, Turkey", "process": "Machining and fabrication", "employee_count": 48}],
        integration_level={"document_management": True, "internal_audit": True, "management_review": True},
        effective_employees=48,
        risk_category="MEDIUM",
        required_scope={"ISO 9001": {"type": "ea", "codes": ["EA 17"], "risk": "Medium"}},
        ea_code="EA 17",
        ea_category="Basic metals and fabricated metal products",
        audit_language="Turkish",
        document_language="english",
        application_date=today_plus(-14),
        application_data={"demo": True},
        workflow_status=status,
        submitted_via_portal=True,
        created_at=days_ago(14),
        updated_at=days_ago(1),
    )


def greentech_base(users: dict[str, PlatformUser]) -> AuditSet:
    return AuditSet(
        id=new_id(),
        plan_number=DEMO_PLAN_START + 7,
        client_reference="DEMO-2025-008",
        status="complete",
        company_name="DEMO — GreenTech Energy A.Ş.",
        company_address="Maslak, İstanbul, Turkey",
        country="Turkey",
        city="İstanbul",
        phone="+90 212 000 0000",
        email="info@greentech.demo",
        representative="Sara Demir",
        standards=["EMS", "OHSMS"],
        audit_type="initial",
        cycle_number=1,
        accreditation_body="UAF",
        scope_en="Installation, operation and maintenance of solar energy systems for commercial and industrial facilities.",
        personnel={"full_time": 22, "part_time": 0, "subcontractors": 0, "shift_count": 1},
        sites=[{"address": "Maslak, İstanbul, Turkey", "process": "Solar energy service operations", "employee_count": 22}],
        effective_employees=22,
        risk_category="LOW",
        required_scope={
            "ISO 14001": {"type": "ea", "codes": ["EA 39"], "risk": "Low"},
            "ISO 45001": {"type": "ea", "codes": ["EA 39"], "risk": "Low"},
        },
        ea_code="EA 39",
        ea_category="Other services",
        audit_language="Turkish",
        document_language="english",
        workflow_status="certified",
        submitted_via_portal=True,
        cert_issued_date=today_plus(-5),
        cert_expiry_date=today_plus(1090),
        cert_status="active",
        created_at=days_ago(30),
        updated_at=days_ago(5),
    )


def add_status_event(db: Session, audit_set: AuditSet, to_status: str, by: str = "demo_seed", from_status: str | None = None) -> None:
    db.add(AuditSetStatusEvent(
        id=new_id(),
        audit_set_id=audit_set.id,
        from_status=from_status,
        to_status=to_status,
        triggered_by=by,
        triggered_at=audit_set.updated_at or now(),
        notes="DEMO seed state",
    ))


def add_doc(
    db: Session,
    audit_set: AuditSet,
    label: str,
    doc_type: str,
    *,
    stage_type: str | None = None,
    status: str = "released",
    direction: str = "cb_to_client",
    signed_at: datetime | None = None,
    assigned_auditor_id: str | None = None,
) -> AuditSetSharedDocument:
    safe_name = label.replace(" ", "_").replace("/", "_")
    doc = AuditSetSharedDocument(
        id=new_id(),
        audit_set_id=audit_set.id,
        label=label,
        document_type=doc_type,
        file_path=f"demo/placeholder/{audit_set.client_reference}/{safe_name}.docx",
        direction=direction,
        stage_type=stage_type,
        assigned_auditor_id=assigned_auditor_id,
        status=status,
        released_by=None,
        released_at=days_ago(5),
        signed_at=signed_at,
        created_at=days_ago(5),
    )
    db.add(doc)
    db.flush()
    return doc


def add_signature_slot(
    db: Session,
    audit_set: AuditSet,
    doc: AuditSetSharedDocument | None,
    role_label: str,
    user: PlatformUser | None,
    *,
    required: bool = True,
    signed_at: datetime | None = None,
    order_index: int = 0,
) -> AuditDocumentSignature:
    sig = AuditDocumentSignature(
        id=new_id(),
        audit_set_id=audit_set.id,
        document_id=doc.id if doc else None,
        document_type=doc.document_type if doc else role_label,
        signer_role_label=role_label,
        signer_user_id=user.id if user else None,
        signer_name=user.full_name if user else None,
        signer_email=user.email if user else None,
        required=required,
        order_index=order_index,
        signed_at=signed_at,
        signed_ip="127.0.0.1" if signed_at else None,
        created_at=days_ago(5),
    )
    db.add(sig)
    return sig


def add_vsp(
    db: Session,
    document_type: str,
    doc_id: str,
    sig_key: str,
    user: PlatformUser,
    *,
    signed_at: datetime | None = None,
) -> None:
    db.add(VisualSignaturePlacement(
        id=new_id(),
        document_type=document_type,
        doc_id=doc_id,
        sig_key=sig_key,
        user_id=user.id,
        signer_name=user.full_name,
        signature_image=PLACEHOLDER_SIG_IMAGE,
        signed_at=signed_at or days_ago(1),
        signed_ip="127.0.0.1",
        created_at=days_ago(2),
    ))


def add_stage(
    db: Session,
    audit_set: AuditSet,
    stage_type: str,
    order: int,
    users: dict[str, PlatformUser],
    auditors: dict[str, Auditor],
    *,
    status: str,
    start_offset: int,
    end_offset: int,
) -> AuditSetStage:
    stage = AuditSetStage(
        id=new_id(),
        audit_set_id=audit_set.id,
        stage_type=stage_type,
        stage_order=order,
        notification_date=today_plus(start_offset - 14),
        audit_date_start=today_plus(start_offset),
        audit_date_end=today_plus(end_offset),
        lead_auditor_id=auditors["lead"].id,
        lead_auditor_name=auditors["lead"].name,
        auditors=[{"id": auditors["auditor2"].id, "name": auditors["auditor2"].name, "ea_code": "EA 17", "standard": "ISO 9001"}],
        technical_experts=[{"id": auditors["te"].id, "name": auditors["te"].name, "ea_code": "EA 17", "standard": "ISO 9001"}],
        audit_days=1.5 if stage_type == "stage_1" else 2.0,
        status=status,
    )
    db.add(stage)
    return stage


def add_acme_roster(db: Session, client_user: PlatformUser) -> None:
    for name, role, _email in (
        ("Fatma Yılmaz", "Quality Manager", "fatma@acmemetal.com"),
        ("Bülent Koç", "Production Manager", "bulent@acmemetal.com"),
        ("Zeynep Avcı", "HSE Coordinator", "zeynep@acmemetal.com"),
    ):
        db.add(ClientOrgEmployee(
            id=new_id(),
            client_user_id=client_user.id,
            full_name=name,
            role_title=role,
            signature_data=PLACEHOLDER_SIG_IMAGE,
            signature_source="uploaded",
            is_active=True,
        ))


def add_stage_docs(db: Session, audit_set: AuditSet, users: dict[str, PlatformUser], stage_type: str, *, signed: bool = True) -> None:
    plan = add_doc(db, audit_set, f"FR.223 Audit Plan — {stage_type}", "audit_plan", stage_type=stage_type, status="signed" if signed else "released")
    meeting = add_doc(db, audit_set, f"FR.225 Opening/Closing Meeting — {stage_type}", "meeting_form", stage_type=stage_type, status="signed" if signed else "uploaded")
    team = add_doc(db, audit_set, f"FR.224 Audit Team Info — {stage_type}", "team_info", stage_type=stage_type, status="signed" if signed else "released", assigned_auditor_id=users["lead"].auditor_id)
    if signed:
        add_vsp(db, "shared_doc", plan.id, "ORG_REP", users["client"])
        add_vsp(db, "shared_doc", meeting.id, "ORG_OPENING_LEAD_AUDITOR", users["lead"])
        add_vsp(db, "shared_doc", meeting.id, "ORG_OPENING_AUDITOR_1", users["auditor2"])
        add_vsp(db, "shared_doc", team.id, "ASSIGNED_AUDITOR", users["lead"])


def add_report(
    db: Session,
    audit_set: AuditSet,
    users: dict[str, PlatformUser],
    stage_type: str,
    form: str,
    *,
    status: str,
    la_signed: bool,
    reviewer_signed: bool,
) -> AuditSetAuditReport:
    report = AuditSetAuditReport(
        id=new_id(),
        audit_set_id=audit_set.id,
        stage_type=stage_type,
        report_form=form,
        label=f"{form} Audit Report",
        file_path=f"demo/placeholder/{audit_set.client_reference}/{form}_{stage_type}.docx",
        file_name=f"{form}_{stage_type}_DEMO.docx",
        la_user_id=users["lead"].id,
        la_signed_at=days_ago(2) if la_signed else None,
        la_signed_ip="127.0.0.1" if la_signed else None,
        appointed_reviewer_user_id=users["committee_chair"].id if reviewer_signed else None,
        appointed_reviewer_signed_at=days_ago(1) if reviewer_signed else None,
        appointed_reviewer_signed_ip="127.0.0.1" if reviewer_signed else None,
        reviewer_user_id=users["cm"].id,
        reviewer_signed_at=days_ago(1) if reviewer_signed else None,
        reviewer_signed_ip="127.0.0.1" if reviewer_signed else None,
        status=status,
        uploaded_by=users["lead"].id,
        reviewer_auditor_id=users["committee_chair"].auditor_id,
        reviewer_auditor_name="Kemal Doğan",
        created_at=days_ago(3),
    )
    db.add(report)
    db.flush()
    if la_signed:
        add_vsp(db, "audit_report", report.id, "LEAD_AUDITOR", users["lead"], signed_at=days_ago(2))
    if reviewer_signed:
        add_vsp(db, "audit_report", report.id, "APPOINTED_REVIEWER", users["committee_chair"], signed_at=days_ago(1))
        add_vsp(db, "audit_report", report.id, "CB_CERT_MANAGER", users["cm"], signed_at=days_ago(1))
    return report


def add_nc_examples(db: Session, audit_set: AuditSet, users: dict[str, PlatformUser], stage_type: str = "stage_1") -> None:
    db.add(AuditSetNCDecision(
        id=new_id(),
        audit_set_id=audit_set.id,
        stage_type=stage_type,
        no_nc=False,
        notes="Two demo nonconformities were identified during Stage 1.",
        decided_by=users["lead"].id,
        decided_at=days_ago(1),
    ))
    for idx, clause, grade, text in (
        (1, "8.5.1", "major", "Production control records are incomplete for batch #2024-117. No traceability to raw material certificates."),
        (2, "7.2", "minor", "Two operators in the machining department cannot demonstrate competency records for CNC operation."),
    ):
        db.add(AuditSetNCItem(
            id=new_id(),
            audit_set_id=audit_set.id,
            stage_type=stage_type,
            nc_index=idx,
            category=grade,
            description=f"{clause}: {text}",
            status="open",
            due_date=today_plus(30 if grade == "minor" else 90),
            created_at=days_ago(1),
        ))


def add_fr233(
    db: Session,
    audit_set: AuditSet,
    users: dict[str, PlatformUser],
    *,
    chair_signed: bool,
    member_signed: bool,
    cm_signed: bool,
) -> AuditSetSharedDocument:
    audit_set.committee_members = [
        {"id": users["committee_chair"].auditor_id, "name": "Kemal Doğan", "ea_codes": ["EA 17", "EA 28"], "standards": ["ISO 9001"], "role": "chairperson"},
        {"id": users["committee_member"].auditor_id, "name": "Selin Yurt", "ea_codes": ["EA 17"], "standards": ["ISO 9001"], "role": "member"},
    ]
    db.add(AuditSetCommitteeMember(
        id=new_id(),
        audit_set_id=audit_set.id,
        user_id=users["committee_chair"].id,
        user_name="Kemal Doğan",
        user_email=users["committee_chair"].email,
        role="decision_maker",
        appointed_by=users["planner"].id,
        ea_codes_at_appointment=["EA 17", "EA 28"],
        appointed_at=days_ago(3),
    ))
    db.add(AuditSetCommitteeMember(
        id=new_id(),
        audit_set_id=audit_set.id,
        user_id=users["committee_member"].id,
        user_name="Selin Yurt",
        user_email=users["committee_member"].email,
        role="reviewer",
        appointed_by=users["planner"].id,
        ea_codes_at_appointment=["EA 17"],
        appointed_at=days_ago(3),
    ))
    doc = add_doc(db, audit_set, "FR.233 Review And Decision Form", "fr233", status="signed" if cm_signed else "released")
    if chair_signed:
        add_vsp(db, "shared_doc", doc.id, "COMMITTEE_CHAIR", users["committee_chair"], signed_at=days_ago(2))
    if member_signed:
        add_vsp(db, "shared_doc", doc.id, "COMMITTEE_MEMBER_1", users["committee_member"], signed_at=days_ago(2))
    if cm_signed:
        add_vsp(db, "shared_doc", doc.id, "CB_CERT_MANAGER", users["cm"], signed_at=days_ago(1))
    db.add(AuditSetFR233Record(
        id=new_id(),
        audit_set_id=audit_set.id,
        document_id=doc.id,
        status="complete" if cm_signed else "signing",
        created_at=days_ago(3),
        updated_at=days_ago(1),
    ))
    return doc


def build_demo_data(audit_db: Session, auth_db: Session, auditor_db: Session) -> None:
    users, auditors = create_users(auth_db, auditor_db)

    sets: list[AuditSet] = [
        acme_base(users, 1, "pending_review", "New Application"),
        acme_base(users, 2, "quotation_sent", "Agreement Awaiting Client Signature"),
        acme_base(users, 3, "agreement_signed", "Planning Phase"),
        acme_base(users, 4, "stage1_in_progress", "Stage 1 In Progress"),
        acme_base(users, 5, "stage1_complete", "Stage 1 Report Review"),
        acme_base(users, 6, "stage2_complete", "Stage 2 CM Sign-off"),
        acme_base(users, 7, "committee_review", "Committee Review"),
        greentech_base(users),
    ]
    for aset in sets:
        audit_db.add(aset)
        audit_db.flush()
        add_status_event(audit_db, aset, aset.workflow_status or "pending_review")

    # Link the two public demo client accounts to the most useful live demo states.
    users["client"].audit_set_id = sets[1].id       # agreement signing demo
    users["client2"].audit_set_id = sets[7].id      # completed certificate demo
    auth_db.commit()

    add_acme_roster(audit_db, users["client"])

    # Set 2 — agreement awaiting client signature.
    quotation = add_doc(audit_db, sets[1], "FR.220 Quotation", "quotation", status="signed", signed_at=days_ago(3))
    agreement = add_doc(audit_db, sets[1], "FR.221 Agreement", "agreement", status="released")
    add_signature_slot(audit_db, sets[1], quotation, "cb_planner", users["planner"], signed_at=days_ago(5), order_index=1)
    add_signature_slot(audit_db, sets[1], quotation, "client", users["client"], signed_at=days_ago(3), order_index=2)
    add_signature_slot(audit_db, sets[1], agreement, "cb_planner", users["planner"], signed_at=days_ago(3), order_index=1)
    add_signature_slot(audit_db, sets[1], agreement, "client", users["client"], signed_at=None, order_index=2)
    add_vsp(audit_db, "shared_doc", agreement.id, "CB_PLANNER", users["planner"], signed_at=days_ago(3))

    # Set 3 — fully signed agreement, no stages yet.
    q3 = add_doc(audit_db, sets[2], "FR.220 Quotation", "quotation", status="signed", signed_at=days_ago(8))
    a3 = add_doc(audit_db, sets[2], "FR.221 Agreement", "agreement", status="signed", signed_at=days_ago(7))
    add_signature_slot(audit_db, sets[2], q3, "client", users["client"], signed_at=days_ago(8))
    add_signature_slot(audit_db, sets[2], a3, "client", users["client"], signed_at=days_ago(7))

    # Set 4 — Stage 1 active with NCs.
    add_stage(audit_db, sets[3], "stage_1", 1, users, auditors, status="in_progress", start_offset=0, end_offset=1)
    add_stage_docs(audit_db, sets[3], users, "stage_1", signed=True)
    add_nc_examples(audit_db, sets[3], users, "stage_1")

    # Set 5 — Stage 1 report reviewer pending.
    add_stage(audit_db, sets[4], "stage_1", 1, users, auditors, status="complete", start_offset=-5, end_offset=-4)
    add_stage_docs(audit_db, sets[4], users, "stage_1", signed=True)
    add_report(audit_db, sets[4], users, "stage_1", "FR.231", status="pending_review", la_signed=True, reviewer_signed=False)

    # Set 6 — Stage 2 CM final sign-off pending.
    add_stage(audit_db, sets[5], "stage_1", 1, users, auditors, status="complete", start_offset=-12, end_offset=-11)
    add_stage(audit_db, sets[5], "stage_2", 2, users, auditors, status="complete", start_offset=-5, end_offset=-4)
    add_stage_docs(audit_db, sets[5], users, "stage_1", signed=True)
    add_stage_docs(audit_db, sets[5], users, "stage_2", signed=True)
    add_report(audit_db, sets[5], users, "stage_1", "FR.231", status="approved", la_signed=True, reviewer_signed=True)
    r6 = add_report(audit_db, sets[5], users, "stage_2", "FR.232", status="pending_review", la_signed=True, reviewer_signed=False)
    add_vsp(audit_db, "audit_report", r6.id, "APPOINTED_REVIEWER", users["committee_chair"], signed_at=days_ago(1))

    # Set 7 — FR.233 chair signature pending.
    add_stage(audit_db, sets[6], "stage_1", 1, users, auditors, status="complete", start_offset=-20, end_offset=-19)
    add_stage(audit_db, sets[6], "stage_2", 2, users, auditors, status="complete", start_offset=-12, end_offset=-11)
    add_stage_docs(audit_db, sets[6], users, "stage_1", signed=True)
    add_stage_docs(audit_db, sets[6], users, "stage_2", signed=True)
    add_report(audit_db, sets[6], users, "stage_1", "FR.231", status="approved", la_signed=True, reviewer_signed=True)
    add_report(audit_db, sets[6], users, "stage_2", "FR.232", status="approved", la_signed=True, reviewer_signed=True)
    add_nc_decision_no_nc(audit_db, sets[6], users, "stage_1")
    add_nc_decision_no_nc(audit_db, sets[6], users, "stage_2")
    add_fr233(audit_db, sets[6], users, chair_signed=False, member_signed=True, cm_signed=False)

    # Set 8 — certified end state.
    add_stage(audit_db, sets[7], "stage_1", 1, users, auditors, status="complete", start_offset=-30, end_offset=-29)
    add_stage(audit_db, sets[7], "stage_2", 2, users, auditors, status="complete", start_offset=-24, end_offset=-23)
    add_stage_docs(audit_db, sets[7], users, "stage_1", signed=True)
    add_stage_docs(audit_db, sets[7], users, "stage_2", signed=True)
    add_report(audit_db, sets[7], users, "stage_1", "FR.231", status="approved", la_signed=True, reviewer_signed=True)
    add_report(audit_db, sets[7], users, "stage_2", "FR.232", status="approved", la_signed=True, reviewer_signed=True)
    add_fr233(audit_db, sets[7], users, chair_signed=True, member_signed=True, cm_signed=True)
    cert = add_doc(audit_db, sets[7], "Certificate(s)", "certificate", status="released")
    cert.file_path = f"demo/placeholder/{sets[7].client_reference}/certificate.pdf"

    audit_db.commit()


def add_nc_decision_no_nc(db: Session, audit_set: AuditSet, users: dict[str, PlatformUser], stage_type: str) -> None:
    db.add(AuditSetNCDecision(
        id=new_id(),
        audit_set_id=audit_set.id,
        stage_type=stage_type,
        no_nc=True,
        notes=f"No nonconformities identified for {stage_type}.",
        decided_by=users["lead"].id,
        decided_at=days_ago(3),
    ))


def wipe_demo_data(audit_db: Session, auth_db: Session, auditor_db: Session) -> None:
    demo_audit_ids = [
        row.id for row in audit_db.query(AuditSet.id)
        .filter(or_(
            AuditSet.client_reference.like("DEMO-2025-%"),
            AuditSet.company_name.like("DEMO — %"),
        ))
        .all()
    ]
    demo_user_ids = [
        row.id for row in auth_db.query(PlatformUser.id)
        .filter(or_(PlatformUser.username.like("demo_%"), PlatformUser.email.like("demo_%@certiva.com")))
        .all()
    ]
    demo_doc_ids = [
        row.id for row in audit_db.query(AuditSetSharedDocument.id)
        .filter(AuditSetSharedDocument.audit_set_id.in_(demo_audit_ids or [""]))
        .all()
    ]
    demo_report_ids = [
        row.id for row in audit_db.query(AuditSetAuditReport.id)
        .filter(AuditSetAuditReport.audit_set_id.in_(demo_audit_ids or [""]))
        .all()
    ]
    demo_nc_item_ids = [
        row.id for row in audit_db.query(AuditSetNCItem.id)
        .filter(AuditSetNCItem.audit_set_id.in_(demo_audit_ids or [""]))
        .all()
    ]

    for model, predicate in (
        (DocumentSignatureField, DocumentSignatureField.docx_path.like("%demo/placeholder/%")),
        (VisualSignaturePlacement, or_(
            VisualSignaturePlacement.doc_id.in_(demo_doc_ids or [""]),
            VisualSignaturePlacement.doc_id.in_(demo_report_ids or [""]),
        )),
        (AuditDocumentSignature, AuditDocumentSignature.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetNCEvidence, AuditSetNCEvidence.nc_item_id.in_(demo_nc_item_ids or [""])),
        (AuditSetNCReview, AuditSetNCReview.nc_item_id.in_(demo_nc_item_ids or [""])),
        (AuditSetNCItem, AuditSetNCItem.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetNCDecision, AuditSetNCDecision.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetNCForm, AuditSetNCForm.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetAuditReport, AuditSetAuditReport.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetAuditorAssessment, AuditSetAuditorAssessment.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetImpartialityDeclaration, AuditSetImpartialityDeclaration.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetMeetingAttendee, AuditSetMeetingAttendee.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetCommitteeMember, AuditSetCommitteeMember.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetFR233Record, AuditSetFR233Record.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetSharedDocument, AuditSetSharedDocument.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetStatusEvent, AuditSetStatusEvent.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSetStage, AuditSetStage.audit_set_id.in_(demo_audit_ids or [""])),
        (AuditSet, AuditSet.id.in_(demo_audit_ids or [""])),
        (ClientOrgEmployee, ClientOrgEmployee.client_user_id.in_(demo_user_ids or [""])),
    ):
        audit_db.query(model).filter(predicate).delete(synchronize_session=False)
        audit_db.commit()

    auth_db.query(UserSignature).filter(UserSignature.user_id.in_(demo_user_ids or [""])).delete(synchronize_session=False)
    auth_db.query(PlatformUser).filter(PlatformUser.id.in_(demo_user_ids or [""])).delete(synchronize_session=False)
    auth_db.commit()

    demo_auditor_ids = [
        row.id for row in auditor_db.query(Auditor.id)
        .filter(Auditor.email.like("demo_%@certiva.com"))
        .all()
    ]
    auditor_db.query(AuditorStandardQualification).filter(
        AuditorStandardQualification.auditor_id.in_(demo_auditor_ids or [""])
    ).delete(synchronize_session=False)
    auditor_db.query(Auditor).filter(Auditor.id.in_(demo_auditor_ids or [""])).delete(synchronize_session=False)
    auditor_db.commit()


def print_credentials() -> None:
    print(
        """
═══════════════════════════════════════════════════════
  CERTIVA DEMO ENVIRONMENT — CREDENTIALS
═══════════════════════════════════════════════════════

  All passwords: Demo1234!
  URL: https://compassionate-miracle-production.up.railway.app/login

  ROLES & LOGINS
  ─────────────────────────────────────────────────────
  Admin              demo_admin
  Planner            demo_planner
  US Planner         demo_usplanner
  Cert. Manager      demo_cm
  Lead Auditor       demo_lead
  Auditor            demo_auditor2
  Technical Expert   demo_te
  Committee Chair    demo_committee_chair
  Committee Member   demo_committee_member
  Consultant         demo_consultant
  Client (Acme)      demo_client
  Client (Green)     demo_client2

  DEMO AUDIT SETS
  ─────────────────────────────────────────────────────
  2025001 / DEMO-2025-001  New Application (Pending Review)
  2025002 / DEMO-2025-002  Agreement Awaiting Client Signature
  2025003 / DEMO-2025-003  Planning Phase (Assign Auditors)
  2025004 / DEMO-2025-004  Stage 1 In Progress + NCs Open
  2025005 / DEMO-2025-005  Stage 1 Report — Reviewer Signing
  2025006 / DEMO-2025-006  Stage 2 Report — CM Sign-off
  2025007 / DEMO-2025-007  Committee Review — FR.233 Signing
  2025008 / DEMO-2025-008  Fully Certified (GreenTech, ISO 14001+45001)

  CLIENT EMPLOYEES (Acme Metal Works)
  ─────────────────────────────────────────────────────
  Fatma Yılmaz    Quality Manager
  Bülent Koç      Production Manager
  Zeynep Avcı     HSE Coordinator

═══════════════════════════════════════════════════════
"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed isolated Certiva demo data.")
    parser.add_argument("--reset", action="store_true", help="Delete existing demo rows and recreate them.")
    args = parser.parse_args()

    create_audit_tables()
    create_auth_tables()
    create_auditor_tables()

    audit_db = AuditSessionLocal()
    auth_db = AuthSessionLocal()
    auditor_db = AuditorSessionLocal()
    try:
        exists = auth_db.query(PlatformUser).filter(PlatformUser.username == "demo_admin").first()
        if exists and not args.reset:
            print("Demo data already exists. Run with --reset to recreate.")
            print_credentials()
            return
        if args.reset:
            wipe_demo_data(audit_db, auth_db, auditor_db)
        build_demo_data(audit_db, auth_db, auditor_db)
        print_credentials()
    finally:
        audit_db.close()
        auth_db.close()
        auditor_db.close()


if __name__ == "__main__":
    main()
