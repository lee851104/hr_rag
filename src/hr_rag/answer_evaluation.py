"""明確執行的真實生成：開發集、固定穩定案例，及階段7經hash核對的保留題；語意驗收仍待人工。"""

import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

from hr_rag.answering import AnswerService
from hr_rag.contracts import Principal, QueryRequest
from hr_rag.evaluation import (
    DEVELOPMENT_PATH,
    HOLDOUT_MANIFEST_PATH,
    execution_fingerprint,
    verify_baseline,
    verify_holdout_file,
)
from hr_rag.evaluation_schema import _read
from hr_rag.generation import selected_generator
from hr_rag.retrieval import Retriever
from hr_rag.settings import PROJECT_ROOT, load_generation_environment


def summarize(rows, *, kind):
    planned = {"development": 26, "stability": 18}.get(kind) or json.loads(
        HOLDOUT_MANIFEST_PATH.read_text("utf-8")
    )["role_execution_count"]
    return {
        "planned_executions": planned,
        "completed_executions": len(rows),
        "complete": len(rows) == planned,
        "statuses": dict(Counter(row["answer"]["status"] for row in rows)),
        "api_calls": sum(row["exchange_count"] for row in rows),
        "human_review_pending": True,
        "accepted": False,
    }


def cost_totals(path):
    if not path.exists():
        return {"settled_usd": "0", "reserved_usd": "0"}
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT amount,settled FROM costs").fetchall()
    return {
        name: str(
            sum(
                (Decimal(value) for value, flag in rows if flag == expected), Decimal(0)
            )
        )
        for name, expected in (("settled_usd", 1), ("reserved_usd", 0))
    }


def _save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def build_jobs(kind, *, holdout_path=None):
    if kind not in {"development", "stability", "holdout"}:
        raise ValueError("development_only")
    if kind == "holdout":
        if holdout_path is None:
            raise ValueError("holdout_path_required")
        verify_holdout_file(holdout_path)
        _, questions = _read(holdout_path)
        return [(q, role, 1) for q in questions for role in q.role_expectations]
    _, questions = _read(DEVELOPMENT_PATH)
    if kind == "development":
        jobs = [(q, role, 1) for q in questions for role in q.role_expectations]
    else:
        fixed = json.loads(
            (PROJECT_ROOT / "eval/stability-cases.json").read_text("utf-8")
        )
        if (
            fixed["development_sha256"]
            != hashlib.sha256(DEVELOPMENT_PATH.read_bytes()).hexdigest()
        ):
            raise ValueError("stability_changed")
        lookup = {q.question_id: q for q in questions}
        jobs = []
        for case in fixed["cases"]:
            q = lookup[case["question_id"]]
            if (
                hashlib.sha256(
                    json.dumps(
                        q.model_dump(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                != case["question_sha256"]
            ):
                raise ValueError("stability_changed")
            if (
                q.as_of != case["as_of"]
                or q.role_expectations[case["role"]].model_dump()
                != case["expected_result"]
            ):
                raise ValueError("stability_changed")
            jobs.extend((q, case["role"], repeat) for repeat in range(1, 4))
    return jobs


def run(kind, output, *, holdout_path=None):
    if kind == "holdout" and Path(output).resolve().is_relative_to(
        PROJECT_ROOT.resolve()
    ):
        raise ValueError("holdout_output_must_be_external")
    verify_baseline()
    # 既有使用者授權上限US$1；較低的.env設定仍優先，不寫回.env。
    values = load_generation_environment()
    limit = min(Decimal(values.get("HR_RAG_COST_LIMIT_USD", "0")), Decimal("1"))
    configured = bool(values.get("OPENAI_API_KEY", "").strip())
    values.clear()
    if not configured or not limit.is_finite() or limit <= 0:
        raise ValueError("not_configured")
    os.environ["HR_RAG_COST_LIMIT_USD"] = str(limit)
    jobs = build_jobs(kind, holdout_path=holdout_path)
    if output.exists():
        raise ValueError("output_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows, exchanges, contexts = [], [], []
    generator = selected_generator(on_exchange=exchanges.append)
    retriever = Retriever()
    service = AnswerService(
        retriever=retriever, generator=generator, on_context=contexts.append
    )
    fingerprint = execution_fingerprint(retriever.store)
    settings = generator.settings
    report = {
        "kind": kind,
        "split": "holdout" if kind == "holdout" else "development",
        "holdout_sha256": (
            verify_holdout_file(holdout_path) if kind == "holdout" else None
        ),
        "human_review_status": "pending",
        "generation_settings": settings.model_dump(
            mode="json", exclude={"cost_ledger_path"}
        ),
        "cost_limit_usd": str(limit),
        "cost_before": cost_totals(settings.cost_ledger_path),
        "execution_fingerprint": fingerprint,
        "freeze_hashes": {
            name: hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest()
            for name in (
                "eval/development.jsonl",
                "eval/labels.jsonl",
                "eval/labels.supplemental.jsonl",
                "src/hr_rag/retrieval.py",
                "src/hr_rag/query.py",
                "config/retrieval.selected.json",
                "src/hr_rag/answering.py",
                "config/models.lock.json",
                "config/generation.selected.json",
                "eval/stability-cases.json",
            )
        },
        "prompt_sha256": hashlib.sha256(generator.SYSTEM.encode()).hexdigest(),
        "rows": rows,
    }
    try:
        for question, role, repeat in jobs:
            exchanges.clear()
            contexts.clear()
            start = time.perf_counter()
            answer = service.answer(
                QueryRequest(question=question.question, as_of=question.as_of),
                Principal(user_id="development-evaluator", role=role),
            )
            row = {
                "question_id": question.question_id,
                "category": question.category,
                "question": question.question,
                "role": role,
                "as_of": question.as_of,
                "repeat": repeat,
                "expected": question.role_expectations[role].model_dump(),
                "answer": answer.model_dump(mode="json"),
                "context": contexts[-1].model_dump(mode="json") if contexts else None,
                "exchanges": list(exchanges),
                "exchange_count": len(exchanges),
                "duration_seconds": round(time.perf_counter() - start, 6),
                "input_hash": hashlib.sha256(
                    json.dumps(
                        exchanges[-1]["request"] if exchanges else {},
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
                "human_review": {
                    "correct": None,
                    "citations_supported": None,
                    "key_claims_covered": None,
                    "reason": "",
                    "reviewer": None,
                },
            }
            rows.append(row)
            report["summary"] = summarize(rows, kind=kind)
            report["cost_after"] = cost_totals(settings.cost_ledger_path)
            _save(output, report)
            print(
                json.dumps(
                    {
                        "question_id": question.question_id,
                        "role": role,
                        "repeat": repeat,
                        "status": answer.status,
                        "api_calls": len(exchanges),
                        "cost_usd": sum(e["cost"] or 0 for e in exchanges),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if "費用上限" in (answer.reason or ""):
                break
        if execution_fingerprint(retriever.store) != fingerprint:
            report["corpus_changed"] = True
        _save(output, report)
    finally:
        retriever.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["development", "stability"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.kind, args.output)
        print(json.dumps(report["summary"], ensure_ascii=False))
    except Exception:
        # 不列印可能含環境、HTTP或輸入內容的底層例外。
        print('{"error":"evaluation_failed"}', flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
