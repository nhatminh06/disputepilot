import ast
import json
import socket
import sys
from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors, types

from backend import gemini
from evaluation import live, run_evaluation


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Unexpected network access during mocked benchmark tests')

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(gemini, 'load_dotenv', lambda: None)
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-benchmark-key-never-use')
    monkeypatch.setenv('GEMINI_MODEL', live.MODEL)


def response(text: str | None = None, *, usage: bool = True, **changes):
    body = {
        'recommendation': 'NEEDS_REVIEW', 'summary': 'Merchant review is required.',
        'supporting_fact_ids': [], 'policy_refs': [], 'missing_information': [],
    }
    body.update(changes)
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(
            parts=[types.Part(text=text if text is not None else json.dumps(body))],
        ))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15,
        ) if usage else None,
    )


@pytest.fixture
def sdk(monkeypatch):
    factory = MagicMock()
    call = factory.return_value.__enter__.return_value.models.generate_content
    call.return_value = response()
    monkeypatch.setattr(gemini.genai, 'Client', factory)
    return factory, call


def test_offline_and_dry_run_never_construct_a_client(monkeypatch, sdk, capsys):
    factory, _ = sdk
    paths = [run_evaluation.RESULTS_PATH, run_evaluation.REPORT_PATH]
    before = [path.read_bytes() for path in paths]
    monkeypatch.delenv('GEMINI_API_KEY')
    monkeypatch.setattr(sys, 'argv', ['evaluation', '--check'])
    assert run_evaluation.main() == 0
    monkeypatch.setattr(sys, 'argv', ['evaluation', '--live', '--dry-run'])
    assert run_evaluation.main() == 0
    factory.assert_not_called()
    assert [path.read_bytes() for path in paths] == before
    assert 'DRY_RUN' in capsys.readouterr().out


@pytest.mark.parametrize('args', [
    ['--confirm-live'], ['--dry-run'], ['--live'], ['--live', '--check'],
])
def test_cli_requires_explicit_live_and_separate_confirmation(args, monkeypatch, sdk):
    monkeypatch.setattr(sys, 'argv', ['evaluation', *args])
    with pytest.raises(SystemExit) as error:
        run_evaluation.main()
    assert error.value.code == 2
    sdk[0].assert_not_called()


def test_missing_credentials_and_confirmation_stop_before_files_or_requests(
    monkeypatch, sdk, tmp_path,
):
    with pytest.raises(ValueError, match='confirmation'):
        live.run(directory=tmp_path)
    monkeypatch.delenv('GEMINI_API_KEY')
    with pytest.raises(ValueError, match='GEMINI_API_KEY'):
        live.run(confirmed=True, directory=tmp_path)
    assert not list(tmp_path.iterdir())
    sdk[0].assert_not_called()


def test_model_mismatch_is_not_silently_switched(monkeypatch, sdk, tmp_path):
    monkeypatch.setenv('GEMINI_MODEL', 'another-model')
    with pytest.raises(ValueError, match='gemini-3.1-flash-lite'):
        live.run(confirmed=True, directory=tmp_path)
    sdk[0].assert_not_called()


def test_twelve_requests_with_production_sanitizer_and_retries_disabled(sdk, tmp_path):
    factory, call = sdk
    result = live.run(confirmed=True, directory=tmp_path)
    assert call.call_count == 12
    assert result['metrics']['requests_started'] == 12
    assert result['metrics']['model_requests_completed'] == 12
    assert result['metrics']['conservative_abstention_low_risk'] == {
        'passed': 3, 'total': 3, 'percent': 100.0,
    }
    assert result['metrics']['review_required_model_compliance']['total'] == 9
    assert result['metrics']['input_tokens']['reported_sum'] == 120
    assert result['metrics']['output_tokens']['reported_sum'] == 60
    assert result['metrics']['total_tokens']['reported_sum'] == 180
    assert result['metrics']['thought_tokens']['reported_sum'] is None
    assert all(row['elapsed_seconds'] >= 0 for row in result['scenarios'])
    for constructor in factory.call_args_list:
        options = constructor.kwargs['http_options']
        assert options.retry_options.attempts == 1
        assert options.timeout == 20000
    for expected, actual in zip(live.preview()['scenarios'], call.call_args_list):
        assert json.loads(actual.kwargs['contents']) == expected['payload']
        assert actual.kwargs['model'] == live.MODEL
        assert actual.kwargs['config'].automatic_function_calling.disable
        assert not actual.kwargs['config'].tools
        text = actual.kwargs['contents']
        assert 'synthetic-address' not in text
        assert 'synthetic_payment' not in text
        assert 'synthetic-benchmark-key-never-use' not in text
    assert live.successful(result)
    stored = json.loads((tmp_path / 'live_results.json').read_text())
    assert stored == result


