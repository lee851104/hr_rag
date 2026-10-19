"""本機告警：觸發、恢復、資料不足與不含正文；不連網。"""

import json

import pytest

from hr_rag.answering import AnswerService
from hr_rag.context import ContextSettings
from hr_rag.contracts import Answer, Chunk, Evidence, Principal
from hr_rag.monitoring import FROZEN_PATH, check, evaluate, load_thresholds

THRESHOLDS = {
    "window": 20,
    "error_rate": 0.10,
    "consecutive_model_failures": 3,
    "p95_seconds": 45.0,
    "timeout_seconds": 60.0,
}


def query(status="ok", seconds=1.0, at=0):
    return {
        "stage": "query",
        "status": status,
        "duration_ms": seconds * 1000,
        "recorded_at": f"2026-10-19T00:{at // 60:02d}:{at % 60:02d}+00:00",
    }


def model(status="ok", at=0):
    return query(status, at=at) | {"stage": "generate"}


def guard(at=0):
    return {
        "stage": "guard",
        "status": "error",
        "error_code": "illegal_evidence",
        "recorded_at": query(at=at)["recorded_at"],
    }


def test_frozen_threshold_is_below_timeout_and_matches_lock():
    frozen = load_thresholds()
    assert frozen["p95_seconds"] < frozen["timeout_seconds"]
    assert frozen["window"] == 20 and frozen["error_rate"] == 0.10
    assert frozen["consecutive_model_failures"] == 3
    assert json.loads(FROZEN_PATH.read_text("utf-8"))["frozen_on"]


def test_fewer_than_twenty_queries_is_insufficient_not_zero():
    states = evaluate([query(at=i) for i in range(19)], THRESHOLDS)
    assert states["error_rate"]["state"] == "insufficient_data"
    assert states["error_rate"]["value"] is None
    assert states["latency_p95"]["state"] == "insufficient_data"
    assert states["model_failures"]["state"] == "insufficient_data"
    assert states["illegal_evidence"]["state"] == "ok"


def test_two_errors_in_twenty_triggers_error_rate():
    events = [query("error" if i < 2 else "ok", at=i) for i in range(20)]
    states = evaluate(events, THRESHOLDS)
    assert states["error_rate"] == {"state": "alert", "value": 0.1, "count": 20}
    assert states["latency_p95"]["state"] == "ok"


def test_p95_above_threshold_alerts():
    events = [query(seconds=50 if i >= 18 else 1, at=i) for i in range(20)]
    states = evaluate(events, THRESHOLDS)
    assert states["latency_p95"]["state"] == "alert"
    assert states["latency_p95"]["value"] == 50.0


def test_three_consecutive_model_failures_alert_without_waiting_for_window():
    events = [model("ok", 0), model("error", 1), model("error", 2), model("error", 3)]
    assert evaluate(events, THRESHOLDS)["model_failures"]["state"] == "alert"
    events.append(model("ok", 4))
    assert evaluate(events, THRESHOLDS)["model_failures"]["state"] == "ok"


def test_illegal_evidence_alerts_immediately():
    states = evaluate([query(at=0), guard(at=1)], THRESHOLDS)
    assert states["illegal_evidence"]["state"] == "alert"


def test_check_records_trigger_and_recovery_history_without_text(tmp_path):
    events = tmp_path / "events.jsonl"
    state = tmp_path / "alerts.json"
    bad = [query("error" if i < 2 else "ok", at=i) for i in range(20)]
    bad += [model("error", 30), model("error", 31), model("error", 32), guard(33)]
    bad[-1]["question"] = "限閱正文不得出現"
    events.write_text("".join(json.dumps(e) + "\n" for e in bad), encoding="utf-8")
    first = check(events, state, THRESHOLDS)
    assert {a["metric"] for a in first["active"]} == {
        "error_rate",
        "model_failures",
        "illegal_evidence",
    }
    good = [model("ok", 100)] + [query(at=101 + i) for i in range(20)]
    with events.open("a", encoding="utf-8") as stream:
        stream.writelines(json.dumps(e) + "\n" for e in good)
    second = check(events, state, THRESHOLDS)
    assert second["active"] == []
    history = json.loads(state.read_text("utf-8"))["history"]
    assert [h["event"] for h in history].count("triggered") == 3
    assert [h["event"] for h in history].count("recovered") == 3
    assert "限閱正文" not in state.read_text("utf-8")


def test_normal_401_404_are_not_leaks():
    events = [query(at=i) for i in range(20)]
    events.append({"stage": "http", "status": "error", "error_code": "not_found"})
    assert evaluate(events, THRESHOLDS)["illegal_evidence"]["state"] == "ok"


@pytest.mark.parametrize("bad", [{"p95_seconds": 60}, {"p95_seconds": 61}])
def test_threshold_must_stay_below_timeout(tmp_path, bad):
    path = tmp_path / "monitoring.json"
    path.write_text(json.dumps(THRESHOLDS | bad | {"frozen_on": "x"}), "utf-8")
    with pytest.raises(ValueError):
        load_thresholds(path)



def test_injected_unauthorized_evidence_is_blocked_and_alerts(answer_store, tmp_path):
    """故意注入：檢索器回傳employee無權的C04；防線攔下、不送模型並觸發告警。"""
    with answer_store.connect() as db:
        rows = db.execute("SELECT chunk_json FROM units WHERE parent=0").fetchall()
    chunks = [Chunk.model_validate_json(row[0]) for row in rows]
    sent = []

    class Leaky:
        store = answer_store

        def retrieve(self, question, principal, as_of, mode):
            return [Evidence(chunk=c, score=1) for c in chunks]

    class Generator:
        def generate(self, question, context):
            sent.append(context)
            return Answer(status="insufficient", claims=(), citations=(), reason=None)

    service = AnswerService(
        retriever=Leaky(),
        generator=Generator(),
        config=ContextSettings(context_max_units=5, min_relevance=0),
    )
    service.answer(
        {"question": "合成問題", "as_of": "2026-10-18"},
        Principal(user_id="u", role="employee"),
    )
    assert sent and {u.document_id for u in sent[0].units} == {"C01"}
    log = (tmp_path / "events.jsonl").read_text("utf-8")
    events = [json.loads(x) for x in log.splitlines()]
    assert any(
        e["stage"] == "guard" and e["error_code"] == "illegal_evidence" for e in events
    )
    assert evaluate(events, THRESHOLDS)["illegal_evidence"]["state"] == "alert"
    assert "合成限閱正文" not in log
