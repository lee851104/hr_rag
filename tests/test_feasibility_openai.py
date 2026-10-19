"""實測命令的離線保護：不讀真實.env，也不呼叫API。"""

import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from hr_rag import feasibility_openai as runner
from hr_rag.audit import CostLedger
from hr_rag.providers import ProviderError


@pytest.fixture
def fixture():
    path = Path(__file__).resolve().parents[1] / "scripts/feasibility_long_context.py"
    spec = importlib.util.spec_from_file_location("feasibility_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("configured,expected", [("5", "1"), ("0.05", "0.05")])
def test_cap_clamps_and_restores_environment(monkeypatch, configured, expected):
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "previous")
    monkeypatch.setattr(
        runner,
        "load_generation_environment",
        lambda: {"OPENAI_API_KEY": "fake", "HR_RAG_COST_LIMIT_USD": configured},
    )
    with runner.capped_environment() as limit:
        assert limit == Decimal(expected)
        assert os.environ["HR_RAG_COST_LIMIT_USD"] == expected
    assert os.environ["HR_RAG_COST_LIMIT_USD"] == "previous"


@pytest.mark.parametrize("limit", ["", "NaN", "Infinity", "-1", "0"])
def test_invalid_limit_stops_before_api(monkeypatch, limit):
    monkeypatch.setattr(
        runner,
        "load_generation_environment",
        lambda: {"OPENAI_API_KEY": "fake", "HR_RAG_COST_LIMIT_USD": limit},
    )
    with pytest.raises(ProviderError, match="not_configured"):
        with runner.capped_environment():
            pytest.fail("不可開始實測")


def test_ledger_counts_previous_costs_and_unknown_reservations(tmp_path):
    path = tmp_path / "cost.sqlite3"
    assert runner.ledger_totals(path)["total_usd"] == "0"
    ledger = CostLedger(path)
    ticket = ledger.reserve(Decimal("0.2"), Decimal(1))
    ledger.settle(ticket, Decimal("0.03"))
    ledger.reserve(Decimal("0.4"), Decimal(1))
    assert runner.ledger_totals(path) == {
        "settled_usd": "0.03",
        "reserved_usd": "0.4",
        "total_usd": "0.43",
        "requests": 2,
    }


def test_report_preserves_previous_runs_and_redacts(tmp_path):
    path = tmp_path / "report.json"
    runner.save_run(path, {"id": "first", "rows": []}, "secret")
    runner.save_run(path, {"id": "second", "rows": ["secret"]}, "secret")
    runner.save_run(path, {"id": "second", "rows": ["updated secret"]}, "secret")
    report = json.loads(path.read_text(encoding="utf-8"))
    assert len(report["runs"]) == 2
    assert report["runs"][0] == {"id": "first", "rows": []}
    assert "secret" not in path.read_text(encoding="utf-8")


def test_fixed_context_is_unchanged_and_settings_share_ledger(fixture):
    evidence = json.loads(fixture.EVIDENCE_PATH.read_text(encoding="utf-8"))
    context = runner.build_context(fixture, evidence)
    assert [unit.id for unit in context.units] == fixture.BUNDLE
    assert len(evidence["units"]) == 20
    for model in runner.MODELS:
        settings = runner.model_settings(model, fixture.ROOT)
        assert (
            settings.cost_ledger_path == fixture.ROOT / ".runtime/openai-cost.sqlite3"
        )
        assert settings.context_limit == 4096
        assert settings.output_reserve == 512
    with pytest.raises(ValueError):
        runner.model_settings("unpriced-model", fixture.ROOT)


def test_summary_includes_failed_response_cost_and_rejects_partial_run():
    rows = [
        {
            "checks": {"auto_pass": False},
            "total_seconds": 2,
            "exchanges": [{"cost": 0.002}],
        }
    ]
    summary = runner.summarize(rows, 60)
    assert summary["cost_usd"] == "0.002"
    assert not summary["automatic_gate_pass"]
    assert not runner.summarize([], 60)["automatic_gate_pass"]


def test_cli_openai_does_not_invoke_local_generator(fixture, monkeypatch):
    received = []
    monkeypatch.setattr(
        runner, "run", lambda models, source: received.append(models) or 0
    )
    monkeypatch.setattr(fixture, "run", lambda *args: pytest.fail("本機生成被呼叫"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "script",
            "run",
            "--strategy",
            "resident",
            "--provider",
            "openai",
            "--model",
            next(iter(runner.MODELS)),
        ],
    )
    assert fixture.main() == 0
    assert received == [[next(iter(runner.MODELS))]]


@pytest.mark.parametrize(
    "error,expected_rows",
    [(None, 10), ("invalid_output", 10), ("timeout", 1), ("retry_success", 10)],
)
def test_run_saves_results_and_stops_on_unknown_cost(
    fixture, monkeypatch, tmp_path, error, expected_rows
):
    import socket
    from types import SimpleNamespace

    import numpy as np

    from hr_rag import local_models
    from hr_rag.contracts import Answer

    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("不可連網"))
    monkeypatch.setattr(
        runner,
        "load_generation_environment",
        lambda: {
            "OPENAI_API_KEY": "fake-test-secret",
            "HR_RAG_COST_LIMIT_USD": "1",
        },
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config/models.lock.json").write_text("{}", encoding="utf-8")
    original = fixture.REPORT_PATH.read_bytes()
    fixture.ROOT = tmp_path

    class Encoder:
        def __init__(self, *args):
            self.process = SimpleNamespace(pid=os.getpid())

        def embed(self, texts):
            return np.ones((len(texts), 2))

        def rerank(self, question, texts):
            return [0.1] * len(texts)

        def close(self):
            pass

    def generate(self, question, context):
        if error == "retry_success":
            self.ledger.reserve(Decimal("0.01"), Decimal(1))
        ticket = self.ledger.reserve(Decimal("0.01"), Decimal(1))
        if error == "timeout":
            raise ProviderError(error)
        self.ledger.settle(ticket, Decimal("0.001"))
        self.on_exchange({"cost": 0.001, "response": "fake-test-secret"})
        if error == "invalid_output":
            raise ProviderError(error)
        return Answer(status="insufficient", claims=(), citations=(), reason="資料不足")

    monkeypatch.setattr(local_models, "LocalEncoder", Encoder)
    monkeypatch.setattr(runner.OpenAIGenerator, "_payload", lambda *args: None)
    monkeypatch.setattr(runner.OpenAIGenerator, "generate", generate)
    assert runner.run(list(runner.MODELS), fixture) == (1 if error == "timeout" else 0)
    path = tmp_path / "reports/feasibility-long-context-openai.json"
    text = path.read_text(encoding="utf-8")
    result = json.loads(text)["runs"][0]
    assert sum(len(model["rows"]) for model in result["models"]) == expected_rows
    expected_cost = "0.11" if error == "retry_success" else "0.01"
    assert Decimal(result["ledger_after"]["total_usd"]) == Decimal(expected_cost)
    assert "fake-test-secret" not in text
    assert fixture.REPORT_PATH.read_bytes() == original
    if error == "timeout":
        assert result["ledger_after"]["reserved_usd"] == "0.01"
        assert result["status"] == "stopped"
    if error in {"timeout", "retry_success"}:
        for model in result["models"]:
            assert model["summary"]["cost_usd"] is None
            assert model["summary"]["mean_cost_usd"] is None
            assert Decimal(model["summary"]["reserved_cost_usd"]) > 0
