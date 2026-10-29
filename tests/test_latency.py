from datetime import date

import pytest

from hr_rag import latency
from hr_rag.contracts import Principal

A = ("A", "v1", "1")
B = ("B", "v1", "2")
C = ("C", "v1", "3")


def test_recall_at_k_counts_groups_within_first_k():
    groups = [[A], [B]]
    refs = [C, A, B]
    assert latency.recall_at(groups, refs, 1) == 0
    assert latency.recall_at(groups, refs, 2) == 0.5
    assert latency.recall_at(groups, refs, 3) == 1
    assert latency.recall_at([], refs, 3) is None


def test_reciprocal_rank_uses_first_required_hit():
    assert latency.reciprocal_rank([[A], [B]], [C, B, A]) == 0.5
    assert latency.reciprocal_rank([[A]], [C]) == 0
    assert latency.reciprocal_rank([], [A]) is None


def test_percentile_is_nearest_rank_and_none_when_empty():
    assert latency.percentile([3, 1, 2, 4], 50) == 2
    assert latency.percentile([3, 1, 2, 4], 95) == 4
    assert latency.percentile([], 95) is None


@pytest.mark.parametrize(
    "output, generate, ttft, expected",
    [
        (30, 1500, 1000, 60.0),
        (30, 1000, 1000, None),
        (None, 1500, 1000, None),
        (30, 1500, None, None),
    ],
)
def test_tokens_per_second_excludes_time_to_first_token(
    output, generate, ttft, expected
):
    assert latency.tokens_per_second(output, generate, ttft) == expected


def test_summary_separates_answerable_recall_and_latency():
    rows = [
        {
            "candidate_limit": 20,
            "answerable": True,
            "recall_at": {"1": 1, "3": 1, "5": 1},
            "reciprocal_rank": 1,
            "stage_ms": {"rerank": 100, "embed": 1},
            "retrieve_ms": 120,
        },
        {
            "candidate_limit": 20,
            "answerable": True,
            "recall_at": {"1": 0, "3": 0.5, "5": 1},
            "reciprocal_rank": 0.5,
            "stage_ms": {"rerank": 300, "embed": 1},
            "retrieve_ms": 320,
        },
        {
            "candidate_limit": 20,
            "answerable": False,
            "recall_at": {"1": None, "3": None, "5": None},
            "reciprocal_rank": None,
            "stage_ms": {"rerank": 200, "embed": 1},
            "retrieve_ms": 220,
        },
    ]
    summary = latency.summarize(rows)["20"]
    assert summary["answerable"] == 2 and summary["rows"] == 3
    assert summary["recall_at"] == {"1": 0.5, "3": 0.75, "5": 1.0}
    assert summary["all_hit_at_5"] == 2 and summary["mrr"] == 0.75
    assert summary["retrieve_ms"] == {"p50": 220, "p95": 320}
    assert summary["rerank_ms"] == {"p50": 200, "p95": 300}


def test_measure_retrieval_records_stage_ms_per_limit(policy_store):
    from test_retrieval import engine

    question = {
        "question_id": "Q1",
        "question": "合成",
        "as_of": "2026-10-01",
        "role_expectations": {
            "hr": {
                "expected_behavior": "answered",
                "required_evidence_groups": [
                    [{"document_id": "C01", "version_id": "v1", "section_id": "s"}]
                ],
            }
        },
    }
    runner = engine(policy_store)
    rows = latency.measure_retrieval(runner, [question], [20, 1])
    assert [row["candidate_limit"] for row in rows] == [20, 1]
    assert all({"embed", "rerank"} <= set(row["stage_ms"]) for row in rows)
    assert all(row["retrieve_ms"] >= 0 for row in rows)
    assert runner.candidate_limit == 20
    assert Principal(user_id="x", role="hr")  # 角色字串必須是合法角色
    assert date.fromisoformat(question["as_of"])
