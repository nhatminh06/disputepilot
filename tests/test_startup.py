from urllib.parse import unquote, urlsplit
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from backend import database, main, start


def test_compose_start_requires_explicit_configuration(monkeypatch):
    monkeypatch.delenv('DISPUTEPILOT_COMPOSE', raising=False)
    with pytest.raises(SystemExit, match='Compose database configuration'):
        start.main()
    monkeypatch.setenv('DISPUTEPILOT_COMPOSE', 'true')
    monkeypatch.delenv('COMPOSE_POSTGRES_PASSWORD', raising=False)
    with pytest.raises(SystemExit, match='Compose database configuration'):
        start.main()


def test_start_initializes_existing_schema_before_serving(monkeypatch):
    password = 'synthetic-test-only@:/?# value'
    monkeypatch.setenv('DISPUTEPILOT_COMPOSE', 'true')
    monkeypatch.setenv('COMPOSE_POSTGRES_PASSWORD', password)
    monkeypatch.setenv('DEV_MERCHANT_ID', 'test-merchant')
    monkeypatch.setenv('DEV_MERCHANT_TOKEN', 'synthetic-development-test-token-only')
    monkeypatch.setenv('PAYPAL_BASE_URL', main.DEFAULT_PAYPAL_BASE_URL)
    monkeypatch.setenv('DATABASE_URL', 'ignored-host-configuration')
    events = []
    monkeypatch.setattr(database, 'initialize', lambda: events.append('schema'))
    monkeypatch.setattr(start.uvicorn, 'run', lambda app, **kwargs: events.append(kwargs))
    start.main()
    assert events == ['schema', {'host': '0.0.0.0', 'port': 8000}]
    parsed = urlsplit(start.os.environ['DATABASE_URL'])
    assert parsed.hostname == 'postgres'
    assert parsed.port == 5432
    assert parsed.username == 'disputepilot'
    assert parsed.path == '/disputepilot'
    assert unquote(parsed.password) == password


def test_start_rejects_non_sandbox_before_database_access(monkeypatch):
    monkeypatch.setenv('DISPUTEPILOT_COMPOSE', 'true')
    monkeypatch.setenv('COMPOSE_POSTGRES_PASSWORD', 'synthetic-test-only')
    monkeypatch.setenv('DATABASE_URL', 'ignored-host-configuration')
    monkeypatch.setenv('PAYPAL_BASE_URL', 'https://api-m.paypal.com')
    initialize = Mock()
    monkeypatch.setattr(database, 'initialize', initialize)
    with pytest.raises(HTTPException):
        start.main()
    initialize.assert_not_called()
