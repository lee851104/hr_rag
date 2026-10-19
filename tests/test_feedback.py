"""回饋閉環：enum限制、本人範圍、處置狀態與回歸證據；不連網。"""

import json
import subprocess
import sys

import pytest

from hr_rag.feedback import FeedbackStore, load_regression

OWNER = "a" * 64
OTHER = "b" * 64
TRACE = "8a0f7d1e-1111-4222-8333-444455556666"


def junit(tmp_path, *, failures=0, errors=0, name="test_citation_fix"):
    path = tmp_path / "regression.xml"
    case = f'<testcase classname="tests.test_x" name="{name}" time="0.1"'
    case += "><failure>x</failure></testcase>" if failures else "/>"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        f'<testsuite name="pytest" tests="1" failures="{failures}" '
        f'errors="{errors}" skipped="0">{case}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def store(tmp_path):
    return FeedbackStore(tmp_path / "feedback.sqlite3")


def test_submit_accepts_only_enums_and_reason_rules(store):
    fid = store.submit(TRACE, OWNER, "not_useful", "citation_issue")
    assert store.for_trace(TRACE, OWNER)[0]["status"] == "pending"
    assert store.submit(TRACE, OWNER, "useful", None)
    for rating, reason in [
        ("great", None),
        ("not_useful", None),
        ("not_useful", "我的身分證字號"),
        ("useful", "other"),
    ]:
        with pytest.raises(ValueError):
            store.submit(TRACE, OWNER, rating, reason)
    assert fid


def test_user_sees_only_own_feedback_without_answer_text(store):
    store.submit(TRACE, OWNER, "not_useful", "off_topic")
    assert store.for_trace(TRACE, OTHER) == []
    shown = store.for_trace(TRACE, OWNER)[0]
    assert set(shown) == {"feedback_id", "rating", "reason", "status", "created_at"}


def test_fixed_requires_passing_regression_evidence(store, tmp_path):
    fid = store.submit(TRACE, OWNER, "not_useful", "citation_issue")
    with pytest.raises(ValueError, match="handler_required"):
        store.update(fid, "analyzed", handler="", note="原因")
    store.update(fid, "analyzed", handler="維護者", note="引用指向背景段落")
    with pytest.raises(ValueError, match="regression_required"):
        store.update(fid, "fixed", handler="維護者", note="修正", fix_reference="x")
    with pytest.raises(ValueError, match="regression_failed"):
        store.update(
            fid,
            "fixed",
            handler="維護者",
            note="修正",
            fix_reference="tests/test_x.py::test_citation_fix",
            regression=junit(tmp_path, failures=1),
        )
    with pytest.raises(ValueError, match="fix_reference_required"):
        store.update(
            fid, "fixed", handler="維護者", note="修正", regression=junit(tmp_path)
        )
    store.update(
        fid,
        "fixed",
        handler="維護者",
        note="修正",
        fix_reference="tests/test_x.py::test_citation_fix",
        regression=junit(tmp_path),
    )
    record = store.get(fid)
    assert record["status"] == "fixed" and record["trace_id"] == TRACE
    assert record["regression"]["passed"] == ["tests.test_x::test_citation_fix"]
    assert len(record["regression"]["sha256"]) == 64
    assert [h["to"] for h in record["history"]] == ["analyzed", "fixed"]
    assert record["history"][-1]["handler"] == "維護者"


def test_wont_fix_needs_reason_and_closed_items_stay_closed(store, tmp_path):
    fid = store.submit(TRACE, OWNER, "not_useful", "other")
    with pytest.raises(ValueError, match="note_required"):
        store.update(fid, "wont_fix", handler="維護者", note="")
    store.update(fid, "wont_fix", handler="維護者", note="屬語料範圍外")
    with pytest.raises(ValueError, match="invalid_transition"):
        store.update(fid, "analyzed", handler="維護者", note="重開")


def test_fix_reference_must_be_a_passed_testcase(store, tmp_path):
    fid = store.submit(TRACE, OWNER, "not_useful", "citation_issue")
    store.update(fid, "analyzed", handler="維護者", note="分析")
    with pytest.raises(ValueError, match="regression_missing_reference"):
        store.update(
            fid,
            "fixed",
            handler="維護者",
            note="修正",
            fix_reference="tests/test_x.py::test_other",
            regression=junit(tmp_path),
        )


def test_regression_parser_rejects_empty_runs(tmp_path):
    path = tmp_path / "empty.xml"
    path.write_text(
        '<testsuites><testsuite tests="0" failures="0" errors="0"/></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="regression_failed"):
        load_regression(path)


def test_feedback_cli_update_and_list(store, tmp_path):
    fid = store.submit(TRACE, OWNER, "not_useful", "citation_issue")
    env_args = ["--path", str(store.path)]
    run = dict(capture_output=True, text=True, encoding="utf-8", check=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "hr_rag.feedback",
            *env_args,
            "update",
            "--id",
            fid,
            "--status",
            "analyzed",
            "--handler",
            "維護者",
            "--note",
            "分析",
        ],
        **run,
    )
    listed = subprocess.run(
        [sys.executable, "-m", "hr_rag.feedback", *env_args, "list"], **run
    )
    rows = json.loads(listed.stdout)
    assert rows[0]["feedback_id"] == fid and rows[0]["status"] == "analyzed"
    assert "user_ref" not in rows[0]
