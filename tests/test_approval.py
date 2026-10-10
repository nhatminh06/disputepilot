import ast
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
import requests
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from backend import database, main, paypal_writes


DISPUTE = 'PP-R-TEST'
TOKEN = 'development-test-credential-not-for-use'
AUTH = {'Authorization': f'Bearer {TOKEN}'}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Unexpected external HTTP request')
    monkeypatch.setattr(requests.Session, 'request', blocked)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DEV_MERCHANT_TOKEN', TOKEN)
    monkeypatch.setenv('DEV_MERCHANT_ID', 'test-merchant')
    monkeypatch.setenv('PAYPAL_BASE_URL', main.DEFAULT_PAYPAL_BASE_URL)
    with TestClient(main.app) as client:
        yield client


@pytest.fixture
def postgres(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is required for PostgreSQL integration tests')
    schema = 'approval_test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

    def connect():
        return psycopg.connect(url, row_factory=dict_row,
                              options=f'-c search_path={schema}', connect_timeout=5)

    monkeypatch.setattr(database, 'connect', connect)
    try:
        database.initialize()
        yield connect
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.fixture
def upstream(monkeypatch):
    dispute = {
        'dispute_id': DISPUTE,
        'status': 'WAITING_FOR_SELLER_RESPONSE',
        'dispute_life_cycle_stage': 'INQUIRY',
        'reason': 'MERCHANDISE_OR_SERVICE_NOT_RECEIVED',
        'links': [{
            'rel': 'send_message', 'method': 'POST',
            'href': f'{main.DEFAULT_PAYPAL_BASE_URL}/v1/customer/disputes/{DISPUTE}/send-message',
        }],
    }
    monkeypatch.setattr(main, 'get_access_token', lambda base: 'test-paypal-token')
    monkeypatch.setattr(main, 'get_dispute', lambda *args: dispute.copy())
    return dispute


@pytest.fixture
def run(client, postgres, upstream):
    result = client.post(f'/api/disputes/{DISPUTE}/investigate', headers=AUTH)
    assert result.status_code == 201
    assert result.json()['investigation_status'] == 'NEEDS_REVIEW'
    return result.json()


def approve(client, run, **changes):
    body = {'run_id': run['run_id'], 'action_type': 'SEND_MESSAGE', 'confirmed': True}
    body.update(changes)
    return client.post(f'/disputes/{DISPUTE}/approve', headers=AUTH, json=body)


def events(postgres, run):
    with postgres() as conn:
        return conn.execute('SELECT * FROM audit_events WHERE run_id=%s ORDER BY event_id',
                            (run['run_id'],)).fetchall()


def mock_write(monkeypatch):
    calls = []

    def send(*args):
        calls.append(args)
        return 'SUCCEEDED', {'http_status': 200, 'body': {'links': []}}

    monkeypatch.setattr(paypal_writes, 'send_message', send)
    return calls


@pytest.mark.parametrize('header', [None, 'Bearer wrong', 'Basic abc'])
def test_unauthorized(client, header):
    response = client.post(f'/disputes/{DISPUTE}/approve',
                           headers={'Authorization': header} if header else {},
                           json={'run_id': str(uuid4()), 'action_type': 'SEND_MESSAGE',
                                 'confirmed': True})
    assert response.status_code == 401


def test_missing_server_credentials_fail_closed(client, monkeypatch):
    monkeypatch.delenv('DEV_MERCHANT_TOKEN')
    assert client.post(f'/api/disputes/{DISPUTE}/investigate',
                       headers=AUTH).status_code == 503


@pytest.mark.parametrize('changes', [
    {'confirmed': False}, {'confirmed': 'true'}, {'action_type': 'REFUND'},
    {'approved_by': 'attacker'}, {'message': 'A different message'},
])
def test_invalid_approval(client, changes):
    result = approve(client, {'run_id': str(uuid4())}, **changes)
    assert result.status_code == 422


def test_missing_confirmation(client):
    result = client.post(f'/disputes/{DISPUTE}/approve', headers=AUTH,
                         json={'run_id': str(uuid4()), 'action_type': 'SEND_MESSAGE'})
    assert result.status_code == 422


def test_investigation_requires_authentication(client):
    assert client.post(f'/api/disputes/{DISPUTE}/investigate').status_code == 401


def test_wrong_dispute(client, run):
    result = client.post('/disputes/OTHER/approve', headers=AUTH,
                         json={'run_id': run['run_id'], 'action_type': 'SEND_MESSAGE',
                               'confirmed': True})
    assert result.status_code == 409


def test_unknown_run(client, postgres):
    assert approve(client, {'run_id': str(uuid4())}).status_code == 404


def test_wrong_merchant(client, run, monkeypatch):
    monkeypatch.setenv('DEV_MERCHANT_ID', 'different-merchant')
    assert approve(client, run).status_code == 403


def test_success_audit_and_duplicate(client, run, postgres, monkeypatch):
    calls = mock_write(monkeypatch)
    result = approve(client, run)
    assert result.status_code == 200
    assert result.json()['paypal_result']['http_status'] == 200
    assert approve(client, run).status_code == 409
    assert len(calls) == 1
    assert calls[0][-1] == main.MESSAGE
    assert [e['event_type'] for e in events(postgres, run)] == [
        'INVESTIGATED', 'APPROVED', 'EXECUTION_RESERVED', 'SUCCEEDED',
    ]
    assert all(e['actor'] == 'test-merchant' for e in events(postgres, run))
    with postgres() as conn:
        row = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    assert row['approved_by'] == 'test-merchant'
    assert row['approved_at'] is not None
    assert row['executed_at'] is not None
    assert row['idempotency_key'] is not None


@pytest.mark.parametrize('separate_run', [False, True])
def test_concurrent_approval(client, run, upstream, monkeypatch, separate_run):
    other = run
    if separate_run:
        other = client.post(f'/api/disputes/{DISPUTE}/investigate', headers=AUTH).json()
    barrier = Barrier(2)

    def get_dispute(*args):
        barrier.wait(timeout=10)
        return upstream.copy()

    monkeypatch.setattr(main, 'get_dispute', get_dispute)
    calls = mock_write(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: approve(client, item), [run, other]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert len(calls) == 1


@pytest.mark.parametrize('change', [
    {'links': []}, {'status': 'RESOLVED'}, {'dispute_life_cycle_stage': 'CHARGEBACK'},
    {'reason': 'OTHER'}, {'dispute_id': 'DIFFERENT'},
    {'links': [{'rel': 'send_message', 'method': 'POST',
                'href': 'https://sandbox.evil.com/send-message'}]},
])
def test_action_unavailable(client, run, upstream, change):
    upstream.update(change)
    assert approve(client, run).status_code == 409


def test_read_failure_prevents_approval(client, run, monkeypatch):
    def fail(*args):
        raise requests.Timeout('read timed out')
    monkeypatch.setattr(main, 'get_dispute', fail)
    assert approve(client, run).status_code == 502


def test_database_failure_before_execution(client, run, monkeypatch):
    def fail(*args):
        raise psycopg.OperationalError('database unavailable')
    monkeypatch.setattr(database, 'reserve', fail)
    assert approve(client, run).status_code == 503


def test_database_audit_failure_rolls_back_reservation(client, run, postgres, monkeypatch):
    original = database.audit

    def fail(conn, run_id, event, actor, data=None):
        if event == 'EXECUTION_RESERVED':
            raise psycopg.OperationalError('audit failed')
        original(conn, run_id, event, actor, data)

    monkeypatch.setattr(database, 'audit', fail)
    assert approve(client, run).status_code == 503
    assert [e['event_type'] for e in events(postgres, run)] == ['INVESTIGATED']
    with postgres() as conn:
        row = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    assert row['approval_state'] == 'PENDING'


def test_ambiguous_result_blocks_replay(client, run, postgres, monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout('do not log secrets')
    monkeypatch.setattr(requests, 'post', timeout)
    result = approve(client, run)
    assert result.status_code == 502
    assert result.json()['execution_status'] == 'REQUIRES_RECONCILIATION'
    assert approve(client, run).status_code == 409
    assert events(postgres, run)[-1]['event_type'] == 'REQUIRES_RECONCILIATION'


def test_database_failure_after_send_keeps_reservation(client, run, postgres, monkeypatch):
    calls = mock_write(monkeypatch)

    def fail(*args):
        raise psycopg.OperationalError('result persistence failed')

    monkeypatch.setattr(database, 'finish', fail)
    assert approve(client, run).status_code == 503
    assert approve(client, run).status_code == 409
    assert len(calls) == 1
    with postgres() as conn:
        row = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    assert row['execution_status'] == 'REQUIRES_RECONCILIATION'
    assert row['executed_at'] is None


@pytest.mark.parametrize('code,body,expected', [
    (200, {'links': [{'rel': 'self', 'method': 'GET',
                     'href': f'https://api-m.sandbox.paypal.com/v1/customer/disputes/{DISPUTE}'}]},
     'SUCCEEDED'),
    (200, {}, 'REQUIRES_RECONCILIATION'),
    (500, {'name': 'INTERNAL_SERVER_ERROR'}, 'REQUIRES_RECONCILIATION'),
    (422, {'name': 'INVALID_REQUEST'}, 'FAILED'),
    (302, {}, 'REQUIRES_RECONCILIATION'),
])
def test_write_contract_and_sanitization(monkeypatch, code, body, expected):
    body = {**body, 'access_token': 'private-token', 'buyer': {'email': 'private@example.com'}}

    def post(url, **kwargs):
        assert url == f'{main.DEFAULT_PAYPAL_BASE_URL}/v1/customer/disputes/{DISPUTE}/send-message'
        assert kwargs['json'] == {'message': main.MESSAGE}
        assert 'PayPal-Request-Id' not in kwargs['headers']
        assert kwargs['allow_redirects'] is False
        assert kwargs['timeout'] == 20
        result = requests.Response()
        result.status_code = code
        result._content = json.dumps(body).encode()
        return result

    monkeypatch.setattr(requests, 'post', post)
    status, result = paypal_writes.send_message(main.DEFAULT_PAYPAL_BASE_URL,
                                               'private-token', DISPUTE, main.MESSAGE)
    assert status == expected
    assert result['http_status'] == code
    assert 'private' not in json.dumps(result)


def test_non_json_response_is_ambiguous(monkeypatch, capsys):
    result = requests.Response()
    result.status_code = 200
    result._content = b'<html>private-token private buyer info</html>'
    monkeypatch.setattr(requests, 'post', lambda *args, **kwargs: result)
    status, body = paypal_writes.send_message(main.DEFAULT_PAYPAL_BASE_URL,
                                             'private-token', DISPUTE, main.MESSAGE)
    assert status == 'REQUIRES_RECONCILIATION'
    assert 'private' not in json.dumps(body)
    assert 'private' not in capsys.readouterr().err


def test_write_rejects_non_sandbox_url():
    with pytest.raises(ValueError):
        paypal_writes.send_message('https://sandbox.attacker.com',
                                  'test-token', DISPUTE, main.MESSAGE)


def test_only_approval_route_imports_write_module():
    importers = []
    for path in Path('backend').rglob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'backend.paypal_writes':
                importers.append(path.name)
                approve_fn = next(n for n in tree.body
                                  if isinstance(n, ast.FunctionDef) and n.name == 'approve')
                assert node in list(ast.walk(approve_fn))
    assert importers == ['main.py']
    assert not list(Path('backend').glob('*agent*'))
