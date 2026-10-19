"""一般事件紀錄不得洩漏憑證或正文；受限追溯可重播、可清除。"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx2
import openai
import pytest
from test_openai_provider import response
from test_retrieval import engine

from hr_rag import audit
from hr_rag.answering import AnswerService
from hr_rag.audit import record_event
from hr_rag.context import ContextSettings
from hr_rag.contracts import Answer, Claim, ContextBundle, Principal, QueryRequest
from hr_rag.settings import OpenAISettings
from hr_rag.verbatim import VerbatimGenerator

EMPLOYEE = Principal(user_id="private-account", role="employee")


def test_event_contains_only_safe_metadata(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(path))
    trace_id = record_event(
        {
            "stage": "embed",
            "status": "ok",
            "duration_ms": 12.5,
            "password": "secret-password",
            "api_key": "secret-key",
            "question": "限閱正文",
            "metadata": {"token": "nested-secret"},
        }
    )
    UUID(trace_id)
    text = path.read_text(encoding="utf-8")
    assert not any(s in text for s in ["secret", "限閱正文", "password", "api_key"])
    row = json.loads(text)
    assert row["trace_id"] == trace_id
    assert row["stage"] == "embed"
    assert row["duration_ms"] == 12.5
    assert row["cost"] is None


def test_arbitrary_text_in_allowed_fields_cannot_leak(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(path))
    record_event(
        {
            "stage": "secret-key",
            "status": "secret-key",
            "error_code": "secret-key",
            "duration_ms": "secret-key",
        }
    )
    assert "secret-key" not in path.read_text(encoding="utf-8")


# ---- 階段6：查詢事件、受限追溯、重播與清除 ----


def test_query_fields_are_whitelisted(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(path))
    record_event(
        {
            "stage": "query",
            "status": "ok",
            "role": "我是HR",
            "mode": "限閱正文",
            "as_of": "限閱正文",
            "candidate_ids": ["ok-id", "含 空白 正文"],
            "stage_ms": {"retrieve": 1, "question": "限閱正文"},
            "snapshot": {"generation_id": "限閱正文"},
            "user_ref": "private-account",
        }
    )
    row = json.loads(path.read_text("utf-8"))
    assert row["role"] is None and row["mode"] is None and row["as_of"] is None
    assert row["candidate_ids"] is None and row["user_ref"] is None
    assert row["stage_ms"] == {"retrieve": 1}
    assert row["snapshot"] is None
    assert "限閱正文" not in path.read_text("utf-8")


def _context():
    return ContextBundle(
        units=(), citation_map={}, token_count=0, dropped_reasons=(), config_hash="h"
    )


class FakeService:
    """模擬AnswerService：在追溯範圍內回報交換、上下文與階段資訊。"""

    def __init__(self, *, exchange=None):
        self.generator = SimpleNamespace(
            SYSTEM="系統提示",
            settings=SimpleNamespace(
                model="gpt-4.1-2025-04-14",
                model_dump=lambda **_: {"model": "gpt-4.1-2025-04-14"},
            ),
        )
        self.exchange = exchange

    def answer(self, request, principal):
        audit.note(
            as_of="2026-10-18",
            mode="rerank",
            snapshot={"generation_id": "synthetic", "manifest_sha256": "test"},
            candidate_ids=["id-1", "id-2"],
            evidence_ids=["parent-1"],
            stage_ms={"retrieve": 3.0, "assemble": 1.0, "generate": 5.0},
        )
        audit.collect_context(_context())
        if self.exchange is not None:
            audit.collect_exchange(self.exchange)
            record_event(
                {"stage": "generate", "status": "ok", "model": "gpt-4.1-2025-04-14"}
            )
        return Answer(
            status="answered",
            claims=(Claim(text="【原文】合成正文", citation_ids=("parent-1",)),),
            citations=("parent-1",),
            reason=None,
        )


def _exchange(**extra):
    return {
        "request": {
            "model": "gpt-4.1-2025-04-14",
            "instructions": "系統提示",
            "input": [{"role": "user", "content": '{"question":"問","context":[]}'}],
        },
        "response": {"id": "resp_1", "output_text": '{"status":"answered"}'},
        "response_id": "resp_1",
        "model": "gpt-4.1-2025-04-14",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "cost": 0.000036,
        **extra,
    }


@pytest.fixture
def traces(tmp_path, monkeypatch):
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(tmp_path / "events.jsonl"))
    return audit.TraceStore(tmp_path / "private" / "traces.sqlite3")


def _events(tmp_path):
    path = tmp_path / "events.jsonl"
    return [json.loads(x) for x in path.read_text("utf-8").splitlines()]


def _ask(traces, service=None, question="問"):
    return audit.traced_answer(
        service or FakeService(exchange=_exchange()),
        QueryRequest(question=question, as_of=None),
        EMPLOYEE,
        traces=traces,
    )


def test_query_trace_is_restricted_and_event_has_only_ids(traces, tmp_path):
    trace_id, answer = _ask(traces, question="限閱問題正文")
    UUID(trace_id)
    assert answer.status == "answered"
    saved = traces.load(trace_id)
    assert saved["question"] == "限閱問題正文"
    assert saved["exchanges"][0]["request"]["instructions"] == "系統提示"
    assert saved["exchanges"][0]["response"]["output_text"]
    assert saved["answer"]["claims"][0]["citation_ids"] == ["parent-1"]
    assert saved["claim_citations"] == [
        {"claim_index": 0, "citation_ids": ["parent-1"]}
    ]
    assert saved["input_sha256"] == audit.input_hash(saved["exchanges"])
    assert saved["user_ref"] != "private-account"
    events = _events(tmp_path)
    query = [e for e in events if e["stage"] == "query"][0]
    generate = [e for e in events if e["stage"] == "generate"][0]
    assert query["trace_id"] == trace_id and generate["query_id"] == trace_id
    assert query["role"] == "employee" and query["mode"] == "rerank"
    assert query["candidate_ids"] == ["id-1", "id-2"]
    assert query["evidence_ids"] == ["parent-1"]
    assert query["snapshot"] == {
        "generation_id": "synthetic",
        "manifest_sha256": "test",
    }
    assert query["model"] == "gpt-4.1-2025-04-14"
    assert len(query["prompt_sha256"]) == 64 and len(query["user_ref"]) == 64
    assert query["response_ids"] == ["resp_1"]
    assert query["usage"]["input_tokens"] == 10 and query["cost"] == 0.000036
    assert set(query["stage_ms"]) >= {"retrieve", "assemble", "generate", "total"}
    assert query["answer_status"] == "answered"
    text = (tmp_path / "events.jsonl").read_text("utf-8")
    assert "限閱問題正文" not in text and "合成正文" not in text
    assert "private-account" not in text and "系統提示" not in text


def test_unknown_cost_and_usage_are_null_not_zero(traces, tmp_path):
    _ask(traces, FakeService(exchange=_exchange(cost=None, usage=None)))
    _ask(traces, FakeService())
    first, second = [e for e in _events(tmp_path) if e["stage"] == "query"]
    assert first["cost"] is None and first["usage"] is None
    # 沒有模型呼叫時也不是0元。
    assert second["cost"] is None and second["response_ids"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"headers": {"Authorization": "Bearer sk-secretvalue123456"}},
        {"note": "sk-proj-abcdefghijklmnop"},
        {"password": "synthetic-password-employee"},
    ],
)
def test_credentials_are_never_saved(traces, tmp_path, extra):
    trace_id, answer = _ask(traces, FakeService(exchange=_exchange(**extra)))
    stored = traces.path.read_bytes()
    assert b"sk-" not in stored and b"synthetic-password" not in stored
    assert b"Authorization" not in stored
    events = (tmp_path / "events.jsonl").read_text("utf-8")
    assert "sk-" not in events and "synthetic-password" not in events
    if answer.status != "error":
        assert "headers" not in json.dumps(traces.load(trace_id))


def test_audit_write_failure_never_returns_untraced_success(traces, monkeypatch):
    def broken(_trace):
        raise OSError("disk full")

    monkeypatch.setattr(traces, "save", broken)
    _, answer = _ask(traces)
    assert answer.status == "error" and not answer.claims
    assert "稽核" in answer.reason


def test_replay_after_source_update_uses_saved_input(traces):
    trace_id, _ = _ask(traces)
    # 重播只讀已保存且hash相符的交換，沒有生成器可呼叫。
    replay = audit.replay(trace_id, traces=traces)
    assert replay["input_sha256_verified"] is True
    assert replay["model_called"] is False
    assert replay["exchanges"][0]["request"]["input"][0]["content"].startswith("{")
    with traces.connect() as db:
        db.execute(
            "UPDATE traces SET content=replace(content,'系統提示','竄改') "
            "WHERE trace_id=?",
            (trace_id,),
        )
    with pytest.raises(ValueError, match="trace_tampered"):
        audit.replay(trace_id, traces=traces)


def test_purge_default_retention_and_explicit_before(traces):
    old, _ = _ask(traces, FakeService(), "舊")
    new, _ = _ask(traces, FakeService(), "新")
    with traces.connect() as db:
        db.execute(
            "UPDATE traces SET created_at=created_at-31*86400,"
            "expires_at=expires_at-31*86400 WHERE trace_id=?",
            (old,),
        )
    assert traces.purge_expired() == 1
    assert traces.get(old) is None and traces.get(new) is not None
    later = datetime.now(timezone.utc) + timedelta(days=1)
    assert traces.purge(before=later) == 1
    assert traces.get(new) is None


def test_trace_retention_is_thirty_days(traces):
    trace_id, _ = _ask(traces, FakeService())
    saved = traces.load(trace_id)
    assert saved["expires_at"] - saved["created_at"] == 30 * 86400


def test_audit_cli_replay_and_purge(traces):
    trace_id, _ = _ask(traces)
    env = {**os.environ, "HR_RAG_TRACE_PATH": str(traces.path)}
    run = dict(capture_output=True, text=True, encoding="utf-8", env=env, check=True)
    shown = subprocess.run(
        [sys.executable, "-m", "hr_rag.audit", "replay", "--trace-id", trace_id], **run
    )
    assert json.loads(shown.stdout)["input_sha256_verified"] is True
    purged = subprocess.run(
        [sys.executable, "-m", "hr_rag.audit", "purge", "--before", "2999-01-01"],
        **run,
    )
    assert json.loads(purged.stdout) == {"purged": 1}


def test_end_to_end_replay_survives_source_update(answer_store, monkeypatch, tmp_path):
    """真SDK＋假HTTP：保存的是實際送出的請求；來源改版後重播仍為當時輸入。"""
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-offline-key")
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "1")
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        data = response()
        data["output"][0]["content"][0]["text"] = json.dumps(
            {"status": "answered", "source_ids": ["parent-1"], "reason": None}
        )
        return httpx2.Response(200, json=data)

    client = openai.OpenAI(
        api_key="synthetic-offline-key",
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
    )
    generator = VerbatimGenerator(
        OpenAISettings(cost_ledger_path=tmp_path / "cost.sqlite3"),
        client=client,
        on_exchange=audit.collect_exchange,
    )
    service = AnswerService(
        retriever=engine(answer_store),
        generator=generator,
        config=ContextSettings(mode="rerank", context_max_units=5, min_relevance=0),
    )
    traces = audit.TraceStore(tmp_path / "private" / "traces.sqlite3")
    trace_id, answer = audit.traced_answer(
        service,
        QueryRequest(question="公司請假流程？", as_of="2026-10-18"),
        Principal(user_id="unique-private-user", role="employee"),
        traces=traces,
    )
    assert answer.status == "answered" and len(sent) == 1
    saved = traces.load(trace_id)
    request = saved["exchanges"][0]["request"]
    assert request["instructions"] == sent[0]["instructions"]
    assert request["input"] == sent[0]["input"]
    assert "合成限閱正文-C01" in json.dumps(request, ensure_ascii=False)
    assert saved["exchanges"][0]["response"]["id"] == "resp_offline"
    assert saved["context"]["units"][0]["id"] == "parent-1"
    with answer_store.connect() as db:
        row = json.loads(
            db.execute("SELECT chunk_json FROM units WHERE id='parent-1'").fetchone()[0]
        )
        row["text"] = "來源已改版的新正文"
        db.execute(
            "UPDATE units SET chunk_json=? WHERE id='parent-1'", (json.dumps(row),)
        )
    replayed = audit.replay(trace_id, traces=traces)
    text = json.dumps(replayed["exchanges"], ensure_ascii=False)
    assert replayed["input_sha256_verified"] and "合成限閱正文-C01" in text
    assert "來源已改版" not in text and len(sent) == 1
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text("utf-8").splitlines()
    ]
    query = [e for e in events if e["stage"] == "query"][0]
    assert query["response_ids"] == ["resp_offline"]
    assert query["usage"]["output_tokens_details"]["reasoning_tokens"] == 20
    assert query["cost"] is not None and query["model"] == "gpt-4.1-mini-2025-04-14"
    assert "unique-private-user" not in json.dumps(events)
