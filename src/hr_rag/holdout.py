"""階段7保留題評估：使用者設定HR_RAG_HOLDOUT_PATH後執行。

保留題結果、核對頁與上下文標註只存在保留題同層的 stage7 資料夾（專案外）；
主控台與專案內報告只含彙總數字與題號，不含題目、答案或證據正文。
執行前核對 eval/final.freeze.json 與語料指紋，看過結果後不得調參。
"""

import argparse
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

from hr_rag.evaluation import PROJECT_ROOT, LabelStore, verify_holdout_file
from hr_rag.freeze import FREEZE_PATH, verify_final_freeze

SUMMARY_PATH = PROJECT_ROOT / "reports/stage7-holdout-summary.json"
DEV_RETRIEVAL = PROJECT_ROOT / "reports/retrieval-stage5-verbatim-v3.json"
DEV_REVIEW = PROJECT_ROOT / "reports/stage5-human-review-development-v3.json"
LABEL_TITLE = "第七階段保留題上下文有用性核對"
LABEL_NOTE = (
    "這是保留題的最終上下文，只存在專案外私人資料夾；請勿複製到專案或交給實作代理。"
)


def holdout_source() -> Path:
    raw = os.environ.get("HR_RAG_HOLDOUT_PATH", "").strip()
    if not raw:
        raise ValueError("holdout_path_not_set")
    path = Path(raw).resolve()
    verify_holdout_file(path)
    return path


