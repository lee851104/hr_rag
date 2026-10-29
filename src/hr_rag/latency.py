"""診斷用量測：k、召回、分段延遲、首字延遲與每秒輸出token。

只讀開發集，不檢查保留集凍結；結果用來比較設定，不是驗收證據。
`--generate` 會實際呼叫 OpenAI 並計費，預設只量檢索（不花費）。
"""

import argparse
import json
import math
import os
import time
from datetime import date
from pathlib import Path

from hr_rag.audit import collecting
from hr_rag.contracts import Principal, QueryRequest
from hr_rag.settings import PROJECT_ROOT

DEVELOPMENT_PATH = PROJECT_ROOT / "eval/development.jsonl"
RECALL_KS = (1, 3, 5)


def recall_at(groups, references, k):
    """前k名找到的必要證據組比例；沒有必要證據的題目回None，不當成滿分。"""
    if not groups:
        return None
    found = set(map(tuple, references[:k]))
    covered = sum(any(tuple(ref) in found for ref in group) for group in groups)
    return covered / len(groups)


def reciprocal_rank(groups, references):
    if not groups:
        return None
    required = {tuple(ref) for group in groups for ref in group}
    for rank, ref in enumerate(references, 1):
        if tuple(ref) in required:
            return 1 / rank
    return 0


def percentile(values, q):
    """nearest-rank，與監控P95同一算法。"""
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(math.ceil(q / 100 * len(ordered)) - 1, 0)]


def tokens_per_second(output_tokens, generate_ms, ttft_ms):
    """扣掉首字前的等待，只看產生輸出的速度；資料不全時不估算。"""
    if output_tokens is None or generate_ms is None or ttft_ms is None:
        return None
    seconds = (generate_ms - ttft_ms) / 1000
    return output_tokens / seconds if seconds > 0 else None


def _spread(values):
    values = [value for value in values if value is not None]
    return {"p50": percentile(values, 50), "p95": percentile(values, 95)}


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def summarize(rows):
    result = {}
    for limit in dict.fromkeys(row["candidate_limit"] for row in rows):
        group = [row for row in rows if row["candidate_limit"] == limit]
        answerable = [row for row in group if row["answerable"]]
        stages = [row["stage_ms"] for row in group]
        summary = {
            "rows": len(group),
            "answerable": len(answerable),
            "recall_at": {
                str(k): _mean(row["recall_at"][str(k)] for row in answerable)
                for k in RECALL_KS
            },
            "all_hit_at_5": sum(row["recall_at"]["5"] == 1 for row in answerable),
            "mrr": _mean(row["reciprocal_rank"] for row in answerable),
            "retrieve_ms": _spread(row["retrieve_ms"] for row in group),
            "embed_ms": _spread(stage.get("embed") for stage in stages),
            "rerank_ms": _spread(stage.get("rerank") for stage in stages),
        }
        answered = [row["generate"] for row in group if "generate" in row]
        if answered:
            summary |= {
                "answered_rows": len(answered),
                **{
                    name: _spread(item[name] for item in answered)
                    for name in (
                        "total_ms",
                        "generate_ms",
                        "ttft_ms",
                        "output_tokens",
                        "tokens_per_second",
                    )
                },
            }
        result[str(limit)] = summary
    return result


def _cases(question):
    for role, expectation in question["role_expectations"].items():
        groups = [
            [
                (ref["document_id"], ref["version_id"], ref["section_id"])
                for ref in group
            ]
            for group in expectation["required_evidence_groups"]
        ]
        yield role, expectation["expected_behavior"], groups


