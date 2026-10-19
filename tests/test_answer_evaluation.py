from hr_rag.answer_evaluation import summarize


def test_frozen_development_and_stability_jobs_have_fixed_roles():
    from hr_rag.answer_evaluation import build_jobs

    assert len(build_jobs("development")) == 26
    jobs = build_jobs("stability")
    assert len(jobs) == 18
    assert len({(q.question_id, role) for q, role, _ in jobs}) == 6


def test_missing_or_error_rows_cannot_pass_or_shrink_denominator():
    result = summarize([], kind="development")
    assert result["planned_executions"] == 26
    assert result["complete"] is False and result["accepted"] is False
    assert result["human_review_pending"] is True


def test_success_status_is_not_human_semantic_approval():
    rows = [{"answer": {"status": "answered"}, "exchange_count": 1} for _ in range(18)]
    result = summarize(rows, kind="stability")
    assert result["complete"] and result["api_calls"] == 18
    assert not result["accepted"] and result["human_review_pending"]
