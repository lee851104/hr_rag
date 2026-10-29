"""以真正 SDK 與 tiktoken 搭配隔離 HTTP 傳輸驗證；不使用真實金鑰。"""

import json
import logging
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import httpx2
import openai
import pytest
import tiktoken
from pydantic import ValidationError

from hr_rag import providers, settings
from hr_rag.audit import CostLedger
from hr_rag.contracts import Chunk, ContextBundle
from hr_rag.providers import CheckedProviders, ProviderError

SECRET = "offline-secret-never-a-real-key"
ANSWER = {
    "status": "answered",
    "claims": [{"text": "窗口為藍色櫃台。", "citation_ids": ["s1"]}],
    "reason": None,
}


@pytest.mark.parametrize("invent", [False, True])
def test_long_citation_ids_use_verified_short_transport_ids(tmp_path, context, invent):
    long_id = "p-" + "a" * 64
    unit = context.units[0].model_copy(update={"id": long_id})
    context = context.model_copy(
        update={"units": (unit,), "citation_map": {long_id: ("source",)}}
    )

    def handler(request):
        data = response()
        cid = long_id if invent else "e1"
        answer = {
            **ANSWER,
            "claims": [{"text": "窗口為藍色櫃台。", "citation_ids": [cid]}],
        }
        data["output"][0]["content"][0]["text"] = json.dumps(answer)
        return httpx2.Response(200, json=data)

    instance, calls, exchanges, _ = generator(tmp_path, handler=handler)
    if invent:
        with pytest.raises(ProviderError, match="invalid_output"):
            instance.generate("窗口？", context)
    else:
        answer = instance.generate("窗口？", context)
        assert answer.citations == (long_id,) and answer.claims[0].citation_ids == (
            long_id,
        )
        assert exchanges[0]["citation_alias_map"] == {"e1": long_id}
    body = json.loads(calls[0].content)
    assert json.loads(body["input"][0]["content"])["context"][0]["id"] == "e1"
    assert long_id not in json.dumps(body)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "1")
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(tmp_path / "events.jsonl"))

    def no_network(*args, **kwargs):
        pytest.fail("離線測試不可連網")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    # 真正 BPE 引擎，僅以256 byte詞表取代會下載的模型詞表。
    encoding = tiktoken.Encoding(
        name="offline-bytes",
        pat_str=r"[\s\S]",
        mergeable_ranks={bytes([n]): n for n in range(256)},
        special_tokens={},
    )
    monkeypatch.setattr(tiktoken, "encoding_for_model", lambda model: encoding)


@pytest.fixture
def context():
    return ContextBundle(
        units=[
            Chunk(
                id="s1",
                document_id="private-metadata",
                version_id="v1",
                section_id="1",
                parent_id="p1",
                text="窗口為藍色櫃台。",
                allowed_roles=["hr"],
                effective_from="2026-01-01",
            )
        ],
        citation_map={"s1": ["private-metadata/v1/1"]},
        token_count=0,
        dropped_reasons=["secret-dropped-metadata"],
        config_hash="private-config",
    )


def config(tmp_path, **kwargs):
    assert hasattr(settings, "OpenAISettings"), "缺少 OpenAISettings"
    values = dict(
        model="gpt-4.1-mini-2025-04-14",
        input_usd_per_million="1",
        output_usd_per_million="2",
        pricing_checked_on="2026-10-18",
        cost_ledger_path=tmp_path / "cost.sqlite3",
    )
    values.update(kwargs)
    return settings.OpenAISettings(**values)


def response(**updates):
    data = {
        "id": "resp_offline",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": "gpt-4.1-mini-2025-04-14",
        "store": False,
        "output": [
            {
                "type": "message",
                "id": "msg_offline",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "text": json.dumps(ANSWER, ensure_ascii=False),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 20},
        },
        "parallel_tool_calls": False,
        "tools": [],
        "tool_choice": "auto",
        "text": {"format": {"type": "text"}},
        "metadata": {},
    }
    data.update(updates)
    return data


