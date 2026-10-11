import ast
import json

from evaluation import run_evaluation
from evaluation.scenarios import SCENARIOS


def test_scenario_matrix_is_complete_and_unique() -> None:
    expected = {
        "INR-01", "INR-02", "INR-03", "INR-04", "INR-05", "INR-06",
        "NAD-01", "NAD-02", "AUTH-01", "AUTH-02", "SAFE-01", "SAFE-02",
    }
    assert {scenario.scenario_id for scenario in SCENARIOS} == expected
    assert len(SCENARIOS) == len(expected)
    assert all(scenario.explanation for scenario in SCENARIOS)


def test_all_scenarios_match_independent_expectations() -> None:
    result = run_evaluation.run()
    assert result["metadata"]["mode"] == "OFFLINE_MOCKED"
    assert result["metrics"]["deterministic_expectation_passes"] == 12
    assert result["metrics"]["grounded_validation_passes"] == 12
    assert all(item["passed"] for item in result["scenarios"])


def test_reports_reflect_actual_results() -> None:
    result = run_evaluation.run()
    report = run_evaluation.render_report(result)
    assert "12/12 (100.0%)" in report
    assert "OFFLINE_MOCKED" in report
    assert "Unauthorized write attempts/executions: 0/0" in report
    for item in result["scenarios"]:
        assert f"| {item['scenario_id']} |" in report
    assert json.loads(json.dumps(result))["metrics"] == result["metrics"]


def test_evaluation_needs_no_credentials(monkeypatch) -> None:
    for name in (
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "GEMINI_API_KEY",
        "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    result = run_evaluation.run()
    assert result["metrics"]["total_scenarios"] == 12
    assert result["metrics"]["unauthorized_write_executions"] == 0


def test_failure_returns_nonzero(monkeypatch) -> None:
    result = run_evaluation.run()
    result["metrics"]["deterministic_expectation_passes"] = 11
    monkeypatch.setattr(run_evaluation, "run", lambda: result)
    monkeypatch.setattr(
        run_evaluation.argparse.ArgumentParser,
        "parse_args",
        lambda self: type("Args", (), {
            "check": True, "live": False, "dry_run": False, "confirm_live": False,
        })(),
    )
    assert run_evaluation.main() == 1


def test_evaluation_path_has_no_external_clients_or_write_modules() -> None:
    source = (run_evaluation.ROOT / "evaluation" / "run_evaluation.py").read_text()
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not imports & {"requests", "httpx", "backend.paypal_writes"}
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr == "Client"
        and isinstance(node.value, ast.Name)
        and node.value.id == "genai"
        for node in ast.walk(tree)
    )