def measure_retrieval(retriever, questions, candidate_limits, *, mode="rerank"):
    original = retriever.candidate_limit
    rows = []
    try:
        for limit in candidate_limits:
            retriever.candidate_limit = limit
            for question in questions:
                for role, behavior, groups in _cases(question):
                    principal = Principal(user_id="latency-" + role, role=role)
                    with collecting() as collector:
                        started = time.monotonic()
                        evidence = retriever.retrieve(
                            question["question"],
                            principal,
                            date.fromisoformat(question["as_of"]),
                            mode,
                        )
                        elapsed = (time.monotonic() - started) * 1000
                    refs = [
                        (e.chunk.document_id, e.chunk.version_id, e.chunk.section_id)
                        for e in evidence
                    ]
                    rows.append(
                        {
                            "candidate_limit": limit,
                            "question_id": question["question_id"],
                            "role": role,
                            "expected_behavior": behavior,
                            "answerable": bool(groups),
                            "recall_at": {
                                str(k): recall_at(groups, refs, k) for k in RECALL_KS
                            },
                            "reciprocal_rank": reciprocal_rank(groups, refs),
                            "retrieve_ms": elapsed,
                            "stage_ms": collector["notes"].get("stage_ms", {}),
                        }
                    )
    finally:
        retriever.candidate_limit = original
    return rows


def measure_answers(service, questions, rows):
    """以正式AnswerService逐題回答一次，補上生成分段；需要API金鑰並計費。"""
    by_case = {(row["question_id"], row["role"]): row for row in rows}
    for question in questions:
        for role, _, _ in _cases(question):
            principal = Principal(user_id="latency-" + role, role=role)
            request = QueryRequest(
                question=question["question"],
                as_of=date.fromisoformat(question["as_of"]),
            )
            with collecting() as collector:
                started = time.monotonic()
                answer = service.answer(request, principal)
                total = (time.monotonic() - started) * 1000
            stage = collector["notes"].get("stage_ms", {})
            usage = [e.get("usage") or {} for e in collector["exchanges"]]
            output = sum(u.get("output_tokens", 0) for u in usage) if usage else None
            by_case[(question["question_id"], role)]["generate"] = {
                "status": answer.status,
                "total_ms": total,
                "generate_ms": stage.get("generate"),
                "ttft_ms": stage.get("ttft"),
                "input_tokens": (
                    sum(u.get("input_tokens", 0) for u in usage) if usage else None
                ),
                "output_tokens": output,
                "tokens_per_second": tokens_per_second(
                    output, stage.get("generate"), stage.get("ttft")
                ),
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-limits", default="20,12,10")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="以第一個k實際生成（OpenAI計費），量首字延遲與每秒輸出token",
    )
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / ".runtime/latency.json"
    )
    args = parser.parse_args()
    try:
        limits = [int(value) for value in args.candidate_limits.split(",")]
    except ValueError:
        limits = []
    if not limits or any(value < 1 for value in limits):
        raise SystemExit("candidate-limits 必須是以逗號分隔的正整數")
    # 量測產生的事件不混入正式監控視窗。
    os.environ.setdefault(
        "HR_RAG_EVENT_PATH", str(PROJECT_ROOT / ".runtime/latency-events.jsonl")
    )
    from hr_rag.retrieval import Retriever

    questions = [
        json.loads(line)
        for line in DEVELOPMENT_PATH.read_text("utf-8").splitlines()
        if line.strip()
    ]
    runner = Retriever()
    try:
        started = time.monotonic()
        runner.warmup()
        warmup_ms = (time.monotonic() - started) * 1000
        rows = measure_retrieval(runner, questions, limits)
        if args.generate:
            from hr_rag.answering import AnswerService
            from hr_rag.audit import collect_exchange
            from hr_rag.generation import selected_generator

            runner.candidate_limit = limits[0]
            service = AnswerService(
                retriever=runner,
                generator=selected_generator(on_exchange=collect_exchange, stream=True),
            )
            measure_answers(
                service,
                questions,
                [row for row in rows if row["candidate_limit"] == limits[0]],
            )
    finally:
        runner.close()
    report = {
        "purpose": "diagnostic_not_acceptance",
        "split": "development",
        "warmup_ms": warmup_ms,
        "summary": summarize(rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