def generator(tmp_path, handler=None, **kwargs):
    calls, exchanges, sleeps = [], [], []

    def respond(request):
        calls.append(request)
        return handler(request) if handler else httpx2.Response(200, json=response())

    client = openai.OpenAI(
        api_key=SECRET,
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
    )
    assert hasattr(providers, "OpenAIGenerator"), "缺少 OpenAIGenerator"
    instance = providers.OpenAIGenerator(
        config(tmp_path, **kwargs),
        client=client,
        on_exchange=exchanges.append,
        sleep=sleeps.append,
    )
    return instance, calls, exchanges, sleeps


def test_success_wire_schema_privacy_and_usage(tmp_path, context):
    instance, calls, exchanges, _ = generator(tmp_path)
    answer = instance.generate("窗口在哪裡？", context)
    assert answer.claims[0].citation_ids == ("s1",)
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://api.openai.com/v1/responses"
    assert body["store"] is False
    assert body["text"]["format"]["strict"] is True
    schema = body["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"status", "claims", "reason"}
    assert schema["$defs"]["Claim"]["additionalProperties"] is False
    assert body["temperature"] == 0
    assert body["max_output_tokens"] == instance.settings.output_reserve
    assert json.loads(body["input"][0]["content"]) == {
        "question": "窗口在哪裡？",
        "context": [{"id": "s1", "text": "窗口為藍色櫃台。"}],
    }
    wire = json.dumps(body)
    for forbidden in (
        "user_id",
        '"hr"',
        "private-metadata",
        "private-config",
        "secret-dropped-metadata",
        SECRET,
    ):
        assert forbidden not in wire
    event = exchanges[0]
    assert event["response_id"] == "resp_offline"
    assert event["model"] == "gpt-4.1-mini-2025-04-14"
    assert event["usage"]["output_tokens_details"]["reasoning_tokens"] == 20
    assert Decimal(str(event["cost"])) == Decimal("0.0002")
    assert event["response"]["output"][0]["content"][0]["text"]
    assert SECRET not in json.dumps(event)
    assert "藍色櫃台" not in (tmp_path / "events.jsonl").read_text("utf-8")
    assert CheckedProviders(generation=instance).generate("窗口？", context) == answer


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPENAI_API_KEY", ""),
        ("HR_RAG_COST_LIMIT_USD", ""),
        ("HR_RAG_COST_LIMIT_USD", "nan"),
        ("HR_RAG_COST_LIMIT_USD", "-1"),
    ],
)
def test_unconfigured_does_not_send(tmp_path, context, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    instance, calls, _, _ = generator(tmp_path)
    with pytest.raises(ProviderError, match="^not_configured$"):
        instance.generate("窗口？", context)
    assert calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",
        "https://evil.test/v1",
        "https://api.openai.com/v1/",
        "https://api.openai.com/v1?key=x",
        "https://api.openai.com.evil.test/v1",
        "https://user@api.openai.com/v1",
    ],
)
def test_endpoint_rejected(tmp_path, url):
    with pytest.raises(ValidationError):
        config(tmp_path, base_url=url)


@pytest.mark.parametrize(
    "status,code,count",
    [
        (429, "rate_limited", 3),
        (500, "unavailable", 3),
        (503, "unavailable", 3),
        (401, "not_configured", 1),
        (400, "unavailable", 1),
        (302, "unavailable", 1),
    ],
)
def test_bounded_retries_and_safe_errors(tmp_path, context, status, code, count):
    instance, calls, exchanges, sleeps = generator(
        tmp_path,
        lambda req: httpx2.Response(
            status,
            json={"error": {"message": SECRET}},
            headers={"Location": "https://evil.test"},
        ),
    )
    with pytest.raises(ProviderError, match=f"^{code}$") as caught:
        instance.generate("窗口？", context)
    assert len(calls) == count
    assert sleeps == ([1, 2] if count == 3 else [])
    assert SECRET not in str(caught.value)
    assert SECRET not in json.dumps(exchanges)
    assert SECRET not in (tmp_path / "events.jsonl").read_text("utf-8")


