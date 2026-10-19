"""模型是慢速外部依賴；替身只替代推論，檢核仍使用真正provider。"""

import json

import httpx
import numpy as np
import pytest

from hr_rag.contracts import Chunk, ContextBundle
from hr_rag.providers import CheckedProviders, LlamaGenerator, ProviderError
from hr_rag.settings import RuntimeSettings


@pytest.fixture
def context():
    unit = Chunk(
        id="s1",
        document_id="fixture",
        version_id="v1",
        section_id="1",
        parent_id="s1",
        text="測試窗口為藍色櫃台。",
        allowed_roles=["employee"],
        effective_from="2026-01-01",
    )
    return ContextBundle(
        units=[unit],
        citation_map={"s1": ["fixture/v1/1"]},
        token_count=12,
        dropped_reasons=[],
        config_hash="fixture",
    )


def valid_answer():
    return json.dumps(
        {
            "status": "answered",
            "claims": [{"text": "窗口為藍色櫃台。", "citation_ids": ["s1"]}],
            "citations": ["s1"],
            "reason": None,
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    "output", [np.array([[1.0]]), np.array([[np.nan], [1.0]]), np.array([1.0, 2.0])]
)
def test_invalid_embedding_shape_or_nan_rejected(output):
    provider = CheckedProviders(embedding=lambda texts: output)
    with pytest.raises(ProviderError, match="invalid_output"):
        provider.embed(["甲", "乙"])


@pytest.mark.parametrize("output", [[0.3], [0.3, float("nan")]])
def test_invalid_reranking_output_rejected(output):
    provider = CheckedProviders(ranking=lambda q, texts: output)
    with pytest.raises(ProviderError, match="invalid_output"):
        provider.rerank("窗口", ["藍色", "紅色"])


def test_valid_numeric_results_preserve_order():
    provider = CheckedProviders(
        embedding=lambda texts: np.array([[1.0, 0.0], [0.0, 1.0]]),
        ranking=lambda q, texts: [0.9, -0.1],
    )
    np.testing.assert_array_equal(provider.embed(["甲", "乙"]), [[1, 0], [0, 1]])
    assert provider.rerank("窗口", ["藍色", "紅色"]) == [0.9, -0.1]


@pytest.mark.parametrize("output", ["not-json", "{}", '{"status":"success"}'])
def test_invalid_generated_json_is_controlled(context, output):
    provider = CheckedProviders(generation=lambda q, c: output)
    with pytest.raises(ProviderError, match="invalid_output"):
        provider.generate("窗口在哪裡？", context)


def test_generation_timeout_is_controlled_without_exception_text(context):
    def timeout(q, c):
        raise TimeoutError("secret-key")

    with pytest.raises(ProviderError, match="^timeout$") as caught:
        CheckedProviders(generation=timeout).generate("窗口？", context)
    assert "secret-key" not in str(caught.value)


def test_real_http_adapter_payload_and_exchange(context):
    exchanges = []

    def respond(request):
        body = json.loads(request.content)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(40))})
        assert request.url.path == "/completion"
        assert "藍色櫃台" in body["prompt"]
        assert body["n_predict"] == 512
        return httpx.Response(
            200,
            json={
                "content": valid_answer(),
                "stop_type": "eos",
                "tokens_predicted": 50,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    generator = LlamaGenerator(
        RuntimeSettings(), client=client, on_exchange=exchanges.append
    )
    answer = CheckedProviders(generation=generator).generate("窗口？", context)
    assert answer.claims[0].citation_ids == ("s1",)
    assert exchanges[0]["response"]["content"] == valid_answer()
    assert "窗口？" in exchanges[0]["request"]["prompt"]


def test_http_timeout_and_token_overflow_never_generate(context):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"tokens": list(range(4096))})

    generator = LlamaGenerator(
        RuntimeSettings(), client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    with pytest.raises(ProviderError, match="budget"):
        CheckedProviders(generation=generator).generate("窗口？", context)
    assert "/completion" not in calls

    def timeout(request):
        raise httpx.ReadTimeout("secret")

    generator = LlamaGenerator(
        RuntimeSettings(), client=httpx.Client(transport=httpx.MockTransport(timeout))
    )
    with pytest.raises(ProviderError, match="^timeout$"):
        CheckedProviders(generation=generator).generate("窗口？", context)


def test_truncated_generation_is_not_accepted(context):
    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1]})
        return httpx.Response(
            200, json={"content": valid_answer(), "stop_type": "limit"}
        )

    generator = LlamaGenerator(
        RuntimeSettings(), client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    with pytest.raises(ProviderError, match="invalid_output"):
        CheckedProviders(generation=generator).generate("窗口？", context)
