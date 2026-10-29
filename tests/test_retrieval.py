from datetime import date

import numpy as np
import pytest
from test_query import CharacterTokenizer

from hr_rag.contracts import Principal
from hr_rag.query import QueryError
from hr_rag.retrieval import Retriever, lexical_tokens, rrf


class Encoder:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.extend(texts)
        return [[1.0, 0.0, 0.0]]


class Reranker:
    def __init__(self):
        self.inputs = []

    def rerank(self, query, texts):
        self.inputs.extend(texts)
        return list(range(len(texts)))


def engine(store):
    return Retriever(
        store=store,
        embedder=Encoder(),
        reranker=Reranker(),
        tokenizers=(CharacterTokenizer(), CharacterTokenizer()),
    )


@pytest.mark.parametrize("mode", ["dense", "hybrid", "rerank"])
def test_prefilter_excludes_high_similarity_forbidden_and_expired(policy_store, mode):
    runner = engine(policy_store)
    result = runner.retrieve(
        "合成", Principal(user_id="e", role="employee"), date(2026, 10, 1), mode
    )
    assert [e.chunk.id for e in result] == ["id-1"]
    assert all(
        "C04" not in text and "C03" not in text for text in runner.reranker.inputs
    )
    policy_store.withdraw("C01", "v1")
    assert (
        runner.retrieve(
            "合成", Principal(user_id="e", role="employee"), date(2026, 10, 1), mode
        )
        == []
    )


def test_predictable_cosine_rank_and_stable_ties(policy_store):
    vectors = np.array(
        [[0, 1, 0], [0, 1, 0], [1, 0, 0], [1, 0, 0], [1, 0, 0]], dtype=np.float32
    )
    sha = policy_store.write_snapshot("ranked", vectors)
    # fixture替換向量檔，SQLite仍指同一已驗證形狀。
    target = policy_store.root / "snapshots/synthetic.npy"
    target.write_bytes((policy_store.root / "snapshots/ranked.npy").read_bytes())
    with policy_store.connect() as db:
        db.execute("UPDATE generations SET snapshot_hash=?", (sha,))
    result = engine(policy_store).retrieve(
        "合成", Principal(user_id="hr", role="hr"), date(2026, 10, 1), "dense"
    )
    assert [e.chunk.id for e in result] == ["id-2", "id-3", "id-1"]


def test_long_query_never_calls_encoder(policy_store):
    runner = engine(policy_store)
    with pytest.raises(QueryError):
        runner.retrieve(
            "甲" * 100,
            Principal(user_id="e", role="employee"),
            date(2026, 10, 1),
            "dense",
        )
    assert runner.embedder.calls == [] and runner.reranker.inputs == []


@pytest.mark.parametrize("mode", ["dense", "hybrid", "rerank"])
def test_synonym_pair_hits_same_required_group(policy_store, mode):
    from hr_rag.evaluation import coverage

    runner = engine(policy_store)
    results = [
        runner.retrieve(
            query, Principal(user_id="e", role="employee"), date(2026, 10, 1), mode
        )
        for query in ["特休幾天？", "特別休假幾天？"]
    ]
    groups = [[("C01", "v1", "section")]]
    for found in results:
        refs = [
            (e.chunk.document_id, e.chunk.version_id, e.chunk.section_id) for e in found
        ]
        assert coverage(groups, refs)["all_hit"]
    assert results[0] == results[1]
    assert runner.embedder.calls == ["特別休假幾天？"] * 2


def test_rrf_limits_and_lexical_locators():
    scores = rrf(["a", "b"], ["b", "a"])
    assert scores["a"] == scores["b"] == 1 / 61 + 1 / 62
    assert {"第38條", "2026-10-01", "14"} <= set(
        lexical_tokens("第38條於2026-10-01請假14日")
    )


def test_date_conflict_does_not_call_models(policy_store):
    runner = engine(policy_store)
    with pytest.raises(QueryError, match="date_conflict"):
        runner.retrieve(
            "民國115年9月30日",
            Principal(user_id="e", role="employee"),
            date(2026, 10, 1),
            "dense",
        )
    assert runner.embedder.calls == []


