"""只用暫存假設定驗證.env載入；不讀使用者的真實金鑰。"""

import os
from decimal import Decimal

import pytest

from hr_rag import settings
from hr_rag.providers import OpenAIGenerator, ProviderError

FAKE_KEY = "offline-fixture-secret"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(settings, "PROJECT_ENV_PATH", path, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HR_RAG_COST_LIMIT_USD", raising=False)
    return path


def configured():
    return OpenAIGenerator(
        settings.OpenAISettings(
            model="fixture",
            input_usd_per_million="1",
            output_usd_per_million="2",
            pricing_checked_on="2026-10-18",
        )
    )._configured()


def test_loads_project_file_independent_of_working_directory(env_file, monkeypatch):
    env_file.write_text(
        f"OPENAI_API_KEY={FAKE_KEY}\nHR_RAG_COST_LIMIT_USD=1.00\n",
        encoding="utf-8",
    )
    elsewhere = env_file.parent / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("OPENAI_API_KEY=wrong-file\n", encoding="utf-8")
    monkeypatch.chdir(elsewhere)
    key, limit = configured()
    assert key == FAKE_KEY
    assert limit == Decimal("1.00")
    assert "OPENAI_API_KEY" not in os.environ


def test_environment_overrides_file_even_when_empty(env_file, monkeypatch):
    env_file.write_text(
        f"OPENAI_API_KEY={FAKE_KEY}\nHR_RAG_COST_LIMIT_USD=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "environment-fixture")
    assert configured() == ("environment-fixture", Decimal("1"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(ProviderError, match="^not_configured$"):
        configured()


def test_missing_file_allows_existing_environment(env_file, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "2")
    assert configured() == (FAKE_KEY, Decimal("2"))


def test_missing_file_and_key_is_controlled(env_file):
    with pytest.raises(ProviderError, match="^not_configured$"):
        configured()


@pytest.mark.parametrize("quote", ["'", '"', ""])
def test_bom_quotes_comments_and_unknown_names(env_file, quote, capsys, caplog):
    env_file.write_text(
        f"# 設定\nexport OPENAI_API_KEY = {quote}{FAKE_KEY}{quote} # 註解\n"
        "HR_RAG_COST_LIMIT_USD = 1.00\n"
        "OPENAI_BASE_URL=https://untrusted.example\nHR_RAG_LIVE_API=1\n",
        encoding="utf-8-sig",
    )
    assert configured() == (FAKE_KEY, Decimal("1"))
    assert settings.OpenAISettings().base_url == "https://api.openai.com/v1"
    assert FAKE_KEY not in capsys.readouterr().out + caplog.text


@pytest.mark.parametrize("bad_value", [f'"{FAKE_KEY}', f"'{FAKE_KEY}' trailing"])
def test_invalid_file_never_exposes_content(env_file, bad_value, capsys, caplog):
    env_file.write_text(
        f"OPENAI_API_KEY={bad_value}\nHR_RAG_COST_LIMIT_USD=1\n",
        encoding="utf-8",
    )
    with pytest.raises(ProviderError, match="^not_configured$") as caught:
        configured()
    assert FAKE_KEY not in str(caught.value) + capsys.readouterr().out + caplog.text


def test_values_are_literal_not_shell_or_variable_expansion(env_file):
    env_file.write_text(
        "OPENAI_API_KEY=${SECRET}$(command)\nHR_RAG_COST_LIMIT_USD=1\n",
        encoding="utf-8",
    )
    assert configured()[0] == "${SECRET}$(command)"


def test_file_changes_are_read_on_next_call(env_file):
    env_file.write_text(
        f"OPENAI_API_KEY={FAKE_KEY}\nHR_RAG_COST_LIMIT_USD=1\n",
        encoding="utf-8",
    )
    assert configured()[1] == Decimal("1")
    env_file.write_text(
        f"OPENAI_API_KEY={FAKE_KEY}\nHR_RAG_COST_LIMIT_USD=2\n",
        encoding="utf-8",
    )
    assert configured()[1] == Decimal("2")
