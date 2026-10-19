"""本機告警：只讀一般事件的非正文欄位；不寄外部通知、不跑背景排程。"""

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from hr_rag.settings import PROJECT_ROOT

FROZEN_PATH = PROJECT_ROOT / "config/monitoring.json"
STATE_PATH = PROJECT_ROOT / ".runtime/monitoring-alerts.json"
METRICS = ("error_rate", "latency_p95", "model_failures", "illegal_evidence")


def load_thresholds(path: Path = FROZEN_PATH) -> dict:
    values = json.loads(Path(path).read_text("utf-8"))
    if (
        not values.get("frozen_on")
        or values["window"] != 20
        or not 0 < values["error_rate"] <= 1
        or values["consecutive_model_failures"] < 1
        or not 0 < values["p95_seconds"] < values["timeout_seconds"]
    ):
        raise ValueError("invalid_monitoring_thresholds")
    return values


def _p95(values):
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def evaluate(events, thresholds) -> dict:
    """未知或不足的指標標資料不足，不把缺值當成零。"""
    queries = [e for e in events if e.get("stage") == "query"]
    window = queries[-thresholds["window"] :]
    full = len(window) == thresholds["window"]
    states = {}
    if full:
        rate = sum(e.get("status") != "ok" for e in window) / len(window)
        states["error_rate"] = {
            "state": "alert" if rate >= thresholds["error_rate"] else "ok",
            "value": rate,
            "count": len(window),
        }
    else:
        states["error_rate"] = {
            "state": "insufficient_data",
            "value": None,
            "count": len(window),
        }
    durations = [
        e["duration_ms"] / 1000
        for e in window
        if type(e.get("duration_ms")) in (int, float)
        and math.isfinite(e["duration_ms"])
    ]
    if full and len(durations) == len(window):
        value = _p95(durations)
        states["latency_p95"] = {
            "state": "alert" if value > thresholds["p95_seconds"] else "ok",
            "value": value,
            "count": len(durations),
        }
    else:
        states["latency_p95"] = {
            "state": "insufficient_data",
            "value": None,
            "count": len(durations),
        }
    calls = [e.get("status") for e in events if e.get("stage") == "generate"]
    limit = thresholds["consecutive_model_failures"]
    if not calls:
        states["model_failures"] = {"state": "insufficient_data", "value": None}
    else:
        streak = 0
        for status in reversed(calls):
            if status == "ok":
                break
            streak += 1
        states["model_failures"] = {
            "state": "alert" if streak >= limit else "ok",
            "value": streak,
        }
    since = window[0].get("recorded_at", "") if full else ""
    blocked = [
        e
        for e in events
        if e.get("stage") == "guard"
        and e.get("error_code") == "illegal_evidence"
        and str(e.get("recorded_at", "")) >= since
    ]
    states["illegal_evidence"] = {
        "state": "alert" if blocked else "ok",
        "value": len(blocked),
    }
    return states


def _read_events(path: Path):
    if not path.exists():
        return []
    events = []
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def check(event_path: Path, state_path: Path, thresholds=None) -> dict:
    """比對上次狀態，記錄觸發／恢復；歷史只含指標名稱、數值與時間。"""
    thresholds = thresholds or load_thresholds()
    states = evaluate(_read_events(Path(event_path)), thresholds)
    state_path = Path(state_path)
    previous = (
        json.loads(state_path.read_text("utf-8"))
        if state_path.exists()
        else {"current": {}, "history": []}
    )
    now = datetime.now(timezone.utc).isoformat()
    history = list(previous["history"])
    for metric in METRICS:
        before = previous["current"].get(metric, {}).get("state")
        after = states[metric]["state"]
        if after == "alert" and before != "alert":
            history.append(
                {
                    "at": now,
                    "metric": metric,
                    "event": "triggered",
                    "value": states[metric]["value"],
                }
            )
        elif before == "alert" and after != "alert":
            history.append(
                {
                    "at": now,
                    "metric": metric,
                    "event": "recovered",
                    "value": states[metric]["value"],
                    "state": after,
                }
            )
    result = {
        "checked_at": now,
        "thresholds": {
            k: thresholds[k]
            for k in (
                "window",
                "error_rate",
                "consecutive_model_failures",
                "p95_seconds",
            )
        },
        "current": states,
        "history": history,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(state_path)
    return {
        "checked_at": now,
        "current": states,
        "active": [
            {"metric": m, **states[m]} for m in METRICS if states[m]["state"] == "alert"
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="本機告警檢查（不含正文）")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--events", type=Path)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    args = parser.parse_args()
    events = args.events or Path(
        os.environ.get("HR_RAG_EVENT_PATH", PROJECT_ROOT / "reports/events.jsonl")
    )
    print(json.dumps(check(events, args.state), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
