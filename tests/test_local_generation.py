"""本機Ollama生成候選：只換端點與模型，選段提示、schema與驗證沿用正式路徑。"""

import json
import socket
from decimal import Decimal

import httpx2
import openai
import pytest
import tiktoken
from pydantic import ValidationError

from hr_rag import local_generation
from hr_rag.contracts import Answer, Chunk, ContextBundle
from hr_rag.providers import ProviderError
from hr_rag.settings import OllamaSettings
from hr_rag.verbatim import VerbatimGenerator

MODEL = "gemma4:e2b-it-q8_0"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    # 本機候選不得讀OpenAI金鑰；清掉環境與.env也要能運作。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HR_RAG_COST_LIMIT_USD", raising=False)
    monkeypatch.setattr("hr_rag.settings.PROJECT_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(tmp_path / "events.jsonl"))

    def no_network(*args, **kwargs):
        pytest.fail("離線測試不可連網")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    encoding = tiktoken.Encoding(
        name="offline-bytes",
        pat_str=r"[\s\S]",
        mergeable_ranks={bytes([n]): n for n in range(256)},
        special_tokens={},
    )
    monkeypatch.setattr(tiktoken, "get_encoding", lambda name: encoding)

    def unknown(model):
        raise KeyError(model)

    monkeypatch.setattr(tiktoken, "encoding_for_model", unknown)


@pytest.fixture
def context():
    return ContextBundle(
        units=[
            Chunk(
                id="s1",
                document_id="O03",
                version_id="v1",
                section_id="2",
                parent_id="p1",
                text="勞工結婚者給予婚假十四日，工資照給。",
                allowed_roles=["employee"],
                effective_from="2026-01-01",
            )
        ],
        citation_map={"s1": ["O03/v1/2"]},
        token_count=0,
        dropped_reasons=[],
        config_hash="h",
    )


def settings(tmp_path, **kwargs):
    values = dict(model=MODEL, cost_ledger_path=tmp_path / "ollama-cost.sqlite3")
    values.update(kwargs)
    return OllamaSettings(**values)


def test_settings_allow_only_local_ollama_endpoint(tmp_path):
    local = settings(tmp_path)
    assert local.provider == "ollama"
    assert local.base_url == "http://127.0.0.1:11434/v1"
    assert local.reasoning_effort == "none"
    assert local.input_usd_per_million == 0 == local.output_usd_per_million
    for url in (
        "https://api.openai.com/v1",
        "http://example.com:11434/v1",
        "http://127.0.0.1:11434/v1?x=1",
        "http://user:pw@127.0.0.1:11434/v1",
    ):
        with pytest.raises(ValidationError):
            settings(tmp_path, base_url=url)
    with pytest.raises(ValidationError):
        settings(tmp_path, model="gemma4 latest")


def _response(text, model=MODEL):
    return {
        "id": "resp_local",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_local",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "annotations": [], "text": text}],
            }
        ],
        "usage": {
            "input_tokens": 120,
            "output_tokens": 20,
            "total_tokens": 140,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "parallel_tool_calls": False,
        "tools": [],
        "tool_choice": "auto",
        "text": {"format": {"type": "text"}},
        "metadata": {},
    }


def generator(tmp_path, text, model=MODEL):
    calls, exchanges = [], []

    def respond(request):
        calls.append(request)
        return httpx2.Response(200, json=_response(text, model))

    client = openai.OpenAI(
        api_key="unused",
        base_url="http://127.0.0.1:11434/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
    )
    instance = local_generation.LocalVerbatimGenerator(
        settings(tmp_path), client=client, on_exchange=exchanges.append
    )
    return instance, calls, exchanges


def test_local_generator_reuses_verbatim_selection_without_api_key(tmp_path, context):
    selection = {"status": "answered", "source_ids": ["s1"], "reason": None}
    instance, calls, exchanges = generator(tmp_path, json.dumps(selection))
    answer = instance.generate("婚假幾天？", context)
    assert isinstance(instance, VerbatimGenerator)
    assert answer.status == "answered" and answer.citations == ("s1",)
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "http://127.0.0.1:11434/v1/responses"
    assert body["model"] == MODEL and body["reasoning"] == {"effort": "none"}
    assert body["instructions"] == VerbatimGenerator.SYSTEM
    assert exchanges[0]["cost"] == 0


def test_local_schema_does_not_offer_error_status(tmp_path, context):
    # error是系統狀態，不是模型可選的判斷；本機模型會誤選它而整題失敗。
    selection = {"status": "insufficient", "source_ids": [], "reason": "缺少依據"}
    instance, calls, _ = generator(tmp_path, json.dumps(selection, ensure_ascii=False))
    instance.generate("婚假幾天？", context)
    schema = json.loads(calls[0].content)["text"]["format"]["schema"]
    assert schema["properties"]["status"]["enum"] == [
        "answered",
        "insufficient",
        "conflict",
    ]
    assert schema["properties"]["source_ids"]["items"]["enum"] == ["s1"]
    # 正式選段schema維持原樣，不受本機候選影響。
    from hr_rag.verbatim import SourceSelection

    assert (
        "error" in SourceSelection.model_json_schema()["properties"]["status"]["enum"]
    )


