"""本機Ollama生成候選與開發集自動評估。

候選與正式OpenAI設定共用VerbatimGenerator的選段提示、schema與輸出驗證，
只換端點與模型。評估只用開發集、自動比對狀態與必要證據，不是人工驗收；
正式採用前仍須人工核對與保留集驗證。
"""

import argparse
import json
import os
import re
import time
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from hr_rag.audit import collecting
from hr_rag.contracts import Principal, QueryRequest
from hr_rag.latency import percentile, tokens_per_second
from hr_rag.providers import ProviderError
from hr_rag.settings import PROJECT_ROOT, OllamaSettings
from hr_rag.verbatim import VerbatimGenerator

CANDIDATE_PATH = PROJECT_ROOT / "config/generation.local-candidate.json"
DEVELOPMENT_PATH = PROJECT_ROOT / "eval/development.jsonl"


class LocalVerbatimGenerator(VerbatimGenerator):
    """同一套選段與驗證，只把端點換成本機Ollama。"""

    def _payload(self, question, context):
        payload, input_tokens, evidence_tokens = super()._payload(question, context)
        # error是系統錯誤狀態，回答層一律視為格式不符；本機模型會把「不夠細」
        # 誤選成error，故候選schema只開放三種判斷。token以原schema估算，只會偏多。
        status = payload["text"]["format"]["schema"]["properties"]["status"]
        status["enum"] = [value for value in status["enum"] if value != "error"]
        return payload, input_tokens, evidence_tokens

    def _configured(self):
        # Ollama不驗金鑰也不計費；仍走成本帳本，讓失敗與重試行為與正式路徑一致。
        if getattr(self.settings, "provider", None) != "ollama":
            raise ProviderError("not_configured")
        return "ollama-local", Decimal(1)


def load_local_candidate(path: Path = CANDIDATE_PATH, *, model: str | None = None):
    config = json.loads(Path(path).read_text("utf-8"))
    if config.get("provider") != "ollama" or config.get("status") == "selected":
        raise ValueError("invalid_local_candidate")
    values = dict(config["settings"])
    if model:
        values["model"] = model
    return config, OllamaSettings(**values)


def local_generator(*, model: str | None = None, **kwargs) -> LocalVerbatimGenerator:
    _, settings = load_local_candidate(model=model)
    return LocalVerbatimGenerator(settings, **kwargs)


def score(expectation, answer, context):
    """自動比對：狀態相符、必要證據組都被引用、沒有引用禁用來源。"""
    groups = [
        {(r["document_id"], r["version_id"], r["section_id"]) for r in group}
        for group in expectation["required_evidence_groups"]
    ]
    units = {unit.id: unit for unit in context.units} if context else {}
    cited = [units[cid] for cid in answer.citations if cid in units]
    refs = {(u.document_id, u.version_id, u.section_id) for u in cited}
    covered = sum(bool(group & refs) for group in groups)
    forbidden = sorted(
        {
            u.document_id
            for u in cited
            if u.document_id in expectation.get("forbidden_sources", [])
            or f"{u.document_id}/{u.version_id}"
            in expectation.get("forbidden_sources", [])
        }
    )
    status_ok = answer.status == expectation["expected_behavior"]
    evidence_ok = covered == len(groups)
    return {
        "expected": expectation["expected_behavior"],
        "status": answer.status,
        "status_ok": status_ok,
        "evidence_coverage": covered / len(groups) if groups else None,
        "evidence_ok": evidence_ok,
        "cited": len(answer.citations),
        "forbidden_cited": forbidden,
        "passed": status_ok and evidence_ok and not forbidden,
    }


def _cases(questions):
    for question in questions:
        for role, expectation in question["role_expectations"].items():
            yield question, role, expectation


def _ask(service, question, role):
    request = QueryRequest(
        question=question["question"], as_of=date.fromisoformat(question["as_of"])
    )
    principal = Principal(user_id="local-evaluator-" + role, role=role)
    with collecting() as collector:
        started = time.monotonic()
        answer = service.answer(request, principal)
        total = (time.monotonic() - started) * 1000
    return answer, total, collector


