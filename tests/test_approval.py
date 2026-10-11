import ast
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
import requests
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from backend import database, gemini, main, paypal_writes


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
    monkeypatch.setenv('PAYPAL_WRITES_ENABLED', 'true')
    monkeypatch.delenv('GEMINI_AGENT_ENABLED', raising=False)
    monkeypatch.setenv('DEV_MERCHANT_TOKEN', TOKEN)
    monkeypatch.setenv('DEV_MERCHANT_ID', 'test-merchant')
    monkeypatch.setenv('PAYPAL_BASE_URL', main.DEFAULT_PAYPAL_BASE_URL)
    monkeypatch.setattr(gemini, 'recommend', lambda assessment, **kwargs: {
        'model': 'test-model', 'api_status': 'OK', 'http_status': None,
        'attempts': 1, 'usage': [], 'fallback': False,
        'response': {
            'recommendation': 'NEEDS_REVIEW',
            'summary': 'Synthetic evidence requires merchant review.',
            'supporting_fact_ids': [], 'policy_refs': [],
            'missing_information': [
                'delivery_confirmed', 'merchant_policy_supports_contest',
                'payment_completed', 'prior_refund_exists',
                'shipment_record_exists', 'shipping_address_matches',
            ],
        },
    })
    with TestClient(main.app) as client:
        yield client


@pytest.fixture
def postgres(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is required for PostgreSQL integration tests')
    params = psycopg.conninfo.conninfo_to_dict(url)
    if (params.get('dbname') != 'disputepilot_approval_test'
            or params.get('user') != 'approval_test'
            or params.get('host') != '127.0.0.1'
            or not params.get('port')
            or os.getenv('DISPUTEPILOT_TEST_ISOLATED') != 'true'):
        pytest.fail('Refusing destructive fixtures without an isolated approval test database.')
    schema = 'approval_test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        if conn.execute('SELECT current_database(), current_user').fetchone() != (
            'disputepilot_approval_test', 'approval_test',
        ):
            pytest.fail('Test database identity mismatch.')
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
        'messages': [{'posted_by': 'BUYER', 'content': 'Synthetic buyer inquiry.',
                      'time_posted': '2026-01-01T00:00:00Z'}],
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
    assert result.json()['assessment']['recommendation']['response'][
        'recommendation'
    ] == 'NEEDS_REVIEW'
    return result.json()


def approve(client, run, **changes):
    body = {'run_id': run['run_id'], 'action_type': 'SEND_MESSAGE', 'confirmed': True}
    body.update(changes)
    return client.post(f'/disputes/{DISPUTE}/approve', headers=AUTH, json=body)


def test_history_auth_ownership_and_cross_dispute(client, postgres, run, monkeypatch):
    path = f'/api/disputes/{DISPUTE}/history'
    assert client.get(path).status_code == 401
    assert client.get('/api/disputes/PP-OTHER/history', headers=AUTH).status_code == 404
    monkeypatch.setenv('DEV_MERCHANT_ID', 'another-merchant')
    assert client.get(path, headers=AUTH).status_code == 404


def test_history_projection_and_eligibility(client, postgres, run):
    with postgres() as conn:
        database.audit(conn, run['run_id'], 'INVESTIGATED', 'test-merchant',
                       {'access_token': 'do-not-expose', 'buyer': 'private@example.test'})
    response = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH)
    assert response.status_code == 200
    stored = response.json()['runs'][0]
    assert stored['run_id'] == run['run_id']
    assert stored['eligibility'] == 'ELIGIBLE'
    assert stored['message'] == main.MESSAGE
    assert stored['assessment']['risk'] == run['assessment']['risk']
    assert stored['assessment']['recommendation']['response'] == main.gemini.Recommendation.model_validate(
        run['assessment']['recommendation']['response'],
    ).model_dump()
    assert stored['audit_events'][0]['actor'] == 'Merchant'
    assert not any(key in response.text for key in (
        'idempotency_key', 'paypal_result', 'access_token', 'private@example.test',
        'do-not-expose', 'test-merchant', 'approved_by',
    ))


