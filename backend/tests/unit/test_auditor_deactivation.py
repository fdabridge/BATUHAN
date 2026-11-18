from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes.auditors import soft_delete
from auditors.models import Auditor, Base as AuditorBase
from auth.db_models import Base as AuthBase, PlatformUser


def _session_for(base):
    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_admin_delete_deactivates_auditor_and_linked_login() -> None:
    auditors_db = _session_for(AuditorBase)
    auth_db = _session_for(AuthBase)

    auditor = Auditor(name="Test Auditor", is_active=True)
    auditors_db.add(auditor)
    auditors_db.commit()
    auditors_db.refresh(auditor)

    linked_user = PlatformUser(
        email="auditor@example.com",
        username="test.auditor",
        password_hash="unused-in-this-test",
        full_name="Test Auditor",
        role="auditor",
        is_active=True,
        auditor_id=auditor.id,
    )
    unrelated_user = PlatformUser(
        email="other@example.com",
        username="other.auditor",
        password_hash="unused-in-this-test",
        full_name="Other Auditor",
        role="auditor",
        is_active=True,
        auditor_id="another-auditor",
    )
    auth_db.add_all([linked_user, unrelated_user])
    auth_db.commit()

    soft_delete(
        auditor_id=auditor.id,
        db=auditors_db,
        auth_db=auth_db,
        _=SimpleNamespace(role="admin"),
    )

    auditors_db.refresh(auditor)
    auth_db.refresh(linked_user)
    auth_db.refresh(unrelated_user)
    assert auditor.is_active is False
    assert linked_user.is_active is False
    assert unrelated_user.is_active is True


def test_admin_delete_keeps_auditor_profile_and_history() -> None:
    auditors_db = _session_for(AuditorBase)
    auth_db = _session_for(AuthBase)

    auditor = Auditor(name="Historical Auditor", is_active=True)
    auditors_db.add(auditor)
    auditors_db.commit()
    auditor_id = auditor.id

    soft_delete(
        auditor_id=auditor_id,
        db=auditors_db,
        auth_db=auth_db,
        _=SimpleNamespace(role="admin"),
    )

    retained = auditors_db.query(Auditor).filter(Auditor.id == auditor_id).one()
    assert retained.name == "Historical Auditor"
    assert retained.is_active is False
