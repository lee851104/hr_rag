"""本人查詢回饋與本機處置；只存分類與狀態，不複製答案正文、不自動改知識庫。"""

import argparse
import hashlib
import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ElementTree
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from hr_rag.settings import PROJECT_ROOT

RATINGS = {"useful", "not_useful"}
REASONS = {
    "off_topic": "答非所問",
    "insufficient_evidence": "證據不足",
    "citation_issue": "引用問題",
    "other": "其他",
}
STATUS_LABELS = {
    "pending": "待處理",
    "analyzed": "已分析",
    "fixed": "已修正",
    "wont_fix": "不處理",
}
TRANSITIONS = {
    "pending": {"analyzed", "wont_fix"},
    "analyzed": {"fixed", "wont_fix"},
    "fixed": set(),
    "wont_fix": set(),
}


def load_regression(path: Path) -> dict:
    """pytest JUnit XML：至少一項、零失敗零錯誤，回傳通過的測試識別。"""
    raw = Path(path).read_bytes()
    root = ElementTree.fromstring(raw)
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = sum(int(s.get("tests", 0)) for s in suites)
    bad = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    passed = [
        f"{case.get('classname')}::{case.get('name')}"
        for suite in suites
        for case in suite.iter("testcase")
        if all(case.find(tag) is None for tag in ("failure", "error", "skipped"))
    ]
    if total == 0 or bad or not passed:
        raise ValueError("regression_failed")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "tests": total,
        "passed": passed,
    }


def _reference_id(reference: str) -> str:
    # tests/test_x.py::test_y → tests.test_x::test_y（pytest JUnit的classname格式）
    module, _, name = reference.partition("::")
    return module.removesuffix(".py").replace("/", ".").replace("\\", ".") + "::" + name


class FeedbackStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(
            path
            or os.environ.get("HR_RAG_FEEDBACK_PATH")
            or PROJECT_ROOT / ".runtime/audit-private/feedback.sqlite3"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
                    user_ref TEXT NOT NULL, rating TEXT NOT NULL, reason TEXT,
                    status TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback_history (
                    feedback_id TEXT NOT NULL REFERENCES feedback(feedback_id),
                    at INTEGER NOT NULL, handler TEXT NOT NULL,
                    from_status TEXT NOT NULL, to_status TEXT NOT NULL,
                    note TEXT NOT NULL, fix_reference TEXT, regression_json TEXT
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def submit(self, trace_id, user_ref, rating, reason) -> str:
        if rating not in RATINGS:
            raise ValueError("invalid_rating")
        if rating == "useful" and reason:
            raise ValueError("invalid_reason")
        if rating == "not_useful" and reason not in REASONS:
            raise ValueError("invalid_reason")
        feedback_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO feedback VALUES (?,?,?,?,?,?,?)",
                (
                    feedback_id,
                    trace_id,
                    user_ref,
                    rating,
                    reason or None,
                    "pending",
                    int(time.time()),
                ),
            )
        return feedback_id

    def for_trace(self, trace_id, user_ref) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT feedback_id,rating,reason,status,created_at FROM feedback "
                "WHERE trace_id=? AND user_ref=? ORDER BY created_at,feedback_id",
                (trace_id, user_ref),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, feedback_id) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT feedback_id,trace_id,rating,reason,status,created_at "
                "FROM feedback WHERE feedback_id=?",
                (feedback_id,),
            ).fetchone()
            if row is None:
                raise ValueError("feedback_not_found")
            history = db.execute(
                "SELECT * FROM feedback_history WHERE feedback_id=? ORDER BY rowid",
                (feedback_id,),
            ).fetchall()
        record = dict(row)
        record["history"] = [
            {
                "at": h["at"],
                "handler": h["handler"],
                "from": h["from_status"],
                "to": h["to_status"],
                "note": h["note"],
                "fix_reference": h["fix_reference"],
                "regression": json.loads(h["regression_json"])
                if h["regression_json"]
                else None,
            }
            for h in history
        ]
        record["regression"] = next(
            (h["regression"] for h in reversed(record["history"]) if h["regression"]),
            None,
        )
        return record

    def list(self, status=None) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT feedback_id,trace_id,rating,reason,status,created_at "
                "FROM feedback WHERE ?1 IS NULL OR status=?1 "
                "ORDER BY created_at,feedback_id",
                (status,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update(
        self, feedback_id, status, *, handler, note, fix_reference=None, regression=None
    ):
        """已修正須附通過且包含修正測試的回歸證據；不處理須附理由。"""
        if not str(handler or "").strip():
            raise ValueError("handler_required")
        if not str(note or "").strip():
            raise ValueError("note_required")
        current = self.get(feedback_id)["status"]
        if status not in TRANSITIONS[current]:
            raise ValueError("invalid_transition")
        evidence = None
        if status == "fixed":
            if regression is None:
                raise ValueError("regression_required")
            evidence = load_regression(regression)
            if not str(fix_reference or "").strip():
                raise ValueError("fix_reference_required")
            if _reference_id(fix_reference) not in evidence["passed"]:
                raise ValueError("regression_missing_reference")
        with self.connect() as db:
            if (
                db.execute(
                    "UPDATE feedback SET status=? WHERE feedback_id=? AND status=?",
                    (status, feedback_id, current),
                ).rowcount
                != 1
            ):
                raise ValueError("invalid_transition")
            db.execute(
                "INSERT INTO feedback_history VALUES (?,?,?,?,?,?,?,?)",
                (
                    feedback_id,
                    int(time.time()),
                    handler.strip(),
                    current,
                    status,
                    note.strip(),
                    fix_reference,
                    json.dumps(evidence, ensure_ascii=False) if evidence else None,
                ),
            )


def main():
    parser = argparse.ArgumentParser(description="本機回饋處置（維護者）")
    parser.add_argument("--path", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    listed = commands.add_parser("list")
    listed.add_argument("--status", choices=sorted(STATUS_LABELS))
    shown = commands.add_parser("show")
    shown.add_argument("--id", required=True)
    changed = commands.add_parser("update")
    changed.add_argument("--id", required=True)
    changed.add_argument("--status", choices=sorted(STATUS_LABELS), required=True)
    changed.add_argument("--handler", required=True)
    changed.add_argument("--note", required=True)
    changed.add_argument("--fix-ref")
    changed.add_argument("--regression", type=Path)
    args = parser.parse_args()
    store = FeedbackStore(args.path)
    if args.command == "list":
        result = store.list(args.status)
    elif args.command == "show":
        result = store.get(args.id)
    else:
        store.update(
            args.id,
            args.status,
            handler=args.handler,
            note=args.note,
            fix_reference=args.fix_ref,
            regression=args.regression,
        )
        result = store.get(args.id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