def test_missing_acl_denied_before_any_scoring(policy_store):
    import json

    with policy_store.connect() as db:
        data = json.loads(
            db.execute("SELECT chunk_json FROM units WHERE id='id-1'").fetchone()[0]
        )
        del data["allowed_roles"]
        db.execute("UPDATE units SET chunk_json=? WHERE id='id-1'", (json.dumps(data),))
    runner = engine(policy_store)
    assert (
        runner.retrieve(
            "合成", Principal(user_id="e", role="employee"), date(2026, 10, 1), "dense"
        )
        == []
    )
    assert runner.embedder.calls == []


def test_reranker_is_capped_at_twenty(policy_store):
    import json

    with policy_store.connect() as db:
        data = json.loads(
            db.execute("SELECT chunk_json FROM units WHERE id='id-1'").fetchone()[0]
        )
        for index in range(25):
            extra = {**data, "id": f"extra-{index:02}"}
            db.execute(
                "INSERT INTO units VALUES (?,?,?,?,?,?)",
                ("synthetic", extra["id"], 0, json.dumps(extra), index + 5, "{}"),
            )
    sha = policy_store.write_snapshot("cap", np.ones((30, 3), dtype=np.float32))
    (policy_store.root / "snapshots/synthetic.npy").write_bytes(
        (policy_store.root / "snapshots/cap.npy").read_bytes()
    )
    with policy_store.connect() as db:
        db.execute("UPDATE generations SET rows=30,snapshot_hash=?", (sha,))
    runner = engine(policy_store)
    result = runner.retrieve(
        "合成", Principal(user_id="e", role="employee"), date(2026, 10, 1), "rerank"
    )
    assert len(result) == 5 and len(runner.reranker.inputs) == 20


def test_withdraw_during_embedding_not_sent_to_reranker(policy_store):
    runner = engine(policy_store)

    class WithdrawingEncoder(Encoder):
        def embed(self, texts):
            policy_store.withdraw("C04", "v3")
            return super().embed(texts)

    runner.embedder = WithdrawingEncoder()
    result = runner.retrieve(
        "合成", Principal(user_id="h", role="hr"), date(2026, 10, 1), "rerank"
    )
    assert all("C04" not in text for text in runner.reranker.inputs)
    assert all(e.chunk.document_id != "C04" for e in result)


def test_compound_rerank_retains_independent_second_clause(policy_store):
    runner = engine(policy_store)
    calls = []

    class ClauseReranker:
        def rerank(self, query, texts):
            calls.append((query, texts))
            if query == "未完成流程是否可以拒絕":
                return [0.99 if "C03" in t else 0.1 for t in texts]
            return [0.8 if "C01" in t else 0.01 for t in texts]

    runner.reranker = ClauseReranker()
    result = runner.retrieve(
        "申請需要哪些資料，以及未完成流程是否可以拒絕。",
        Principal(user_id="manager", role="manager"),
        date(2026, 10, 1),
        "rerank",
    )
    assert calls[1][0] == "未完成流程是否可以拒絕"
    assert result[0].chunk.document_id == "C03"
    assert all("C04" not in t for _, texts in calls for t in texts)


def test_compound_query_keeps_full_negation_dates_and_bounded_subqueries():
    from hr_rag.query import rerank_queries

    query = "2026-10-01不是特休，以及未滿14日不能拒絕。"
    assert rerank_queries(query) == (query, "未滿14日不能拒絕")
    assert rerank_queries("不是特休，以及補休") == ("不是特休，以及補休",)
    assert (
        len(
            rerank_queries(
                "需要資料，以及需要核對資料，以及需要保留資料，以及需要刪除資料"
            )
        )
        <= 3
    )


def test_invalid_clause_scores_are_rejected(policy_store):
    runner = engine(policy_store)

    class Invalid:
        def rerank(self, query, texts):
            return (
                [float("nan")] * len(texts)
                if query.startswith("未完成")
                else [0.8] * len(texts)
            )

    runner.reranker = Invalid()
    from hr_rag.providers import ProviderError

    with pytest.raises(ProviderError, match="invalid_reranking"):
        runner.retrieve(
            "申請需要哪些資料，以及未完成流程是否可以拒絕。",
            Principal(user_id="e", role="employee"),
            date(2026, 10, 1),
            "rerank",
        )


