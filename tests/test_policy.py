from pathlib import Path

import pytest

from backend import policy


@pytest.mark.parametrize(('query', 'expected'), [
    ('shipping tracking', 'shipping'), ('refund eligibility', 'refunds'),
    ('returns condition', 'returns'),
])
def test_relevant_policy(query, expected):
    assert policy.search_policy(query)[0]['policy_id'] == expected


def test_irrelevant_query():
    assert policy.search_policy('astronomy telescope') == []
    assert policy.search_policy('') == []


def test_exact_stable_sources():
    results = policy.search_policy('shipping tracking delivery missing')
    assert len(results) == 3
    assert results == policy.search_policy('shipping tracking delivery missing')
    for item in results:
        assert item['excerpt'] in Path(item['source_path']).read_text()
        assert item['section_id']
        assert len(item['excerpt']) <= 1200


def test_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'POLICY_DIR', tmp_path)
    assert policy.search_policy('shipping') == []
    monkeypatch.setattr(policy, 'POLICY_DIR', tmp_path / 'missing')
    assert policy.search_policy('shipping') == []


def test_symlink_cannot_escape_directory(tmp_path, monkeypatch):
    (tmp_path / 'shipping.md').symlink_to(Path('AGENTS.md').resolve())
    monkeypatch.setattr(policy, 'POLICY_DIR', tmp_path)
    with pytest.raises(OSError):
        policy.search_policy('shipping')


@pytest.mark.parametrize(('query', 'limit'), [('x' * 501, 3), ('shipping', 4),
                                           ('shipping', 0)])
def test_input_bounds(query, limit):
    with pytest.raises(ValueError):
        policy.search_policy(query, limit)


def test_excerpt_bound_and_fidelity(tmp_path, monkeypatch):
    text = '## Shipping\n' + 'tracking ' * 200
    (tmp_path / 'shipping.md').write_text(text)
    monkeypatch.setattr(policy, 'POLICY_DIR', tmp_path)
    assert policy.search_policy('tracking')[0]['excerpt'] == text[:1200]