def test_local_generator_rejects_other_model_response(tmp_path, context):
    selection = {"status": "answered", "source_ids": ["s1"], "reason": None}
    instance, _, _ = generator(tmp_path, json.dumps(selection), model="other:model")
    with pytest.raises(ProviderError, match="invalid_output"):
        instance.generate("婚假幾天？", context)


def test_local_generator_refuses_non_ollama_settings(tmp_path):
    from hr_rag.settings import OpenAISettings

    instance = local_generation.LocalVerbatimGenerator(
        OpenAISettings(cost_ledger_path=tmp_path / "c.sqlite3")
    )
    with pytest.raises(ProviderError, match="not_configured"):
        instance._configured()


def test_candidate_config_loads_and_model_can_be_overridden():
    config, loaded = local_generation.load_local_candidate()
    assert config["status"] == "candidate_not_selected"
    assert loaded.provider == "ollama" and loaded.model
    _, other = local_generation.load_local_candidate(model="gemma4:latest")
    assert other.model == "gemma4:latest"


def _context_with(*units):
    return ContextBundle(
        units=units,
        citation_map={unit.id: [unit.document_id] for unit in units},
        token_count=0,
        dropped_reasons=[],
        config_hash="h",
    )


def _unit(uid, doc, section):
    return Chunk(
        id=uid,
        document_id=doc,
        version_id="v1",
        section_id=section,
        parent_id="p-" + uid,
        text="合成正文",
        allowed_roles=["hr"],
        effective_from="2026-01-01",
    )


def _answer(status, citations):
    from hr_rag.contracts import Claim

    return Answer(
        status=status,
        claims=tuple(Claim(text="x", citation_ids=(cid,)) for cid in citations),
        citations=tuple(citations),
        reason=None if status == "answered" else "缺少依據",
    )


def test_score_requires_status_and_every_evidence_group():
    context = _context_with(_unit("a", "O01", "1"), _unit("b", "O02", "2"))
    expectation = {
        "expected_behavior": "answered",
        "required_evidence_groups": [
            [{"document_id": "O01", "version_id": "v1", "section_id": "1"}],
            [{"document_id": "O02", "version_id": "v1", "section_id": "2"}],
        ],
        "forbidden_sources": ["C04"],
    }
    full = local_generation.score(expectation, _answer("answered", ["a", "b"]), context)
    assert full["status_ok"] and full["evidence_ok"] and full["passed"]
    partial = local_generation.score(expectation, _answer("answered", ["a"]), context)
    assert partial["evidence_coverage"] == 0.5 and not partial["passed"]
    wrong = local_generation.score(
        expectation, _answer("insufficient", ["a", "b"]), context
    )
    assert not wrong["status_ok"] and not wrong["passed"]


def test_score_insufficient_and_forbidden_sources():
    context = _context_with(_unit("a", "C04", "x"))
    expectation = {
        "expected_behavior": "insufficient",
        "required_evidence_groups": [],
        "forbidden_sources": ["C04"],
    }
    clean = local_generation.score(
        expectation, _answer("insufficient", []), _context_with()
    )
    assert clean["passed"] and clean["evidence_coverage"] is None
    leaked = local_generation.score(
        expectation, _answer("insufficient", ["a"]), context
    )
    assert leaked["forbidden_cited"] == ["C04"] and not leaked["passed"]
    errored = local_generation.score(
        expectation,
        Answer(status="error", claims=(), citations=(), reason="逾時"),
        None,
    )
    assert not errored["passed"]


def test_web_uses_local_generator_only_when_requested(monkeypatch, tmp_path):
    from hr_rag import web

    built = []
    monkeypatch.setattr(
        local_generation, "local_generator", lambda **kw: built.append(kw) or "local"
    )

    class Service:
        def __init__(self, *, retriever=None, generator=None):
            self.generator = generator
            self.retriever = retriever

    monkeypatch.setattr("hr_rag.answering.AnswerService", Service)
    monkeypatch.setattr("hr_rag.retrieval.Retriever", lambda store: "retriever")
    monkeypatch.setenv("HR_RAG_GENERATION", "local")
    app = web.create_app(auth_store=object(), corpus_store=object())
    assert app.state.answer_service is None
    assert web_service(app).generator == "local" and len(built) == 1
    monkeypatch.delenv("HR_RAG_GENERATION")
    app = web.create_app(auth_store=object(), corpus_store=object())
    assert web_service(app).generator is None


def web_service(app):
    app.state.warmup()
    return app.state.answer_service


def test_cost_is_zero_but_ledger_still_records(tmp_path, context):
    selection = {"status": "answered", "source_ids": ["s1"], "reason": None}
    instance, _, _ = generator(tmp_path, json.dumps(selection))
    instance.generate("婚假幾天？", context)
    import sqlite3

    with sqlite3.connect(tmp_path / "ollama-cost.sqlite3") as db:
        rows = db.execute("SELECT amount, settled FROM costs").fetchall()
    assert [(Decimal(amount), settled) for amount, settled in rows] == [(0, 1)]