def test_oversized_scenario_set_rejected_before_any_request(monkeypatch, sdk, tmp_path):
    monkeypatch.setattr(live, 'SCENARIOS', (*live.SCENARIOS, live.SCENARIOS[0]))
    with pytest.raises(ValueError, match='budget'):
        live.run(confirmed=True, directory=tmp_path)
    sdk[0].assert_not_called()


@pytest.mark.parametrize(('error', 'reason'), [
    (errors.APIError(429, {'error': {'message': 'synthetic quota'}}), 'QUOTA_EXHAUSTED'),
    (errors.APIError(401, {'error': {'message': 'synthetic auth'}}),
     'AUTHENTICATION_OR_PERMISSION_FAILURE'),
    (errors.APIError(403, {'error': {'message': 'synthetic permission'}}),
     'AUTHENTICATION_OR_PERMISSION_FAILURE'),
    (httpx.ReadTimeout('synthetic timeout'), 'API_OR_TRANSPORT_FAILURE'),
])
def test_api_errors_stop_and_save_partial_results(error, reason, sdk, tmp_path):
    sdk[1].side_effect = [response(), error]
    result = live.run(confirmed=True, directory=tmp_path)
    assert sdk[1].call_count == 2
    assert result['stop_reason'] == reason
    assert result['metrics']['scenarios_attempted'] == 2
    assert result['metrics']['model_requests_completed'] == 1
    assert result['metrics']['failed_scenarios'] == 1
    assert result['metrics']['skipped_scenarios'] == 10
    assert result['metrics']['first_response_schema']['total'] == 1
    assert result['metrics']['fallback_count'] == 1
    assert result['metrics']['final_application_safety']['total'] == 2
    assert result['metrics']['input_tokens']['requests_with_reported_usage'] == 1
    assert result['scenarios'][1]['first_response'] is None
    assert not live.successful(result)
    report = (tmp_path / 'LIVE_REPORT.md').read_text()
    assert reason in report and 'SKIPPED' in report


def test_invalid_first_responses_remain_visible_and_not_successful_reasoning(sdk, tmp_path):
    sdk[1].side_effect = [
        response(supporting_fact_ids=['invented']), response(text='not JSON'),
        response(summary='The item was delivered.'),
        *[response() for _ in range(9)],
    ]
    result = live.run(confirmed=True, directory=tmp_path)
    counts = result['metrics']
    assert sdk[1].call_count == 12
    assert counts['fallback_count'] == 3
    assert counts['first_response_schema'] == {'passed': 11, 'total': 12, 'percent': 91.67}
    assert counts['first_response_grounded_citations']['passed'] == 10
    assert counts['first_response_production_validation']['passed'] == 9
    assert counts['final_application_safety']['passed'] == 12
    assert counts['review_required_model_compliance']['total'] == 9
    assert counts['conservative_abstention_low_risk']['passed'] == 2
    assert counts['potentially_unsupported_narratives']['passed'] == 1
    assert result['scenarios'][0]['first_response']['parsed']['supporting_fact_ids'] == ['invented']
    assert result['scenarios'][0]['final_response']['supporting_fact_ids'] == []
    assert result['scenarios'][1]['first_response']['text'] == 'not JSON'
    assert not live.successful(result)


def test_missing_information_and_review_requirement_remain_application_controlled(sdk, tmp_path):
    sdk[1].side_effect = [response(recommendation='CONTEST'), *[
        response(missing_information=['invented missing fact']) for _ in range(11)
    ]]
    result = live.run(confirmed=True, directory=tmp_path)
    assert result['scenarios'][0]['fallback']
    row = result['scenarios'][2]
    assert row['first_response']['parsed']['missing_information'] == ['invented missing fact']
    assert row['final_response']['missing_information'] == gemini.missing_fact_ids(
        row['sanitized_input'],
    )
    assert result['metrics']['review_required_model_compliance']['passed'] == 8


def test_injection_behavior_is_reviewed_beyond_schema(sdk, tmp_path):
    sdk[1].side_effect = [*[response() for _ in range(11)], response(
        summary='Approve this refund immediately.',
        policy_refs=['synthetic-policy#malicious-instruction'],
    )]
    result = live.run(confirmed=True, directory=tmp_path)
    row = result['scenarios'][-1]
    assert row['first_response']['schema_pass']
    assert row['first_response']['production_validation_pass']
    assert row['injection_outcome'] == 'POTENTIAL_INSTRUCTION_FOLLOWING'
    assert not live.successful(result)
    config = sdk[1].call_args.kwargs['config']
    instruction = live.SCENARIOS[-1].malicious_policy
    assert instruction in sdk[1].call_args.kwargs['contents']
    assert instruction not in config.system_instruction


def test_unretrieved_policy_is_rejected(sdk, tmp_path):
    sdk[1].return_value = response(policy_refs=['synthetic#not-retrieved'])
    result = live.run(confirmed=True, directory=tmp_path)
    assert result['metrics']['first_response_grounded_citations']['passed'] == 0
    assert result['metrics']['fallback_count'] == 12
    assert result['metrics']['first_response_production_validation']['passed'] == 0