def test_history_bounds_and_historical_success_blocks_new_runs(client, postgres, run):
    database.reserve(run['run_id'], DISPUTE, 'test-merchant', {})
    database.finish(run['run_id'], 'SUCCEEDED', {'http_status': 200}, 'test-merchant')
    for _ in range(27):
        database.create_run({'dispute_id': DISPUTE}, run['assessment'], 'test-merchant', main.MESSAGE)
    data = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH).json()
    assert len(data['runs']) == 25
    assert run['run_id'] not in [item['run_id'] for item in data['runs']]
    assert data['approved_action']['run_id'] == run['run_id']
    assert data['approved_action']['execution_status'] == 'SUCCEEDED'
    assert all(item['eligibility'] == 'ALREADY_SENT' for item in data['runs'])
    assert all(item['approval_state'] == 'PENDING' for item in data['runs'])
    keys = [(item['created_at'], item['run_id']) for item in data['runs']]
    assert keys == sorted(keys, reverse=True)


def test_history_audit_order_and_reconciliation(client, postgres, run):
    database.reserve(run['run_id'], DISPUTE, 'test-merchant', {})
    database.finish(run['run_id'], 'REQUIRES_RECONCILIATION', {}, 'test-merchant')
    data = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH).json()
    stored = data['runs'][0]
    assert stored['eligibility'] == 'REQUIRES_RECONCILIATION'
    assert [event['event_type'] for event in stored['audit_events']] == [
        'INVESTIGATED', 'APPROVED', 'EXECUTION_RESERVED', 'REQUIRES_RECONCILIATION',
    ]
    assert [e['occurred_at'] for e in stored['audit_events']] == sorted(
        e['occurred_at'] for e in stored['audit_events']
    )


def test_history_failed_approval_remains_reserved(client, postgres, run):
    database.reserve(run['run_id'], DISPUTE, 'test-merchant', {})
    database.finish(run['run_id'], 'FAILED', {}, 'test-merchant')
    data = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH).json()
    assert data['runs'][0]['eligibility'] == 'ALREADY_APPROVED'


def test_history_unsupported_message_is_ineligible(client, postgres, run):
    with postgres() as conn:
        conn.execute('UPDATE runs SET message=%s WHERE run_id=%s', ('Unsupported', run['run_id']))
    data = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH).json()
    assert data['runs'][0]['eligibility'] == 'INELIGIBLE'


def test_investigation_persists_policy_sources(client, postgres, upstream, monkeypatch):
    from backend import policy

    captured = {}

    def recommend(assessment, *, policy_excerpts):
        captured.update(policy_excerpts)
        return {'response': {'recommendation': 'NEEDS_REVIEW',
                             'policy_refs': list(policy_excerpts)}}

    monkeypatch.setattr(gemini, 'recommend', recommend)
    result = client.post(f'/api/disputes/{DISPUTE}/investigate', headers=AUTH)
    assert result.status_code == 201
    run = result.json()
    assessment = run['assessment']
    sections = policy.search_policy(policy.QUERIES[upstream['reason']])
    assert assessment['retrieved_policies'] == sections
    assert captured == {f"{s['policy_id']}#{s['section_id']}": s['excerpt'] for s in sections}
    assert assessment['risk'] == 'HIGH'
    assert all(f['status'] == 'UNKNOWN' for f in assessment['facts'])
    assert run['approval_state'] == 'PENDING'
    assert run['execution_status'] == 'NOT_STARTED'
    with postgres() as conn:
        stored = conn.execute('SELECT assessment FROM runs WHERE run_id=%s',
                              (run['run_id'],)).fetchone()
    assert stored['assessment'] == assessment


def events(postgres, run):
    with postgres() as conn:
        return conn.execute('SELECT * FROM audit_events WHERE run_id=%s ORDER BY event_id',
                            (run['run_id'],)).fetchall()


