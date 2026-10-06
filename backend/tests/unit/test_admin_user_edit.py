from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.admin_users import admin_update_user
from auth.db_models import Base, PlatformUser
from auth.schemas import UserUpdateSchema


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _user(
    db,
    *,
    user_id: str,
    email: str,
    username: str | None,
    role: str,
    auditor_id: str | None = None,
) -> PlatformUser:
    user = PlatformUser(
        id=user_id,
        email=email,
        username=username,
        password_hash="not-used-by-these-tests",
        full_name=user_id.title(),
        role=role,
        is_active=True,
        auditor_id=auditor_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_admin_can_edit_user_identity_role_and_status(db):
    admin = _user(
        db,
        user_id="admin-id",
        email="admin@example.com",
        username="admin",
        role="admin",
    )
    target = _user(
        db,
        user_id="target-id",
        email="old@example.com",
        username="old-name",
        role="officer",
    )

    updated = admin_update_user(
        target.id,
        UserUpdateSchema(
            email=" new@example.com ",
            username=" new-name ",
            full_name=" New Name ",
            role="planner",
            is_active=False,
        ),
        db,
        admin,
    )

    assert updated.email == "new@example.com"
    assert updated.username == "new-name"
    assert updated.full_name == "New Name"
    assert updated.role == "planner"
    assert updated.is_active is False


def test_changing_from_auditor_role_clears_auditor_link(db):
    admin = _user(
        db,
        user_id="admin-id",
        email="admin@example.com",
        username="admin",
        role="admin",
    )
    target = _user(
        db,
        user_id="auditor-user",
        email="auditor@example.com",
        username="auditor",
        role="auditor",
        auditor_id="auditor-record-id",
    )

    updated = admin_update_user(
        target.id,
        UserUpdateSchema(role="planner"),
        db,
        admin,
    )

    assert updated.role == "planner"
    assert updated.auditor_id is None


def test_explicit_null_unlinks_auditor_record(db):
    admin = _user(
        db,
        user_id="admin-id",
        email="admin@example.com",
        username="admin",
        role="admin",
    )
    target = _user(
        db,
        user_id="auditor-user",
        email="auditor@example.com",
        username="auditor",
        role="auditor",
        auditor_id="auditor-record-id",
    )

    updated = admin_update_user(
        target.id,
        UserUpdateSchema(auditor_id=None),
        db,
        admin,
    )

    assert updated.auditor_id is None


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (UserUpdateSchema(email="taken@example.com"), "Email already exists."),
        (UserUpdateSchema(username="taken"), "Username already exists."),
    ],
)
def test_duplicate_identity_is_rejected_without_changing_user(db, body, detail):
    admin = _user(
        db,
        user_id="admin-id",
        email="admin@example.com",
        username="admin",
        role="admin",
    )
    _user(
        db,
        user_id="existing-id",
        email="taken@example.com",
        username="taken",
        role="planner",
    )
    target = _user(
        db,
        user_id="target-id",
        email="original@example.com",
        username="original",
        role="officer",
    )

    with pytest.raises(HTTPException) as exc:
        admin_update_user(target.id, body, db, admin)

    assert exc.value.status_code == 409
    assert exc.value.detail == detail
    db.refresh(target)
    assert target.email == "original@example.com"
    assert target.username == "original"


@pytest.mark.parametrize(
    "body",
    [
        UserUpdateSchema(full_name="   "),
        UserUpdateSchema(email="   "),
        UserUpdateSchema(username="   "),
    ],
)
def test_blank_identity_fields_are_rejected(db, body):
    admin = _user(
        db,
        user_id="admin-id",
        email="admin@example.com",
        username="admin",
        role="admin",
    )
    target = _user(
        db,
        user_id="target-id",
        email="target@example.com",
        username="target",
        role="officer",
    )

    with pytest.raises(HTTPException) as exc:
        admin_update_user(target.id, body, db, admin)

    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (UserUpdateSchema(role="planner"), "Cannot remove your own admin role."),
        (UserUpdateSchema(is_active=False), "Cannot deactivate your own account."),
    ],
)
def test_admin_cannot_lock_themselves_out(db, body, detail):
    admin = _user(
        db,
        user_id="admin-id",
        email="admin@example.com",
        username="admin",
        role="admin",
    )

    with pytest.raises(HTTPException) as exc:
        admin_update_user(admin.id, body, db, admin)

    assert exc.value.status_code == 400
    assert exc.value.detail == detail