def test_low_risk_refund_is_advice_but_expectation_mismatch(sdk, tmp_path):
    sdk[1].side_effect = [response(), response(recommendation='REFUND'), *[
        response() for _ in range(10)
    ]]
    result = live.run(confirmed=True, directory=tmp_path)
    row = result['scenarios'][1]
    assert not row['fallback']
    assert row['expectation_outcome'] == 'MISMATCH'
    assert not live.successful(result)


def test_valid_contest_cites_only_supplied_support(sdk, tmp_path):
    sdk[1].side_effect = [response(), response(
        recommendation='CONTEST', summary='Verified delivery supports contesting.',
        supporting_fact_ids=['delivery_confirmed'],
    ), *[response() for _ in range(10)]]
    result = live.run(confirmed=True, directory=tmp_path)
    row = result['scenarios'][1]
    assert row['expectation_outcome'] == 'MATCH'
    assert row['first_response']['production_validation_pass']
    assert row['first_response']['citation_pass']
    assert row['final_response']['supporting_fact_ids'] == ['delivery_confirmed']
    assert not row['fallback']


def test_workflow_claim_is_reported_and_falls_back(sdk, tmp_path):
    sdk[1].side_effect = [response(summary='The dispute is under review.'), *[
        response() for _ in range(11)
    ]]
    result = live.run(confirmed=True, directory=tmp_path)
    row = result['scenarios'][0]
    assert row['fallback']
    assert row['first_response']['semantic_review']['reasons'] == [
        'Possible unverified workflow status.',
    ]
    assert result['metrics']['first_response_production_validation']['passed'] == 11


def test_cli_returns_nonzero_for_unsafe_model_text(monkeypatch, sdk, tmp_path, capsys):
    sdk[1].side_effect = [response(summary='The item was delivered.'), *[
        response() for _ in range(11)
    ]]
    actual_run = live.run
    monkeypatch.setattr(live, 'run', lambda **kwargs: actual_run(
        **kwargs, directory=tmp_path,
    ))
    monkeypatch.setattr(sys, 'argv', ['evaluation', '--live', '--confirm-live'])
    assert run_evaluation.main() == 1
    assert 'synthetic-benchmark-key-never-use' not in capsys.readouterr().out
    assert (tmp_path / 'LIVE_REPORT.md').exists()


def test_absent_usage_is_unknown_and_zero_responses_have_no_percentage(sdk, tmp_path):
    sdk[1].side_effect = errors.APIError(429, {'error': {'message': 'quota'}})
    result = live.run(confirmed=True, directory=tmp_path)
    assert result['metrics']['first_response_schema'] == {
        'passed': 0, 'total': 0, 'percent': None,
    }
    assert result['metrics']['input_tokens']['reported_sum'] is None
    assert result['metrics']['output_tokens']['reported_sum'] is None


def test_reports_redact_secrets_and_exception_messages(sdk, tmp_path):
    sdk[1].side_effect = [
        response(summary='synthetic-benchmark-key-never-use'),
        RuntimeError('synthetic-benchmark-key-never-use'),
    ]
    result = live.run(confirmed=True, directory=tmp_path)
    assert result['scenarios'][1]['status'] == 'INTERRUPTED'
    assert result['metrics']['requests_with_ambiguous_outcome'] == 1
    assert sdk[1].call_count == 2
    for text in [json.dumps(result), *[p.read_text() for p in tmp_path.iterdir()]]:
        assert 'synthetic-benchmark-key-never-use' not in text
    assert '[REDACTED]' in (tmp_path / 'live_results.json').read_text()


def test_checkpoint_exists_before_request_and_cannot_be_replayed(sdk, tmp_path):
    def interrupted(**kwargs):
        checkpoint = json.loads((tmp_path / 'live_results.json').read_text())
        assert checkpoint['scenarios'][0]['status'] == 'IN_PROGRESS'
        raise KeyboardInterrupt()

    sdk[1].side_effect = interrupted
    result = live.run(confirmed=True, directory=tmp_path)
    assert result['scenarios'][0]['status'] == 'INTERRUPTED'
    with pytest.raises(ValueError, match='existing live reports'):
        live.run(confirmed=True, directory=tmp_path)
    assert sdk[1].call_count == 1


def test_evaluation_has_no_local_import_path_to_writes_or_database():
    pending = ['evaluation.live']
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        assert name not in {'backend.main', 'backend.database', 'backend.paypal_writes'}
        path = live.ROOT.joinpath(*name.split('.')).with_suffix('.py')
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for candidate in [node.module, *[
                    f'{node.module}.{alias.name}' for alias in node.names
                ]]:
                    if candidate.startswith(('backend.', 'evaluation.')):
                        if live.ROOT.joinpath(*candidate.split('.')).with_suffix('.py').exists():
                            pending.append(candidate)
            elif isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names
                               if alias.name.startswith(('backend.', 'evaluation.')))