def test_revocation_between_rerank_clauses_never_sends_second_request(policy_store):
    from hr_rag.providers import ProviderError

    runner = engine(policy_store)
    calls = []

    class RevokingReranker:
        def rerank(self, query, texts):
            calls.append(query)
            policy_store.withdraw("C03", "v2")
            return [0.8] * len(texts)

    runner.reranker = RevokingReranker()
    with pytest.raises(ProviderError, match="corpus_changed"):
        runner.retrieve(
            "申請需要哪些資料，以及未完成流程是否可以拒絕。",
            Principal(user_id="m", role="manager"),
            date(2026, 10, 1),
            "rerank",
        )
    assert len(calls) == 1


def _traced_notes():
    from hr_rag import audit

    collector = {"exchanges": [], "contexts": [], "notes": {}}
    return collector["notes"], audit._TRACE.set(("trace", collector))


def test_retrieve_records_embed_and_rerank_stage_ms(policy_store):
    from hr_rag import audit

    notes, token = _traced_notes()
    try:
        engine(policy_store).retrieve(
            "合成", Principal(user_id="hr", role="hr"), date(2026, 10, 1), "rerank"
        )
    finally:
        audit._TRACE.reset(token)
    # 已注入模型時不得出現載入耗時，避免把冷啟動算進暖機後的分段。
    assert set(notes["stage_ms"]) == {"embed", "rerank"}
    assert all(value >= 0 for value in notes["stage_ms"].values())


def test_first_request_records_model_load_separately(policy_store, monkeypatch):
    from hr_rag import audit, retrieval

    created = []

    class FakeEncoder:
        def __init__(self, role, path, settings):
            created.append(role)
            self.role = role

        def embed(self, texts):
            return [[1.0, 0.0, 0.0]]

        def rerank(self, query, texts):
            return [0.9] * len(texts)

        def close(self):
            pass

    monkeypatch.setattr(retrieval, "LocalEncoder", FakeEncoder)
    runner = engine(policy_store)
    runner.embedder = runner.reranker = None
    notes, token = _traced_notes()
    try:
        runner.retrieve(
            "合成", Principal(user_id="hr", role="hr"), date(2026, 10, 1), "rerank"
        )
    finally:
        audit._TRACE.reset(token)
    assert created == ["embedding", "reranker"]
    assert set(notes["stage_ms"]) == {"model_load", "embed", "rerank"}


def test_warmup_loads_and_exercises_both_models_once(policy_store, monkeypatch):
    import threading

    from hr_rag import retrieval

    created, calls = [], []
    gate = threading.Event()

    class SlowEncoder:
        def __init__(self, role, path, settings):
            gate.wait(1)
            created.append(role)

        def embed(self, texts):
            calls.append("embed")
            return [[1.0, 0.0, 0.0]] * len(texts)

        def rerank(self, query, texts):
            calls.append("rerank")
            return [0.5] * len(texts)

        def close(self):
            pass

    monkeypatch.setattr(retrieval, "LocalEncoder", SlowEncoder)
    runner = engine(policy_store)
    runner.embedder = runner.reranker = None
    workers = [threading.Thread(target=runner.warmup) for _ in range(3)]
    for worker in workers:
        worker.start()
    gate.set()
    for worker in workers:
        worker.join(5)
    # 並行預熱或預熱撞上首查，都只能各建立一個模型子程序。
    assert sorted(created) == ["embedding", "reranker"]
    assert calls.count("embed") == 3 and calls.count("rerank") == 3
    runner.retrieve(
        "合成", Principal(user_id="hr", role="hr"), date(2026, 10, 1), "rerank"
    )
    assert sorted(created) == ["embedding", "reranker"]


def test_candidate_limit_bounds_rerank_inputs(policy_store):
    runner = engine(policy_store)
    runner.candidate_limit = 1
    runner.retrieve(
        "合成", Principal(user_id="hr", role="hr"), date(2026, 10, 1), "rerank"
    )
    assert len(runner.reranker.inputs) == 1