def test_timeout_no_blind_retry(tmp_path, context):
    def timeout(request):
        raise httpx2.ReadTimeout(SECRET)

    instance, calls, _, sleeps = generator(tmp_path, timeout)
    with pytest.raises(ProviderError, match="^timeout$"):
        instance.generate("窗口？", context)
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "text",
    [
        "not-json",
        "{}",
        json.dumps({**ANSWER, "extra": 1}),
        json.dumps({**ANSWER, "citations": []}),
    ],
)
def test_invalid_output_still_charged(tmp_path, context, text):
    data = response()
    data["output"][0]["content"][0]["text"] = text
    instance, _, exchanges, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(200, json=data),
    )
    with pytest.raises(ProviderError, match="^invalid_output$"):
        instance.generate("窗口？", context)
    assert Decimal(str(exchanges[0]["cost"])) == Decimal("0.0002")


@pytest.mark.parametrize(
    "updates",
    [
        {"status": "incomplete"},
        {"output": []},
        {"usage": None},
        {"model": "unexpected-model"},
    ],
)
def test_incomplete_or_unaccountable_response_rejected(tmp_path, context, updates):
    instance, _, _, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(200, json=response(**updates)),
    )
    with pytest.raises(ProviderError, match="^invalid_output$"):
        instance.generate("窗口？", context)


def test_real_token_count_overrules_untrusted_context_count(tmp_path, context):
    instance, calls, _, _ = generator(tmp_path, evidence_budget=10)
    with pytest.raises(ProviderError, match="^budget$"):
        instance.generate("窗口？", context)
    assert calls == []


def test_question_and_schema_count_toward_budget(tmp_path, context):
    instance, calls, _, _ = generator(tmp_path)
    with pytest.raises(ProviderError, match="^budget$"):
        instance.generate("甲" * 2000, context)
    assert calls == []


def test_cost_limit_zero_and_insufficient_reservation(tmp_path, context, monkeypatch):
    instance, calls, _, _ = generator(tmp_path)
    for value in ("0", "0.0000001"):
        monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", value)
        with pytest.raises(ProviderError, match="^cost_limit$"):
            instance.generate("窗口？", context)
    assert calls == []


def test_cost_accumulates_across_instances(tmp_path, context, monkeypatch):
    first, _, _, _ = generator(tmp_path)
    first.generate("窗口？", context)
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "0.0002")
    second, calls, _, _ = generator(tmp_path)
    with pytest.raises(ProviderError, match="^cost_limit$"):
        second.generate("窗口？", context)
    assert calls == []


def test_reasoning_configuration_omits_temperature(tmp_path, context):
    instance, calls, exchanges, _ = generator(
        tmp_path,
        supports_temperature=False,
        reasoning_effort="low",
    )
    instance.generate("窗口？", context)
    payload = json.loads(calls[0].content)
    assert "temperature" not in payload
    assert payload["reasoning"] == {"effort": "low"}
    assert exchanges[0]["temperature_applied"] is False


def test_audit_hook_failure_never_returns_success(tmp_path, context):
    instance, _, _, _ = generator(tmp_path)

    def fail(event):
        raise OSError(SECRET)

    instance.on_exchange = fail
    with pytest.raises(ProviderError, match="^audit_failure$"):
        instance.generate("窗口？", context)


def test_invalid_answer_creates_only_one_failure_event(tmp_path, context):
    instance, _, _, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(200, json=response(output=[])),
    )
    with pytest.raises(ProviderError):
        instance.generate("窗口？", context)
    rows = (tmp_path / "events.jsonl").read_text("utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["error_code"] == "invalid_output"


def test_sdk_debug_logs_never_expose_key_or_body(tmp_path, context, caplog):
    def respond(request):
        return httpx2.Response(
            429,
            json={"error": {"message": SECRET}},
            headers={"x-request-id": SECRET},
        )

    instance, _, _, _ = generator(tmp_path, respond)
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError):
        instance.generate("限閱問題", context)
    assert SECRET not in caplog.text
    assert "限閱問題" not in caplog.text
    assert "藍色櫃台" not in caplog.text


def test_unknown_usage_keeps_reservation_after_restart(tmp_path, context, monkeypatch):
    first, _, exchanges, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(200, json=response(usage=None)),
    )
    with pytest.raises(ProviderError, match="invalid_output"):
        first.generate("窗口？", context)
    assert exchanges[0]["cost"] is None
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "0.00512")
    second, calls, _, _ = generator(tmp_path)
    with pytest.raises(ProviderError, match="cost_limit"):
        second.generate("窗口？", context)
    assert not calls


