from datetime import date

import pytest

from hr_rag.context import ContextSettings, assemble_context
from hr_rag.contracts import Evidence, Principal
from hr_rag.policy import eligible_chunks
from hr_rag.providers import ProviderError
from hr_rag.settings import OpenAISettings

DAY = date(2026, 10, 1)
HR = Principal(user_id="hr", role="hr")


def evidence(store):
    return [
        Evidence(chunk=c, score=score)
        for c, score in zip(
            eligible_chunks(HR, DAY, store=store), [1, 0.8, 0.2], strict=True
        )
    ]


def test_same_parent_dedup_relevance_and_citation_whitelist(policy_store):
    items = evidence(policy_store)
    result = assemble_context(
        [items[0], items[0], *items[1:]],
        HR,
        DAY,
        "合成問題",
        store=policy_store,
        config=ContextSettings(context_max_units=5, min_relevance=0.5),
    )
    assert [u.id for u in result.units] == ["parent-1", "parent-2"]
    assert set(result.citation_map) == {"parent-1", "parent-2"}
    assert any("relevance" in r for r in result.dropped_reasons)


def test_parent_withdrawal_rechecks_and_budget_removes_whole_units(policy_store):
    items = evidence(policy_store)
    policy_store.withdraw("C04", "v3")
    result = assemble_context(
        items,
        HR,
        DAY,
        "合成問題",
        store=policy_store,
        config=ContextSettings(context_max_units=5, min_relevance=0),
        settings=OpenAISettings(evidence_budget=10),
    )
    assert result.units == () and result.citation_map == {}
    assert any("budget" in r for r in result.dropped_reasons)
    assert any("unauthorized" in r for r in result.dropped_reasons)


def test_prompt_itself_over_budget_is_controlled(policy_store):
    with pytest.raises(ProviderError, match="budget"):
        assemble_context([], HR, DAY, "甲" * 10000, store=policy_store)


def test_filter_keeps_first_but_never_unauthorized(policy_store):
    result = assemble_context(
        evidence(policy_store),
        HR,
        DAY,
        "合成",
        store=policy_store,
        config=ContextSettings(mode="rerank", context_max_units=1, min_relevance=100),
    )
    assert len(result.units) == 1
    assert result.units[0].id == "parent-1"


def test_identical_text_different_source_scope_never_overwrites(policy_store):
    import json

    with policy_store.connect() as db:
        for chunk_id in ["parent-1", "parent-2"]:
            data = json.loads(
                db.execute(
                    "SELECT chunk_json FROM units WHERE id=?", (chunk_id,)
                ).fetchone()[0]
            )
            data["text"] = "相同正文但來源與適用對象不同，不可互相覆蓋。"
            db.execute(
                "UPDATE units SET chunk_json=? WHERE id=?", (json.dumps(data), chunk_id)
            )
    result = assemble_context(
        evidence(policy_store),
        HR,
        DAY,
        "合成",
        store=policy_store,
        config=ContextSettings(context_max_units=5, min_relevance=0),
    )
    assert {"parent-1", "parent-2"} <= set(result.citation_map)


def test_forged_evidence_text_never_reaches_prompt(policy_store):
    item = evidence(policy_store)[0]
    forged = item.model_copy(
        update={"chunk": item.chunk.model_copy(update={"text": "偽造內容"})}
    )
    result = assemble_context([forged], HR, DAY, "合成", store=policy_store)
    assert all("偽造內容" not in unit.text for unit in result.units)


@pytest.mark.parametrize(
    "question,text",
    [
        ("產檢假有幾天？", "女性受僱者每月得請生理假一日，其餘併入病假。"),
        ("婚假如何給薪？", "勞工得請家庭照顧假，其日數併入事假計算。"),
    ],
)
def test_explicit_different_leave_grant_is_noise(question, text):
    from hr_rag.context import leave_scope_mismatch

    assert leave_scope_mismatch(question, text)


@pytest.mark.parametrize(
    "question,text",
    [
        ("產檢假有幾天？", "雇主應給予產檢假七日，另給予產假。"),
        ("生理假與病假如何計算？", "雇主應給予產檢假。"),
        ("不是產檢假，是生理假？", "雇主應給予產檢假。"),
        ("請假怎麼申請？", "勞工得請事假。"),
        ("產檢假可以扣全勤嗎？", "勞工請婚假不得影響全勤獎金。"),
        ("產檢假怎麼申請？", "勞工得請事假；其他法律另有規定者從其規定。"),
        ("病假安胎怎麼處理？", "雇主給予產假；安胎休養依相關法令之規定。"),
        ("補休怎麼申請？", "特別休假由勞工排定；補休另依規定。"),
        (
            "產檢假要提前申請嗎？",
            "勞工得請事假。請假應事前向主管提出，緊急事故得委託他人辦理。",
        ),
        ("產檢假要提前申請嗎？", "勞工得請事假，請假應事前向主管提出。"),
        ("病假安胎怎麼處理？", "雇主給予產假；安胎休養依照其他法令辦理。"),
        ("病假安胎怎麼處理？", "雇主給予產假；安胎休養依據相關法律辦理。"),
        ("不請婚假還能請哪種假？", "有事故須親自處理者得請事假。"),
        ("無法請婚假時怎麼辦？", "有事故須親自處理者得請事假。"),
        ("產檢假有幾天？", "勞工得請事假。其他權利仍受保障。"),
    ],
)
def test_ambiguous_general_or_related_scope_is_preserved(question, text):
    from hr_rag.context import leave_scope_mismatch

    assert not leave_scope_mismatch(question, text)


def test_leave_scope_filter_keeps_first_and_drops_whole_later_unit(policy_store):
    import json

    with policy_store.connect() as db:
        for cid in ["parent-1", "parent-2"]:
            data = json.loads(
                db.execute(
                    "SELECT chunk_json FROM units WHERE id=?", (cid,)
                ).fetchone()[0]
            )
            data["text"] = "勞工得請生理假一日。"
            db.execute(
                "UPDATE units SET chunk_json=? WHERE id=?", (json.dumps(data), cid)
            )
    result = assemble_context(
        evidence(policy_store),
        HR,
        DAY,
        "產檢假幾日？",
        store=policy_store,
        config=ContextSettings(
            context_max_units=5, min_relevance=0, leave_scope_filter=True
        ),
    )
    assert result.units[0].id == "parent-1"
    assert "parent-2" not in result.citation_map
    assert "parent-2:leave_scope_mismatch" in result.dropped_reasons


def test_context_uses_actual_provider_budget(policy_store):
    calls = []

    def builder(question, context):
        calls.append(len(context.units))
        if len(context.units) > 1:
            raise ProviderError("budget")
        return (
            {"instructions": "candidate", "text": {"format": {"schema": {}}}},
            123,
            45,
        )

    result = assemble_context(
        evidence(policy_store),
        HR,
        DAY,
        "合成問題",
        store=policy_store,
        config=ContextSettings(min_relevance=0),
        payload_builder=builder,
    )
    assert len(result.units) == 1 and result.token_count == 123
    assert calls[0] == 0 and any(n > 1 for n in calls)
    assert any("whole_unit_over_budget" in reason for reason in result.dropped_reasons)
