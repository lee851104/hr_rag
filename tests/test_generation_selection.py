"""第五階段人工驗收後的正式生成器選擇；離線，不讀.env或呼叫API。"""

import hashlib
import json
from pathlib import Path

import pytest

from hr_rag.answering import AnswerService
from hr_rag.generation import load_selected_generation, selected_generator
from hr_rag.verbatim import SourceSelection, VerbatimGenerator

ROOT = Path(__file__).resolve().parents[1]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_selected_generation_is_the_human_accepted_verbatim_candidate():
    lock = json.loads((ROOT / "config/models.lock.json").read_text("utf-8"))
    selected = lock["selected_generation"]
    config, settings = load_selected_generation()
    candidate = json.loads(
        (ROOT / "config/generation.verbatim-candidate-v3.json").read_text("utf-8")
    )
    assert config["status"] == "selected"
    assert config["candidate_sha256"] == _digest(
        ROOT / "config/generation.verbatim-candidate-v3.json"
    )
    for name in ("mode", "settings", "system", "schema", "implementation_sha256"):
        assert config[name] == candidate[name], name
    assert settings.model == "gpt-4.1-2025-04-14"
    assert (
        settings.model_dump(mode="json", exclude={"cost_ledger_path"})
        == (candidate["settings"])
    )
    # 已測payload／預算：4096上下文、2048證據、512輸出、128安全餘量。
    assert (settings.context_limit, settings.evidence_budget) == (4096, 2048)
    assert (settings.output_reserve, settings.safety_margin) == (512, 128)
    assert config["system"] == VerbatimGenerator.SYSTEM
    assert config["schema"] == SourceSelection.model_json_schema()
    for kind in ("development", "stability"):
        review = selected["human_review"][kind]
        assert review["passed"] is True
        assert _digest(ROOT / review["assessment"]) == review["assessment_sha256"]


def test_selected_generator_uses_verbatim_path_not_summary(tmp_path):
    generator = selected_generator()
    assert type(generator) is VerbatimGenerator
    assert generator.settings.model == "gpt-4.1-2025-04-14"


def test_history_lock_is_preserved():
    history = ROOT / "config/history/models.lock.2026-10-18.json"
    assert _digest(history) == (
        "77ab0f395e54a4c18c0786abcc5a052f16c91bf09232956b6a90e540577e58a8"
    )
    assert (
        json.loads(history.read_text("utf-8"))["openai_generator"]["settings"]["model"]
        == "gpt-4.1-mini-2025-04-14"
    )


@pytest.mark.parametrize("field", ["system", "settings", "status"])
def test_tampered_selection_is_rejected(tmp_path, field):
    lock = json.loads((ROOT / "config/models.lock.json").read_text("utf-8"))
    config = json.loads(
        (ROOT / lock["selected_generation"]["config"]).read_text("utf-8")
    )
    config[field] = {"system": "改過", "settings": {}, "status": "candidate"}[field]
    changed = tmp_path / "selected.json"
    changed.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="generation_selection_changed"):
        load_selected_generation(config_path=changed)


def test_answer_service_defaults_to_selected_generator():
    class Store:
        pass

    class Retriever:
        store = Store()

    service = AnswerService(retriever=Retriever())
    assert type(service.generator) is VerbatimGenerator
    assert service.generator.settings.model == "gpt-4.1-2025-04-14"