def test_cost_reservations_are_atomic(tmp_path):
    path = tmp_path / "atomic.sqlite3"

    def reserve(_):
        return CostLedger(path).reserve(Decimal("0.6"), Decimal("1"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert sum(result is not None for result in results) == 1


def test_underestimated_input_increases_margin(tmp_path, context):
    _, estimate, _ = providers.build_openai_payload("窗口？", context, config(tmp_path))
    actual = estimate + max(200, estimate // 10)
    usage = {
        "input_tokens": actual,
        "output_tokens": 50,
        "total_tokens": actual + 50,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 20},
    }
    instance, _, exchanges, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(200, json=response(usage=usage)),
    )
    instance.generate("窗口？", context)
    assert exchanges[0]["input_token_delta"] > 0
    assert exchanges[0]["safety_margin"] > instance.settings.safety_margin


def test_audit_redacts_echoed_credentials(tmp_path, context):
    data = response()
    data["output"][0]["content"][0]["text"] = json.dumps(
        {**ANSWER, "reason": SECRET},
    )
    instance, _, exchanges, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(200, json=data),
    )
    instance.generate("窗口？", context)
    assert SECRET not in json.dumps(exchanges)
    assert SECRET not in (tmp_path / "events.jsonl").read_text("utf-8")


def test_retries_stop_if_uncertain_charges_exhaust_budget(
    tmp_path, context, monkeypatch
):
    monkeypatch.setenv("HR_RAG_COST_LIMIT_USD", "0.00512")
    instance, calls, _, _ = generator(
        tmp_path,
        lambda req: httpx2.Response(500, json={"error": {"message": SECRET}}),
    )
    with pytest.raises(ProviderError, match="cost_limit"):
        instance.generate("窗口？", context)
    assert len(calls) == 1


def test_cost_ledger_failure_blocks_request(tmp_path, context):
    instance, calls, _, _ = generator(tmp_path)
    instance.settings.cost_ledger_path.write_text("not-a-database", encoding="utf-8")
    with pytest.raises(ProviderError, match="audit_failure"):
        instance.generate("窗口？", context)
    assert not calls