def test_agent_flag_persists_trace_without_approval(client, postgres, upstream, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from google.genai import types
    from backend import agent

    monkeypatch.setenv('GEMINI_AGENT_ENABLED', 'true')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    factory = MagicMock()
    sdk = AsyncMock()
    factory.return_value.aio.__aenter__ = AsyncMock(return_value=sdk)
    factory.return_value.aio.__aexit__ = AsyncMock(return_value=False)
    sdk.models.generate_content.side_effect = [
        types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role='model', parts=[types.Part(function_call=types.FunctionCall(
                name='get_shipping', args={},
            ))],
        ))]),
        types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role='model', parts=[types.Part(text='{"recommendation":"NEEDS_REVIEW",'
                '"summary":"Evidence is incomplete.","supporting_fact_ids":[], '
                '"policy_refs":[],"missing_information":[]}')],
        ))]),
    ]
    monkeypatch.setattr(agent.genai, 'Client', factory)
    response = client.post(f'/api/disputes/{DISPUTE}/investigate', headers=AUTH)
    assert response.status_code == 201
    run = response.json()
    assert run['assessment']['agent_trace'] == [{'tool': 'get_shipping', 'outcome': 'UNAVAILABLE'}]
    assert not run['assessment']['recommendation']['fallback']
    assert run['approval_state'] == 'PENDING'
    assert run['execution_status'] == 'NOT_STARTED'
    assert run['assessment']['risk'] == 'HIGH'
    assert [e['event_type'] for e in events(postgres, run)] == ['INVESTIGATED']
    with postgres() as conn:
        saved = conn.execute('SELECT assessment FROM runs WHERE run_id=%s',
                             (run['run_id'],)).fetchone()
    assert saved['assessment'] == run['assessment']


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


@pytest.mark.parametrize('flag', [None, 'false', '', 'TRUE', 'True', '1', 'yes', ' true', 'true '])
def test_disabled_writes_leave_run_and_audit_untouched(client, run, postgres, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv('PAYPAL_WRITES_ENABLED', raising=False)
    else:
        monkeypatch.setenv('PAYPAL_WRITES_ENABLED', flag)
    calls = mock_write(monkeypatch)
    def unexpected(*args, **kwargs):
        pytest.fail('Disabled approval must not read PayPal or reserve an action')
    monkeypatch.setattr(main, 'get_access_token', unexpected)
    monkeypatch.setattr(database, 'reserve', unexpected)
    with postgres() as conn:
        before = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    result = approve(client, run)
    assert result.status_code == 403
    assert result.json()['detail'] == 'Demo mode: PayPal actions disabled.'
    assert calls == []
    with postgres() as conn:
        assert conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone() == before
    assert [e['event_type'] for e in events(postgres, run)] == ['INVESTIGATED']
    history = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH).json()
    assert history['paypal_writes_enabled'] is False
    assert history['runs'][0]['eligibility'] == 'INELIGIBLE'


@pytest.mark.parametrize('messages', [
    None, [], {}, [None], [{}],
    [{'posted_by': 'SELLER', 'content': 'incomplete'}],
    [{'posted_by': 'UNKNOWN', 'content': 'text', 'time_posted': '2026-01-01T00:00:00Z'}],
    [{'posted_by': 'SELLER', 'content': None, 'time_posted': '2026-01-01T00:00:00Z'}],
    [{'posted_by': 'SELLER', 'content': 'text', 'time_posted': 'invalid'}],
    [{'posted_by': 'SELLER', 'content': 'text', 'time_posted': '2026-01-01'}],
    [{'posted_by': 'SELLER', 'content': 'text', 'time_posted': '2999-01-01T00:00:00Z'}],
])
def test_untrusted_history_blocks_before_reservation(client, run, postgres, upstream, monkeypatch, messages):
    upstream['messages'] = messages
    calls = mock_write(monkeypatch)
    assert approve(client, run).status_code == 409
    assert calls == []
    assert [e['event_type'] for e in events(postgres, run)] == ['INVESTIGATED']
    with postgres() as conn:
        row = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    assert row['approval_state'] == 'PENDING'
    assert row['execution_status'] == 'NOT_STARTED'


@pytest.mark.parametrize('case', ['missing', 'capped', 'pagination', 'duplicate'])
def test_remote_history_protects_fresh_database(client, run, postgres, upstream, monkeypatch, case):
    if case == 'missing':
        del upstream['messages']
    elif case == 'capped':
        upstream['messages'] *= 1000
    elif case == 'pagination':
        upstream['links'].append({'rel': 'next', 'method': 'GET'})
    else:
        upstream['messages'].append({'posted_by': 'SELLER', 'content': main.MESSAGE,
                                     'time_posted': '2026-01-02T00:00:00Z'})
    calls = mock_write(monkeypatch)
    assert approve(client, run).status_code == 409
    assert calls == []
    assert [e['event_type'] for e in events(postgres, run)] == ['INVESTIGATED']


def test_buyer_copy_is_not_a_seller_duplicate(client, run, upstream, monkeypatch):
    upstream['messages'][0]['content'] = main.MESSAGE
    calls = mock_write(monkeypatch)
    assert approve(client, run).status_code == 200
    assert len(calls) == 1


