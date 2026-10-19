"""合成上下文與假生成器；不讀憑證、不呼叫API。"""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from hr_rag.answering import AnswerService, contains_simplified, validate_citations
from hr_rag.citations import citation_details
from hr_rag.context import ContextSettings
from hr_rag.contracts import Answer, Claim, ContextBundle, Evidence, Principal
from hr_rag.policy import eligible_chunks
from hr_rag.providers import ProviderError

DAY = date(2026, 10, 18)
HR = Principal(user_id="private-account", role="hr")


def test_default_generator_uses_frozen_settings_without_reading_key(policy_store):
    runner = AnswerService(
        retriever=SimpleNamespace(store=policy_store), config=ContextSettings()
    )
    # 2026-10-19人工驗收後改採原文候選；mini摘要設定保留於歷史鎖定。
    assert runner.generator.settings.model == "gpt-4.1-2025-04-14"
    assert runner.generator.SYSTEM.startswith("你是證據選取器")


def result(text="有證據的主張。", ids=("parent-1",), status="answered", reason=None):
    return Answer(
        status=status,
        claims=(Claim(text=text, citation_ids=ids),),
        citations=ids,
        reason=reason,
    )


def service(store, generated=None, *, hook=None):
    calls = []

    def generate(question, context):
        calls.append(context)
        if hook:
            hook()
        if isinstance(generated, Exception):
            raise generated
        return generated or result()

    retriever = SimpleNamespace(
        store=store,
        retrieve=lambda q, p, d, *a, **k: [
            Evidence(chunk=c, score=1) for c in eligible_chunks(p, d, store=store)
        ],
    )
    return AnswerService(
        retriever=retriever,
        generator=SimpleNamespace(generate=generate),
        config=ContextSettings(context_max_units=5, min_relevance=0),
    ), calls


def ask(runner, question="合成問題"):
    return runner.answer({"question": question, "as_of": DAY.isoformat()}, HR)


def test_unknown_citation_rejected(answer_store):
    runner, _ = service(answer_store, result(ids=("never-sent",)))
    got = ask(runner)
    assert got.status == "error" and not got.claims and not got.citations
    assert "never-sent" not in got.model_dump_json()


def test_original_child_is_not_a_sent_parent_citation(answer_store):
    runner, _ = service(answer_store, result(ids=("id-1",)))
    assert ask(runner).status == "error"


def test_source_labels_and_citation_metadata(answer_store):
    generated = Answer(
        status="answered",
        claims=(
            Claim(text="公司流程。", citation_ids=("parent-1",)),
            Claim(text="官方依據。", citation_ids=("parent-2",)),
        ),
        citations=("parent-1", "parent-2"),
        reason=None,
    )
    runner, _ = service(answer_store, generated)
    got = ask(runner)
    assert got.status == "answered"
    assert got.claims[0].text.startswith("【虛構公司流程】")
    assert got.claims[1].text.startswith("【官方依據】")
    details = citation_details(HR, "parent-1", DAY, store=answer_store)
    assert details["title"] == "合成來源C01" and details["is_synthetic"] is True
    assert details["version_id"] == "v1" and details["section_id"] == "section"
    assert details["effective_from"] == "2026-10-01"


@pytest.mark.parametrize("text", ["请假", "规定", "累计天数"])
def test_simplified_output_rejected(answer_store, text):
    runner, _ = service(answer_store, result(text=text))
    assert ask(runner).status == "error"


def test_simplified_reason_rejected(answer_store):
    runner, _ = service(answer_store, result(status="insufficient", reason="资料不足"))
    assert ask(runner).status == "error"


def test_ambiguous_traditional_characters_are_not_auto_converted():
    assert not contains_simplified("皇后住在台北，干涉公里計算，只有余先生知道。")
    assert contains_simplified("请假规定")


def test_moe_traditional_employer_is_not_simplified():
    assert not contains_simplified("雇主應告知勞工排定特別休假。")


def test_partial_and_conflict_status_preserved(answer_store):
    for status in ("insufficient", "conflict"):
        runner, _ = service(
            answer_store, result(status=status, reason="另一部分待核對。")
        )
        got = ask(runner)
        assert got.status == status and got.claims
        assert (
            "待人工核對" in got.reason
            if status == "conflict"
            else "資料不足" in got.reason
        )


def test_conflicting_official_and_company_fixture_reaches_generator(answer_store):
    statements = {
        "parent-1": "虛構公司規定婚假三日。",
        "parent-2": "官方規定婚假十四日。",
    }
    with answer_store.connect() as db:
        for cid, text in statements.items():
            data = json.loads(
                db.execute(
                    "SELECT chunk_json FROM units WHERE id=?", (cid,)
                ).fetchone()[0]
            )
            data["text"] = text
            db.execute(
                "UPDATE units SET chunk_json=? WHERE id=?", (json.dumps(data), cid)
            )
    runner, _ = service(answer_store)

    def generate(question, context):
        assert set(statements.values()) <= {unit.text for unit in context.units}
        return Answer(
            status="conflict",
            claims=tuple(
                Claim(text=text, citation_ids=(cid,))
                for cid, text in statements.items()
            ),
            citations=tuple(statements),
            reason="兩份來源日數不一致。",
        )

    runner.generator.generate = generate
    got = ask(runner, "合成婚假規則？")
    assert got.status == "conflict" and len(got.citations) == 2
    assert got.claims[0].text.startswith("【虛構公司流程】")
    assert got.claims[1].text.startswith("【官方依據】")