def private_dir(source) -> Path:
    return Path(source).parent / "stage7"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save(path: Path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _check_frozen():
    """設定、程式與語料皆須與7.1凍結一致。"""
    from hr_rag.evaluation import execution_fingerprint
    from hr_rag.storage import CorpusStore

    verify_final_freeze()
    record = json.loads(FREEZE_PATH.read_text("utf-8"))
    if (
        execution_fingerprint(CorpusStore())
        != record["corpus"]["execution_fingerprint"]
    ):
        raise ValueError("final_freeze_changed:corpus")


RETRIEVAL_KEYS = (
    "answerable_count",
    "top5_all_hit",
    "context_all_hit",
    "mean_context_precision",
    "version_correct",
    "version_count",
    "authorization_errors",
    "execution_errors",
    "pending_labels",
)


def retrieve(source: Path) -> dict:
    """本機檢索與組裝（不呼叫API）；有新上下文單位時產生私人標註頁。"""
    from hr_rag.context import ContextSettings
    from hr_rag.evaluation import evaluate
    from hr_rag.review_page import render_review

    _check_frozen()
    folder = private_dir(source)
    folder.mkdir(parents=True, exist_ok=True)
    selected = json.loads(
        (PROJECT_ROOT / "config/retrieval.selected.json").read_text("utf-8")
    )
    config = ContextSettings(**selected["context_settings"])
    labels = LabelStore(folder / "context-labels.jsonl")
    report = evaluate(
        source,
        config.mode,
        "full",
        labels=labels,
        context_config=config,
        split="holdout",
    )
    _save(folder / "retrieval-holdout.json", report)
    pending = {}
    for row in report["rows"]:
        for unit in row["units"]:
            key = (row["question_id"], row["role"], unit["content_sha256"])
            if unit["human_useful"] is None and key not in pending:
                pending[key] = {
                    "question": row["question"],
                    "question_id": row["question_id"],
                    "role": row["role"],
                    "as_of": row["as_of"],
                    "unit": unit,
                    "modes": [report["mode"]],
                }
    if pending:
        items = [
            {"review_id": f"L{number:03}", **item}
            for number, (_, item) in enumerate(sorted(pending.items()), 1)
        ]
        items_path = folder / "context-review.json"
        items_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (folder / "context-review.html").write_text(
            render_review(items, _sha(items_path), title=LABEL_TITLE, note=LABEL_NOTE),
            encoding="utf-8",
        )
    return {
        "role_executions": len(report["rows"]),
        **{k: report[k] for k in RETRIEVAL_KEYS},
        "label_page": str(folder / "context-review.html") if pending else None,
    }


def import_labels(export_path: Path, items_path: Path, labels_path: Path) -> int:
    """匯入使用者在私人標註頁匯出的完整判定；不覆寫、不重複。"""
    items_raw = Path(items_path).read_bytes()
    items = json.loads(items_raw)
    data = json.loads(Path(export_path).read_text("utf-8"))
    if data.get("review_set_sha256") != hashlib.sha256(items_raw).hexdigest():
        raise ValueError("review_set_mismatch")
    if data.get("complete") is not True:
        raise ValueError("labels_incomplete")
    labels = data["labels"]
    expected = {
        (i["review_id"], i["question_id"], i["role"], i["unit"]["content_sha256"])
        for i in items
    }
    got = {
        (row["review_id"], row["question_id"], row["role"], row["content_sha256"])
        for row in labels
    }
    if got != expected or len(labels) != len(items):
        raise ValueError("review_set_mismatch")
    if any(
        type(row["useful"]) is not bool
        or not str(row.get("reviewer") or "").strip()
        or not str(row.get("reason") or "").strip()
        for row in labels
    ):
        raise ValueError("labels_incomplete")
    store = LabelStore(labels_path)
    if any(
        (row["question_id"], row["role"], row["content_sha256"]) in store.labels
        for row in labels
    ):
        raise ValueError("labels_already_imported")
    Path(labels_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(labels_path).open("a", encoding="utf-8") as stream:
        for row in labels:
            stream.write(
                json.dumps(
                    {
                        "question_id": row["question_id"],
                        "role": row["role"],
                        "content_sha256": row["content_sha256"],
                        "useful": row["useful"],
                        "reviewer": row["reviewer"].strip(),
                        "reason": row["reason"].strip(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return len(labels)


def answer(source: Path) -> dict:
    """真實API生成（每個角色執行1次，不重跑）；輸出私人核對頁。"""
    from hr_rag.answer_evaluation import run
    from hr_rag.answer_review import write

    _check_frozen()
    folder = private_dir(source)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "answers-holdout.json"
    report = run("holdout", output, holdout_path=source)
    page = write(output)
    before = sum(Decimal(v) for v in report["cost_before"].values())
    after = sum(Decimal(v) for v in report["cost_after"].values())
    return {
        **report["summary"],
        "added_usd": str(after - before),
        "review_page": str(page),
    }


def _pair(dev, dev_total, hold, hold_total):
    return {
        "development": dev,
        "holdout": hold,
        "total": dev + hold,
        "denominator": dev_total + hold_total,
        # 7.2：全體可回答22題至少20、保留8題至少7。
        "passed": dev + hold >= 20 and hold >= 7,
    }


def _all(dev, hold):
    total = dev["total"] + hold["total"]
    passed = dev["passed"] + hold["passed"]
    return {
        "development": dev["passed"],
        "holdout": hold["passed"],
        "total": passed,
        "denominator": total,
        "passed": passed == total,
    }


def combine(dev_retrieval, dev_answers, hold_retrieval, hold_answers) -> dict:
    """合併固定設定下的30題；只輸出數字。"""
    if (
        hold_retrieval["pending_labels"]
        or hold_retrieval["mean_context_precision"] is None
    ):
        raise ValueError("labels_pending")
    dev_n = dev_retrieval["answerable_count"]
    hold_n = hold_retrieval["answerable_count"]
    support = {
        "supported": dev_answers["citation_support"]["supported"]
        + hold_answers["citation_support"]["supported"],
        "total": dev_answers["citation_support"]["total"]
        + hold_answers["citation_support"]["total"],
    }
    support["rate"] = (
        support["supported"] / support["total"] if support["total"] else None
    )
    support["passed"] = support["rate"] is not None and support["rate"] >= 0.95
    covered = {
        "passed": dev_answers["key_claims_covered"]["passed"]
        + hold_answers["key_claims_covered"]["passed"],
        "total": dev_answers["key_claims_covered"]["total"]
        + hold_answers["key_claims_covered"]["total"],
    }
    covered["ok"] = covered["passed"] == covered["total"]
    result = {
        "top5": _pair(
            dev_retrieval["top5_all_hit"], dev_n, hold_retrieval["top5_all_hit"], hold_n
        ),
        "context": _pair(
            dev_retrieval["context_all_hit"],
            dev_n,
            hold_retrieval["context_all_hit"],
            hold_n,
        ),
        "answers": _pair(
            dev_answers["answerable"]["passed"],
            dev_answers["answerable"]["total"],
            hold_answers["answerable"]["passed"],
            hold_answers["answerable"]["total"],
        ),
        "precision": {
            "development": dev_retrieval["mean_context_precision"],
            "holdout": hold_retrieval["mean_context_precision"],
            "passed": dev_retrieval["mean_context_precision"] >= 0.8
            and hold_retrieval["mean_context_precision"] >= 0.8,
        },
        "version": _all(dev_answers["version"], hold_answers["version"]),
        "insufficient": _all(dev_answers["insufficient"], hold_answers["insufficient"]),
        "permission": _all(dev_answers["permission"], hold_answers["permission"]),
        "citation_support": support,
        "key_claims_covered": covered,
        "authorization_errors": dev_retrieval["authorization_errors"]
        + hold_retrieval["authorization_errors"],
        "execution_errors": {
            "development": dev_retrieval["execution_errors"],
            "holdout": hold_retrieval["execution_errors"],
        },
        "holdout_status_mismatches": len(hold_answers["status_mismatches"]),
    }
    result["passed"] = (
        all(
            result[name]["passed"]
            for name in (
                "top5",
                "context",
                "answers",
                "precision",
                "version",
                "insufficient",
                "permission",
                "citation_support",
            )
        )
        and covered["ok"]
        and result["authorization_errors"] == 0
    )
    return result


def score(source: Path, review_path: Path) -> dict:
    from hr_rag.answer_review import assess

    _check_frozen()
    folder = private_dir(source)
    retrieval = json.loads((folder / "retrieval-holdout.json").read_text("utf-8"))
    answers_path = folder / "answers-holdout.json"
    raw = answers_path.read_bytes()
    review_raw = Path(review_path).read_bytes()
    holdout_answers = assess(json.loads(raw), raw, json.loads(review_raw))
    dev_runs = json.loads(DEV_RETRIEVAL.read_text("utf-8"))["runs"]
    dev_answers = json.loads(DEV_REVIEW.read_text("utf-8"))
    # 階段5彙總未存分母；開發可回答題數取人工核對的14題。
    dev_retrieval = {
        "answerable_count": dev_answers["answerable"]["total"],
        **next(run for run in dev_runs if run["mode"] == "rerank"),
    }
    result = combine(dev_retrieval, dev_answers, retrieval, holdout_answers)
    summary = {
        "split": "development+holdout",
        "holdout_sha256": verify_holdout_file(source),
        "final_freeze_sha256": _sha(FREEZE_PATH),
        "private_results_sha256": {
            "retrieval": _sha(folder / "retrieval-holdout.json"),
            "answers": _sha(answers_path),
            "review": hashlib.sha256(review_raw).hexdigest(),
        },
        "holdout_reviewer": holdout_answers["reviewer"],
        "holdout_reviewed_at": holdout_answers["reviewed_at"],
        # 只列題號與角色，不含題目、答案、理由或證據。
        "holdout_marked_incorrect": holdout_answers["marked_incorrect"],
        "holdout_unsupported_citations": len(holdout_answers["unsupported_citations"]),
        **result,
    }
    _save(SUMMARY_PATH, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("retrieve")
    labels = commands.add_parser("import-labels")
    labels.add_argument("--export", type=Path, required=True)
    commands.add_parser("answer")
    scored = commands.add_parser("score")
    scored.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = holdout_source()
        folder = private_dir(source)
        if args.command == "retrieve":
            result = retrieve(source)
        elif args.command == "import-labels":
            result = {
                "imported": import_labels(
                    args.export,
                    folder / "context-review.json",
                    folder / "context-labels.jsonl",
                )
            }
        elif args.command == "answer":
            result = answer(source)
        else:
            result = score(source, args.review)
    except ValueError as error:
        # 錯誤碼皆為固定字串；不印例外細節以免帶出內容。
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from None
    except Exception:
        print('{"error": "holdout_failed"}')
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