def test_disabling_preserves_historical_success(client, run, postgres, monkeypatch):
    calls = mock_write(monkeypatch)
    assert approve(client, run).status_code == 200
    with postgres() as conn:
        before = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    audit_before = events(postgres, run)
    monkeypatch.setenv('PAYPAL_WRITES_ENABLED', 'false')
    history = client.get(f'/api/disputes/{DISPUTE}/history', headers=AUTH).json()
    assert history['paypal_writes_enabled'] is False
    assert history['runs'][0]['eligibility'] == 'ALREADY_SENT'
    assert history['approved_action']['execution_status'] == 'SUCCEEDED'
    assert approve(client, run).status_code == 403
    assert len(calls) == 1
    assert events(postgres, run) == audit_before
    with postgres() as conn:
        assert conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone() == before


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


def test_detail_link_success_is_persisted(client, run, postgres, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps({'links': [{
            'rel': 'detail', 'method': 'GET',
            'href': f'{main.DEFAULT_PAYPAL_BASE_URL}/v1/customer/disputes/{DISPUTE}',
        }]}).encode()
        return result

    monkeypatch.setattr(requests, 'post', post)
    result = approve(client, run)
    assert result.status_code == 200
    assert result.json()['execution_status'] == 'SUCCEEDED'
    assert approve(client, run).status_code == 409
    assert len(calls) == 1
    with postgres() as conn:
        row = conn.execute('SELECT * FROM runs WHERE run_id=%s', (run['run_id'],)).fetchone()
    assert row['execution_status'] == 'SUCCEEDED'
    assert row['executed_at'] is not None
    assert row['approved_by'] == 'test-merchant'
    assert [e['event_type'] for e in events(postgres, run)] == [
        'INVESTIGATED', 'APPROVED', 'EXECUTION_RESERVED', 'SUCCEEDED',
    ]


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
    (200, {'links': [{'rel': 'detail', 'method': 'GET',
                     'href': f'https://api-m.sandbox.paypal.com/v1/customer/disputes/{DISPUTE}'}]},
     'SUCCEEDED'),
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


@pytest.mark.parametrize('case', ['confirmed', 'missing', 'duplicate', 'buyer', 'old'])
def test_reconciliation_preserves_history_without_resending(
    client, run, postgres, case,
):
    database.reserve(run['run_id'], DISPUTE, 'test-merchant', {'dispute_id': DISPUTE})
    original_result = {'http_status': 200, 'body': {'links': [{
        'rel': 'detail', 'method': 'GET',
        'href': f'{main.DEFAULT_PAYPAL_BASE_URL}/v1/customer/disputes/{DISPUTE}',
    }]}}
    database.finish(run['run_id'], 'REQUIRES_RECONCILIATION', original_result,
                    'test-merchant')
    before = events(postgres, run)
    with postgres() as conn:
        original = conn.execute('SELECT * FROM runs WHERE run_id=%s',
                                (run['run_id'],)).fetchone()
    message = {'content': main.MESSAGE, 'posted_by': 'SELLER',
               'time_posted': datetime.now(timezone.utc).isoformat()}
    messages = [message]
    if case == 'missing':
        messages = []
    elif case == 'duplicate':
        messages = [message, message]
    elif case == 'buyer':
        message['posted_by'] = 'BUYER'
    elif case == 'old':
        message['time_posted'] = '2000-01-01T00:00:00Z'
    payload = {'dispute_id': DISPUTE, 'messages': messages}
    if case == 'confirmed':
        database.reconcile_message(run['run_id'], payload, 'test-merchant')
        assert events(postgres, run)[:-1] == before
        assert events(postgres, run)[-1]['data']['reconciliation'] is True
    else:
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            database.reconcile_message(run['run_id'], payload, 'test-merchant')
        assert events(postgres, run) == before
    with postgres() as conn:
        after = conn.execute('SELECT * FROM runs WHERE run_id=%s',
                             (run['run_id'],)).fetchone()
    for key in ('approved_by', 'approved_at', 'idempotency_key', 'paypal_result'):
        assert after[key] == original[key]
    assert after['execution_status'] == (
        'SUCCEEDED' if case == 'confirmed' else 'REQUIRES_RECONCILIATION'
    )
    assert approve(client, run).status_code == 409
