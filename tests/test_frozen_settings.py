"""0.9凍結設定的離線回歸；不讀.env或呼叫API。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hr_rag.settings import OpenAISettings

ROOT = Path(__file__).resolve().parents[1]


def test_default_generation_matches_frozen_lock():
    lock = json.loads((ROOT / "config/models.lock.json").read_text(encoding="utf-8"))
    settings = OpenAISettings()
    assert lock["default_generation_provider"] == "openai"
    frozen = lock["openai_generator"]
    for name, value in frozen["settings"].items():
        assert settings.model_dump(mode="json")[name] == value, name
    assert settings.model == "gpt-4.1-mini-2025-04-14"
    assert settings.cost_ledger_path == ROOT / ".runtime/openai-cost.sqlite3"
    assert settings.encoder_strategy == "resident"
    assert 36.3031 < settings.p95_alert_seconds < settings.timeout_seconds
    # 舊生成器專供重現第一次實測，不能因正式切換而遺失。
    assert lock["generator"]["filename"] == "qwen2.5-1.5b-instruct-q4_k_m.gguf"


def test_default_ledger_is_independent_of_working_directory(monkeypatch, tmp_path):
    before = OpenAISettings().cost_ledger_path
    monkeypatch.chdir(tmp_path)
    assert OpenAISettings().cost_ledger_path == before
    assert before.is_absolute()


@pytest.mark.parametrize("alert", [60, 61])
def test_alert_cannot_reach_timeout(alert):
    with pytest.raises(ValidationError):
        OpenAISettings(p95_alert_seconds=alert)


def test_new_model_cannot_inherit_mini_prices():
    with pytest.raises(ValidationError):
        OpenAISettings(model="unpriced-alternative")
    settings = OpenAISettings(
        model="offline-alternative",
        input_usd_per_million="1",
        output_usd_per_million="2",
        pricing_checked_on="2026-10-18",
    )
    assert settings.model == "offline-alternative"


def test_frozen_budget_accepts_boundary_and_rejects_overflow():
    settings = OpenAISettings()
    settings.check_request_tokens(3456, evidence_tokens=2048)
    with pytest.raises(ValueError):
        settings.check_request_tokens(3457, evidence_tokens=2048)
    with pytest.raises(ValueError):
        settings.check_request_tokens(2484, evidence_tokens=2049)
    # 保留0.8最大完整payload空間，不靠放寬預算通過。
    settings.check_request_tokens(2484, evidence_tokens=1957)