def test_no_context_never_generates(answer_store):
    runner, calls = service(answer_store)
    runner.retriever.retrieve = lambda *a, **k: []
    got = ask(runner, "我還剩多少天特休？")
    assert got.status == "insufficient" and not calls and not got.claims


def test_personal_balance_cannot_be_invented_from_general_rules(answer_store):
    runner, calls = service(answer_store, result(text="你還剩十三天特休。"))
    got = ask(runner, "我今年還剩多少天特休？")
    assert calls and got.status == "insufficient" and not got.claims
    assert "個人假勤" in got.reason


@pytest.mark.parametrize(
    "question",
    [
        "我還有幾天特休可以用？",
        "特休餘額有幾天？",
        "查詢我的特休結餘",
    ],
)
def test_personal_balance_paraphrases_are_not_entitlement_rules(answer_store, question):
    runner, _ = service(answer_store, result(text="你還剩十三天特休。"))
    got = ask(runner, question)
    assert got.status == "insufficient" and not got.claims


@pytest.mark.parametrize("status", ["insufficient", "conflict"])
def test_reason_cannot_bypass_claim_citations(answer_store, status):
    generated = Answer(
        status=status,
        claims=(),
        citations=(),
        reason="你今年依法可以請十三天特休，並已使用兩天。",
    )
    runner, _ = service(answer_store, generated)
    got = ask(runner)
    assert (
        "十三天" not in got.model_dump_json() and "已使用" not in got.model_dump_json()
    )


def test_unexpected_provider_exception_is_sanitized(answer_store):
    runner, _ = service(answer_store, RuntimeError("secret-transport-content"))
    got = ask(runner)
    assert got.status == "error" and "secret" not in got.model_dump_json()


@pytest.mark.parametrize(
    "bad",
    [
        {"question": "  "},
        {"question": "問題", "as_of": "2026-02-30"},
        {"question": "問題", "role": "hr"},
    ],
)
def test_invalid_input_is_controlled(answer_store, bad):
    runner, calls = service(answer_store)
    assert runner.answer(bad, HR).status == "error" and not calls


@pytest.mark.parametrize(
    "error", [ProviderError("timeout"), ProviderError("invalid_output")]
)
def test_provider_errors_never_expose_output(answer_store, error):
    runner, _ = service(answer_store, error)
    assert ask(runner).status == "error"


def test_withdrawn_during_generation_cannot_be_displayed(answer_store):
    runner, _ = service(answer_store, hook=lambda: answer_store.withdraw("C01", "v1"))
    assert ask(runner).status == "error"


def test_citation_whitelist_checks_even_unused_answer_citations(answer_store):
    chunk = eligible_chunks(HR, DAY, store=answer_store)[0]
    context = ContextBundle(
        units=(chunk,),
        citation_map={chunk.id: (chunk.id,)},
        token_count=0,
        dropped_reasons=(),
        config_hash="test",
    )
    generated = Answer(
        status="answered",
        claims=(Claim(text="主張", citation_ids=(chunk.id,)),),
        citations=(chunk.id, "invented"),
        reason=None,
    )
    assert validate_citations(generated, context)


@pytest.mark.parametrize(
    "question",
    ["專案複核使用什麼識別表單？", "內部稽查要用哪張表單？", "審查表單名稱是什麼？"],
)
def test_missing_named_form_does_not_accept_invented_identity(answer_store, question):
    runner, calls = service(answer_store, result(text="識別表單為C01。"))
    got = ask(runner, question)
    assert got.status == "insufficient" and not got.claims and not got.citations
    assert len(calls) == 1


def test_named_form_gate_accepts_explicit_identity_and_ignores_general_questions():
    from hr_rag.answering import missing_form_identity

    assert not missing_form_identity(
        "稽查用哪張表單？", ["稽查使用綠色核對單Z-42，記錄進度。"]
    )
    assert not missing_form_identity(
        "稽查用哪張表單？", ["稽查使用綠色核對單，記錄進度。"]
    )
    assert missing_form_identity(
        "稽查用哪張表單？", ["依當時有效C01補件方式，內部表單未完成不能駁回。"]
    )
    assert not missing_form_identity(
        "表單未填完能拒絕請假嗎？", ["不得因內部表單未完成拒絕。"]
    )


@pytest.mark.parametrize(
    "question,text",
    [
        ("請假表單需要什麼附件？", "申請病假須附診斷證明。"),
        ("表單有什麼欄位一定要填？", "申請人必須填寫姓名與請假起訖日期。"),
        ("什麼情況可以不用表單？", "緊急狀況可以口頭通知。"),
        ("稽查用哪張表單？", "表單名稱：綠色核對單。"),
        ("稽查用哪張表單？", "稽查使用表單 Z-42。"),
    ],
)
def test_form_identity_does_not_reject_other_intents_or_explicit_names(question, text):
    from hr_rag.answering import missing_form_identity

    assert not missing_form_identity(question, [text])