def evaluate(service, questions):
    rows = []
    for question, role, expectation in _cases(questions):
        answer, total, collector = _ask(service, question, role)
        context = collector["contexts"][-1] if collector["contexts"] else None
        stage = collector["notes"].get("stage_ms", {})
        usage = [e.get("usage") or {} for e in collector["exchanges"]]
        output = sum(u.get("output_tokens", 0) for u in usage) if usage else None
        rows.append(
            {
                "question_id": question["question_id"],
                "category": question["category"],
                "role": role,
                "error_code": collector["notes"].get("error_code"),
                "score": score(expectation, answer, context),
                "total_ms": total,
                "retrieve_ms": stage.get("retrieve"),
                "generate_ms": stage.get("generate"),
                "ttft_ms": stage.get("ttft"),
                "input_tokens": (
                    sum(u.get("input_tokens", 0) for u in usage) if usage else None
                ),
                "input_token_delta": next(
                    (e.get("input_token_delta") for e in collector["exchanges"]),
                    None,
                ),
                "output_tokens": output,
                "tokens_per_second": tokens_per_second(
                    output, stage.get("generate"), stage.get("ttft")
                ),
            }
        )
        print(
            json.dumps(
                {
                    "question_id": rows[-1]["question_id"],
                    "role": role,
                    **{k: rows[-1]["score"][k] for k in ("status", "passed")},
                    "error_code": rows[-1]["error_code"],
                    "total_s": round(total / 1000, 2),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return rows


def summarize(rows):
    def spread(name):
        values = [row[name] for row in rows if row[name] is not None]
        return {"p50": percentile(values, 50), "p95": percentile(values, 95)}

    scores = [row["score"] for row in rows]
    answerable = [s for s in scores if s["expected"] == "answered"]
    return {
        "cases": len(rows),
        "passed": sum(s["passed"] for s in scores),
        "status_ok": sum(s["status_ok"] for s in scores),
        "answerable_evidence_ok": sum(
            s["evidence_ok"] and s["status_ok"] for s in answerable
        ),
        "answerable": len(answerable),
        "insufficient_ok": sum(
            s["status_ok"] for s in scores if s["expected"] == "insufficient"
        ),
        "insufficient": sum(s["expected"] == "insufficient" for s in scores),
        "forbidden_citations": sum(bool(s["forbidden_cited"]) for s in scores),
        "errors": dict(Counter(row["error_code"] for row in rows if row["error_code"])),
        **{
            name: spread(name)
            for name in (
                "total_ms",
                "retrieve_ms",
                "generate_ms",
                "ttft_ms",
                "output_tokens",
                "tokens_per_second",
                "input_token_delta",
            )
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", help="以逗號分隔；預設用候選設定的模型")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / ".runtime")
    args = parser.parse_args()
    # 評估事件不混入正式監控視窗。
    os.environ.setdefault(
        "HR_RAG_EVENT_PATH", str(PROJECT_ROOT / ".runtime/local-eval-events.jsonl")
    )
    from hr_rag.answering import AnswerService
    from hr_rag.audit import collect_exchange
    from hr_rag.retrieval import Retriever

    config, default = load_local_candidate()
    models = args.models.split(",") if args.models else [default.model]
    questions = [
        json.loads(line)
        for line in DEVELOPMENT_PATH.read_text("utf-8").splitlines()
        if line.strip()
    ]
    retriever = Retriever()
    try:
        retriever.warmup()
        for model in models:
            generator = local_generator(
                model=model, on_exchange=collect_exchange, stream=True
            )
            service = AnswerService(retriever=retriever, generator=generator)
            # 第一題先跑一次讓Ollama載入模型，不計入結果。
            first, role, _ = next(_cases(questions))
            started = time.monotonic()
            _ask(service, first, role)
            load_ms = (time.monotonic() - started) * 1000
            rows = evaluate(service, questions)
            report = {
                "purpose": "development_auto_check_not_acceptance",
                "model": model,
                "candidate": config,
                "settings": generator.settings.model_dump(
                    mode="json", exclude={"cost_ledger_path"}
                ),
                "model_load_ms": load_ms,
                "summary": summarize(rows),
                "rows": rows,
            }
            name = re.sub(r"[^a-zA-Z0-9._-]", "_", model)
            output = args.output_dir / f"local-eval-{name}.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {"model": model, **report["summary"]}, ensure_ascii=False, indent=2
                ),
                flush=True,
            )
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
