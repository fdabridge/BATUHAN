import copy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth.db_models import get_db
from auth.dependencies import get_current_user
from standalone_tracker.models import Base, TrackerRecord
from standalone_tracker.router import router


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv("IFC_TRACKER_EDITOR_EMAILS", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="admin", email="owner@example.test")
    return TestClient(app), app, engine, factory


def cert(id="c1"):
    return dict(id=id, kind="certificate", company="Example", consultant="Individual", standard="ISO 9001", certificate="IFC-Q-1", country="Germany", stage="Certificate", annual="2027-01-01", expiry="2029-01-01", invoiced="Yes", invoiceRef="INV-1", currency="USD", fee=100, payment="Unpaid", revision=0)


def snapshot():
    return dict(records=[cert()], invoices=[dict(id="i1", kind="invoice", company="Example", ref="INV-1", total=100, paid=0, currency="USD")], other=[], asOf="2026-11-02")


def test_auth_and_designated_editor_access(setup, monkeypatch):
    client, app, _, _ = setup
    app.dependency_overrides.pop(get_current_user)
    assert client.get('/standalone-tracker').status_code == 401
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="planner", email="editor@example.test")
    assert client.get('/standalone-tracker').status_code == 403
    monkeypatch.setenv("IFC_TRACKER_EDITOR_EMAILS", "editor@example.test")
    assert client.get('/standalone-tracker').status_code == 200
    assert client.post('/standalone-tracker/import', json=snapshot()).status_code == 403


def test_import_is_independent_one_time_and_atomic(setup):
    client, _, engine, _ = setup
    invalid = snapshot()
    invalid['records'].append(dict(cert('bad'), annual="not-a-date"))
    assert client.post('/standalone-tracker/import', json=invalid).status_code == 422
    assert client.get('/standalone-tracker').json()['records'] == []
    assert client.post('/standalone-tracker/import', json=snapshot()).json()['imported'] == 2
    assert client.post('/standalone-tracker/import', json=snapshot()).status_code == 409
    assert set(inspect(engine).get_table_names()) == {'standalone_tracker_records', 'standalone_tracker_history', 'standalone_tracker_metadata'}
    assert len(client.get('/standalone-tracker').json()['records']) == 1


def test_edit_conflict_archive_and_restore(setup):
    client, _, _, _ = setup
    first = client.post('/standalone-tracker', json=cert()).json()['record']
    edited = client.post('/standalone-tracker', json=dict(first, recordNote="Renewing")).json()['record']
    assert client.post('/standalone-tracker', json=dict(first, recordNote="Stale edit")).status_code == 409
    archived = client.post('/standalone-tracker', json=dict(edited, archived=True)).json()['record']
    assert archived['archived']
    restored = client.post('/standalone-tracker', json=dict(archived, archived=False)).json()['record']
    assert restored['recordNote'] == 'Renewing' and not restored['archived']
    assert len(client.get('/standalone-tracker?history=true').json()['history']) == 4


def test_invoice_payment_updates_only_its_linked_certificates(setup):
    client, _, _, _ = setup
    data = snapshot()
    data['records'] += [dict(cert('unrelated'), invoiceRef='OTHER'), dict(cert('confirmed'), paymentConfirmedByOwner=True)]
    assert client.post('/standalone-tracker/import', json=data).status_code == 200
    invoice = client.get('/standalone-tracker').json()['invoices'][0]
    response = client.post('/standalone-tracker', json=dict(invoice, paid=100))
    assert response.status_code == 200, response.text
    assert response.json()['record']['balance'] == 0
    rows = {r['id']: r for r in client.get('/standalone-tracker').json()['records']}
    assert rows['c1']['payment'] == 'Paid' and rows['c1']['balance'] == 0
    assert rows['unrelated']['payment'] == rows['confirmed']['payment'] == 'Unpaid'
    assert client.post('/standalone-tracker', json=dict(response.json()['record'], paid=101)).status_code == 422


def test_identity_edit_drops_old_registry_match_and_preserves_notes(setup):
    client, _, _, _ = setup
    data = snapshot()
    data['records'][0].update(uaf={'url':'https://example.test/registration','status':'Withdrawn'}, recordNote='Keep this note')
    client.post('/standalone-tracker/import', json=data)
    row = client.get('/standalone-tracker').json()['records'][0]
    saved = client.post('/standalone-tracker', json=dict(row, certificate='NEW')).json()['record']
    assert 'uaf' not in saved and saved['recordNote'] == 'Keep this note'


def test_reject_duplicate_import_and_cross_kind_overwrite(setup):
    client, _, _, _ = setup
    data = snapshot()
    data['records'].append(copy.deepcopy(data['records'][0]))
    assert client.post('/standalone-tracker/import', json=data).status_code == 422
    row = client.post('/standalone-tracker', json=cert()).json()['record']
    assert client.post('/standalone-tracker', json=dict(row, kind='invoice', total=100, ref='INV')).status_code == 409


def registry_evidence(status='Active'):
    return dict(status=status, checkedAt='2026-11-09', issued='2026-01-02', expiry='2027-01-01', url='https://member.iafcertsearch.org/certifications/live/example', iafCertificate='IFC-Q-1')


def test_registry_checks_preserve_business_data_and_record_negative_search(setup):
    client, _, _, _ = setup
    client.post('/standalone-tracker/import', json=snapshot())
    row = client.get('/standalone-tracker').json()['records'][0]
    check = dict(id=row['id'], revision=row['revision'], iaf=registry_evidence())
    assert client.post('/standalone-tracker/registry-checks', json={'checks':[check]}).json() == {'updated':1}
    saved = client.get('/standalone-tracker').json()['records'][0]
    for key in ('annual','expiry','invoiceRef','payment','fee','company','certificate'):
        assert saved[key] == row[key]
    assert saved['iaf']['status'] == 'Active'
    check.update(revision=saved['revision'], iaf=registry_evidence('Not found'))
    assert client.post('/standalone-tracker/registry-checks', json={'checks':[check]}).status_code == 200
    saved = client.get('/standalone-tracker').json()['records'][0]
    assert saved['iaf'] is None and saved['iafCheck']['status'] == 'Not found'


def test_registry_checks_reject_stale_batch_and_other_fields(setup):
    client, _, _, _ = setup
    for rid in ('c1','c2'):
        client.post('/standalone-tracker', json=cert(rid))
    checks=[dict(id=rid,revision=1,iaf=registry_evidence()) for rid in ('c1','c2')]
    checks[1]['revision']=0
    assert client.post('/standalone-tracker/registry-checks',json={'checks':checks}).status_code == 409
    assert all(not r.get('iaf') for r in client.get('/standalone-tracker').json()['records'])
    checks[1]['revision']=1
    checks[0]['payment']='Paid'
    assert client.post('/standalone-tracker/registry-checks',json={'checks':checks}).status_code == 422
    checks[0].pop('payment')
    checks[0]['iaf']['url']='https://unrelated.test/certificate'
    assert client.post('/standalone-tracker/registry-checks',json={'checks':checks}).status_code == 422
