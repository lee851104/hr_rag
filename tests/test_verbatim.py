"""原文候選以假API檢核完整來源及嚴格選取。"""

# ruff: noqa: F811
import json

import httpx2
import pytest
from test_openai_provider import context, generator, isolated, response  # noqa: F401

from hr_rag.providers import ProviderError
from hr_rag.verbatim import VerbatimGenerator


def make(tmp_path, output):
    def handler(request):
        raw = response()
        raw["output"][0]["content"][0]["text"] = json.dumps(output, ensure_ascii=False)
        return httpx2.Response(200, json=raw)

    base, calls, exchanges, _ = generator(tmp_path, handler)
    return (
        VerbatimGenerator(
            base.settings, client=base.client, on_exchange=exchanges.append
        ),
        calls,
        exchanges,
    )


def test_verbatim_preserves_whole_authorized_text(tmp_path, context):
    original = "申請請依原紀錄辦理。\n緊急時先通知；不得因此否定權利。"
    context = context.model_copy(
        update={"units": (context.units[0].model_copy(update={"text": original}),)}
    )
    instance, calls, _ = make(
        tmp_path, dict(status="answered", source_ids=["s1"], reason=None)
    )
    answer = instance.generate("申請怎麼辦？", context)
    assert answer.claims[0].text == "【原文】" + original
    assert answer.citations == answer.claims[0].citation_ids == ("s1",)
    wire = json.loads(calls[0].content)
    assert set(wire["text"]["format"]["schema"]["required"]) == {
        "status",
        "source_ids",
        "reason",
    }
    assert "claims" not in wire["text"]["format"]["schema"]["properties"]


@pytest.mark.parametrize(
    "output",
    [
        dict(status="answered", source_ids=["not-sent"], reason=None),
        dict(status="answered", source_ids=["s1", "s1"], reason=None),
        dict(status="answered", source_ids=[], reason=None),
        dict(status="answered", source_ids=["s1"], reason=None, text="模型改寫"),
    ],
)
def test_verbatim_rejects_invalid_selection_and_keeps_usage(tmp_path, context, output):
    instance, _, exchanges = make(tmp_path, output)
    with pytest.raises(ProviderError, match="^invalid_output$"):
        instance.generate("申請怎麼辦？", context)
    assert len(exchanges) == 1 and exchanges[0]["cost"] > 0


def test_verbatim_insufficient_has_no_invented_text(tmp_path, context):
    instance, _, _ = make(
        tmp_path, dict(status="insufficient", source_ids=[], reason="缺少資料。")
    )
    answer = instance.generate("未知流程？", context)
    assert (
        answer.status == "insufficient"
        and answer.claims == ()
        and answer.citations == ()
    )


def test_verbatim_source_identity_is_minimal_and_authorized(tmp_path, context):
    instance, calls, _ = make(
        tmp_path, dict(status="answered", source_ids=["s1"], reason=None)
    )
    instance.generate("窗口？", context)
    source = json.loads(calls[0].content)["input"][0]["content"]
    unit = json.loads(source)["context"][0]
    original = context.units[0]
    assert unit["source"] == [
        original.document_id,
        original.version_id,
        original.section_id,
    ]
    assert set(unit) == {"id", "text", "source"}
    for forbidden in (
        "allowed_roles",
        "user_id",
        "parent_id",
        "effective_from",
        "private-config",
    ):
        assert forbidden not in source


def test_verbatim_expands_explicit_document_and_rule_references(tmp_path, context):
    first = context.units[0].model_copy(
        update={
            "id": "a",
            "document_id": "X44",
            "text": "研究假薪資依各該訓練假規定辦理。表單請查Y55。",
        }
    )
    wage = first.model_copy(
        update={
            "id": "b",
            "document_id": "Z66",
            "text": "勞工得請訓練假，期間工資照給。",
        }
    )
    form = first.model_copy(
        update={"id": "c", "document_id": "Y55", "text": "申請附紙本表單交指定窗口。"}
    )
    unrelated = first.model_copy(
        update={
            "id": "d",
            "document_id": "Y550",
            "text": "其他背景。紀錄中提及訓練假。",
        }
    )
    context = context.model_copy(
        update={
            "units": (first, wage, form, unrelated),
            "citation_map": {u.id: (u.id,) for u in (first, wage, form, unrelated)},
        }
    )
    instance, _, _ = make(
        tmp_path, dict(status="answered", source_ids=["a"], reason=None)
    )
    answer = instance.generate("研究假薪資與表單？", context)
    assert answer.citations == ("a", "b", "c")
    assert answer.claims[1].text == "【參照補充】【原文】" + wage.text
    assert answer.claims[2].text == "【參照補充】【原文】" + form.text


def test_verbatim_does_not_resolve_missing_reference_outside_context(tmp_path, context):
    unit = context.units[0].model_copy(update={"text": "依各該訓練假規定辦理，查Y55。"})
    context = context.model_copy(update={"units": (unit,)})
    instance, _, _ = make(
        tmp_path,
        dict(status="insufficient", source_ids=["s1"], reason="缺少具體依據。"),
    )
    answer = instance.generate("訓練假薪資？", context)
    assert answer.citations == ("s1",)
    assert answer.status == "insufficient"


def test_verbatim_reference_cycles_are_bounded_and_negative_refs_ignored(
    tmp_path, context
):
    first = context.units[0].model_copy(
        update={
            "id": "a",
            "document_id": "X44",
            "text": "請查Y55。不依訓練假規定辦理。",
        }
    )
    second = first.model_copy(
        update={"id": "b", "document_id": "Y55", "text": "參閱X44。不需查Z66。"}
    )
    third = first.model_copy(
        update={"id": "c", "document_id": "Z66", "text": "勞工得請訓練假。"}
    )
    context = context.model_copy(
        update={
            "units": (first, second, third),
            "citation_map": {u.id: (u.id,) for u in (first, second, third)},
        }
    )
    instance, _, _ = make(
        tmp_path, dict(status="answered", source_ids=["a"], reason=None)
    )
    answer = instance.generate("流程？", context)
    assert answer.citations == ("a", "b")


@pytest.mark.parametrize(
    "text", ["請依規定辦理，不需查Z66。", "請參閱Y55，不得參照Z66。", "不須查Z66。"]
)
def test_verbatim_negation_scope_never_includes_explicitly_excluded_doc(
    tmp_path, context, text
):
    first = context.units[0].model_copy(
        update={"id": "a", "document_id": "X44", "text": text}
    )
    excluded = first.model_copy(
        update={"id": "b", "document_id": "Z66", "text": "不應補入的來源。"}
    )
    context = context.model_copy(
        update={"units": (first, excluded), "citation_map": {"a": ("a",), "b": ("b",)}}
    )
    instance, _, _ = make(
        tmp_path, dict(status="answered", source_ids=["a"], reason=None)
    )
    assert instance.generate("流程？", context).citations == ("a",)


def test_verbatim_wire_constrains_ids_not_document_names(tmp_path, context):
    instance, calls, _ = make(
        tmp_path, dict(status="answered", source_ids=["s1"], reason=None)
    )
    instance.generate("窗口？", context)
    wire = json.loads(calls[0].content)
    assert wire["text"]["format"]["schema"]["properties"]["source_ids"]["items"][
        "enum"
    ] == ["s1"]
