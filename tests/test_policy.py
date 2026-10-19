"""獨立合成權限／日期fixture，不使用保留題。"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from hr_rag.contracts import Principal
from hr_rag.policy import clarify_date, eligible_chunks


@pytest.mark.parametrize(
    "role,expected",
    [
        ("employee", {"id-1"}),
        ("manager", {"id-1", "id-2"}),
        ("hr", {"id-1", "id-2", "id-3"}),
    ],
)
def test_role_matrix(policy_store, role, expected):
    result = eligible_chunks(
        Principal(user_id=role, role=role), date(2026, 10, 1), store=policy_store
    )
    assert {c.id for c in result} == expected


def test_half_open_dates_and_missing_acl_deny(policy_store):
    principal = Principal(user_id="employee", role="employee")
    assert {
        c.id for c in eligible_chunks(principal, date(2026, 9, 30), store=policy_store)
    } == {"id-0"}
    with policy_store.connect() as db:
        row = db.execute("SELECT chunk_json FROM units WHERE id='id-1'").fetchone()
        chunk = json.loads(row[0])
        del chunk["allowed_roles"]
        db.execute(
            "UPDATE units SET chunk_json=? WHERE id='id-1'", (json.dumps(chunk),)
        )
    assert eligible_chunks(principal, date(2026, 10, 1), store=policy_store) == []


def test_parallel_accounts_and_sequential_downgrade(policy_store):
    def run(role):
        return {
            c.document_id
            for c in eligible_chunks(
                Principal(user_id=role, role=role),
                date(2026, 10, 1),
                store=policy_store,
            )
        }

    roles = ["hr", "employee"] * 8
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, roles))
    for role, documents in zip(roles, results, strict=True):
        assert documents == ({"C01", "C03", "C04"} if role == "hr" else {"C01"})


@pytest.mark.parametrize(
    "question",
    [
        "2026-09-30請假",
        "2026年9月30日請假",
        "民國115年9月30日",
        "115年9月30日",
        "2025年請假",
        "民國114年",
        "115年9月",
        "2026-09請假",
    ],
)
def test_explicit_conflict_displays_both_dates(question):
    result = clarify_date(question, date(2026, 10, 1))
    assert result and question in result and "2026-10-01" in result


@pytest.mark.parametrize(
    "question",
    [
        "今年請假",
        "明年請假",
        "2026年請假",
        "115年10月請假",
        "民國115年10月1日",
        "2026-10-01請假",
    ],
)
def test_relative_or_matching_period_has_no_conflict(question):
    assert clarify_date(question, date(2026, 10, 1)) is None


def test_invalid_explicit_date_requests_clarification():
    assert clarify_date("2026年2月30日請假", date(2026, 10, 1))


@pytest.mark.parametrize(
    "question",
    [
        "任職滿10年有幾天特休？",
        "工作滿20年有幾天？",
        "年資10年可休幾天？",
        "任職10年2月可休幾天？",
        "10年年資有幾天？",
        "服務滿115年是合成年資例子",
    ],
)
def test_tenure_is_duration_not_calendar_year(question):
    assert clarify_date(question, date(2026, 10, 2)) is None


@pytest.mark.parametrize(
    "question",
    [
        "2026年 9 月 30 日請假",
        "民國 115 年 9 月 30 日請假",
        "115 年 9 月請假",
        "2025 年請假",
        "民國 99 年請假",
    ],
)
def test_spaced_absolute_dates_do_not_silently_match_year_only(question):
    result = clarify_date(question, date(2026, 10, 2))
    assert result and question in result and "2026-10-02" in result


@pytest.mark.parametrize("question", ["工作2025年需要幾天假？", "工作115年10月1日開始"])
def test_duration_guard_preserves_clear_calendar_dates(question):
    assert clarify_date(question, date(2026, 10, 2)) is not None