def test_success_after_retry_has_one_settled_charge(tmp_path, context):
    attempts = []

    def respond(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx2.Response(429, json={"error": {"message": "limited"}})
        return httpx2.Response(200, json=response())

    instance, calls, _, sleeps = generator(tmp_path, respond)
    instance.generate("窗口？", context)
    assert len(calls) == 2
    assert sleeps == [1]
    with sqlite3.connect(instance.settings.cost_ledger_path) as db:
        amounts = db.execute("SELECT amount FROM costs").fetchall()
    assert sum(Decimal(row[0]) for row in amounts) == Decimal("0.0002")


def test_lazy_transport_logger_cannot_leak(tmp_path, context, caplog):
    def respond(request):
        # logger首次出現在provider呼叫內，涵蓋延遲載入的HTTP傳輸模組。
        from httpcore2._trace import Trace

        logger = logging.getLogger("httpcore2.http11." + uuid4().hex)
        Trace("receive_response_headers", logger).trace(
            "receive_response_headers.complete",
            {"return_value": [(b"x-request-id", SECRET.encode())]},
        )
        return httpx2.Response(200, json=response())

    instance, _, _, _ = generator(tmp_path, respond)
    with caplog.at_level(logging.DEBUG):
        instance.generate("窗口？", context)
    assert SECRET not in caplog.text


def test_token_difference_persisted_without_optional_hook(tmp_path, context):
    instance, _, _, _ = generator(tmp_path)
    instance.on_exchange = None
    instance.generate("窗口？", context)
    event = json.loads((tmp_path / "events.jsonl").read_text("utf-8"))
    assert type(event.get("input_token_delta")) is int
    assert event["input_token_delta"] < 0
    assert event.get("safety_margin") == 128


@pytest.mark.parametrize(
    "claims,expected",
    [
        ([], ()),
        (
            [
                {"text": "窗口為藍色櫃台。", "citation_ids": ["s1"]},
                {"text": "可到藍色櫃台辦理。", "citation_ids": ["s1"]},
            ],
            ("s1",),
        ),
    ],
)
def test_wire_claims_derive_exact_citation_union(tmp_path, context, claims, expected):
    def handler(request):
        raw = response()
        raw["output"][0]["content"][0]["text"] = json.dumps(
            {
                "status": "answered" if claims else "insufficient",
                "claims": claims,
                "reason": None if claims else "缺少必要資料。",
            }
        )
        return httpx2.Response(200, json=raw)

    instance, calls, _, _ = generator(tmp_path, handler=handler)
    answer = instance.generate("窗口在哪裡？", context)
    assert answer.citations == expected
    assert (
        "citations"
        not in json.loads(calls[0].content)["text"]["format"]["schema"]["properties"]
    )


def test_wire_rejects_legacy_unowned_citation_summary(tmp_path, context):
    def handler(request):
        raw = response()
        raw["output"][0]["content"][0]["text"] = json.dumps(
            {**ANSWER, "citations": ["s1"]}
        )
        return httpx2.Response(200, json=raw)

    instance, _, _, _ = generator(tmp_path, handler=handler)
    with pytest.raises(ProviderError, match="^invalid_output$"):
        instance.generate("窗口？", context)


def test_wire_unknown_claim_citation_still_rejected(tmp_path, context):
    def handler(request):
        raw = response()
        raw["output"][0]["content"][0]["text"] = json.dumps(
            {
                **ANSWER,
                "claims": [{"text": "未知來源的敘述。", "citation_ids": ["not-sent"]}],
            }
        )
        return httpx2.Response(200, json=raw)

    instance, _, _, _ = generator(tmp_path, handler=handler)
    with pytest.raises(ProviderError, match="^invalid_output$"):
        instance.generate("窗口？", context)


# ---- 串流量測：首字延遲 ----


def _sse(*events):
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        for event in events
    )


def _stream_handler(*, terminal=True):
    text = json.dumps(ANSWER, ensure_ascii=False)
    events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": response(status="in_progress", output=[], usage=None),
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "item_id": "msg_offline",
            "output_index": 0,
            "content_index": 0,
            "delta": text[:5],
            "logprobs": [],
        },
    ]
    if terminal:
        events.append(
            {"type": "response.completed", "sequence_number": 2, "response": response()}
        )

    def handler(request):
        return httpx2.Response(
            200,
            content=_sse(*events).encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )

    return handler


def test_default_generation_does_not_stream(tmp_path, context):
    instance, calls, exchanges, _ = generator(tmp_path)
    instance.generate("窗口在哪裡？", context)
    assert "stream" not in json.loads(calls[0].content)
    assert "ttft_ms" not in exchanges[0]


def test_stream_records_ttft_without_changing_payload(tmp_path, context):
    from hr_rag import audit

    instance, calls, exchanges, _ = generator(tmp_path, handler=_stream_handler())
    instance.stream = True
    collector = {"exchanges": [], "contexts": [], "notes": {}}
    token = audit._TRACE.set(("trace", collector))
    try:
        answer = instance.generate("窗口在哪裡？", context)
    finally:
        audit._TRACE.reset(token)
    assert answer.claims[0].citation_ids == ("s1",)
    assert json.loads(calls[0].content)["stream"] is True
    # 追溯保存的請求仍是未加stream的payload，重播雜湊不受量測方式影響。
    assert "stream" not in exchanges[0]["request"]
    assert exchanges[0]["usage"]["output_tokens"] == 50
    assert exchanges[0]["ttft_ms"] >= 0
    assert collector["notes"]["stage_ms"]["ttft"] == exchanges[0]["ttft_ms"]


def test_stream_without_terminal_event_is_unavailable(tmp_path, context):
    instance, _, _, _ = generator(tmp_path, handler=_stream_handler(terminal=False))
    instance.stream = True
    with pytest.raises(ProviderError, match="unavailable"):
        instance.generate("窗口在哪裡？", context)
