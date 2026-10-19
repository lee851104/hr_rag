"""檢索評估：開發集比較；保留題只在階段7由使用者設定路徑後經hash核對執行。"""

import argparse
import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path

from hr_rag.context import ContextSettings, assemble_context
from hr_rag.contracts import Principal
from hr_rag.corpus.manifest import validate_manifest
from hr_rag.evaluation_schema import _read, validate_evaluation
from hr_rag.generation import load_selected_generation
from hr_rag.policy import eligible_chunks
from hr_rag.providers import ProviderError
from hr_rag.query import QueryError, normalize_query, synonyms_hash
from hr_rag.retrieval import MODES, Retriever
from hr_rag.settings import PROJECT_ROOT
from hr_rag.verbatim import VerbatimGenerator, build_verbatim_payload

DEVELOPMENT_PATH = PROJECT_ROOT / "eval/development.jsonl"
HOLDOUT_MANIFEST_PATH = PROJECT_ROOT / "eval/holdout.manifest.json"


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def unit_hash(text):
    return sha256_bytes(text.encode("utf-8"))


def forbidden_source(document_id, version_id, sources):
    return document_id in sources or f"{document_id}/{version_id}" in sources


def coverage(groups, references):
    references = set(tuple(r) for r in references)
    covered = sum(any(tuple(ref) in references for ref in group) for group in groups)
    total = len(groups)
    return {
        "covered": covered,
        "total": total,
        "coverage": covered / total if total else None,
        "all_hit": covered == total if total else None,
    }


def precision(labels, *, error=False):
    if error or not labels:
        return 0.0
    if any(label is None for label in labels):
        return None
    return sum(label is True for label in labels) / len(labels)


class LabelStore:
    def __init__(self, path=None, *, supplemental_path=None):
        use_default = path is None
        self.path = Path(path or PROJECT_ROOT / "eval/labels.jsonl")
        self.labels = {}
        raw = self.path.read_bytes() if self.path.exists() else b""
        self.sha256 = sha256_bytes(raw)
        if self.path.exists():
            for line in raw.decode("utf-8").splitlines():
                row = json.loads(line)
                if (
                    type(row["useful"]) is not bool
                    or not row["reviewer"]
                    or not row["reason"]
                ):
                    raise ValueError("invalid_human_label")
                self.labels[
                    (row["question_id"], row["role"], row["content_sha256"])
                ] = row["useful"]

        supplemental = (
            Path(supplemental_path)
            if supplemental_path
            else (
                PROJECT_ROOT / "eval/labels.supplemental.jsonl" if use_default else None
            )
        )
        self.supplemental_sha256 = None
        if supplemental and supplemental.exists():
            extra = supplemental.read_bytes()
            self.supplemental_sha256 = sha256_bytes(extra)
            for line in extra.decode("utf-8").splitlines():
                row = json.loads(line)
                key = (row["question_id"], row["role"], row["content_sha256"])
                if key in self.labels:
                    raise ValueError("supplemental_label_collision")
                if (
                    type(row["useful"]) is not bool
                    or not row["reviewer"]
                    or not row["reason"]
                ):
                    raise ValueError("invalid_human_label")
                self.labels[key] = row["useful"]

    def lookup(self, question_id, role, text):
        return self.labels.get((question_id, role, unit_hash(text)))

    def record(self, question_id, role, text, useful, *, reviewer, reason):
        if type(useful) is not bool or not reviewer.strip() or not reason.strip():
            raise ValueError("human_label_requires_reviewer_reason")
        row = {
            "question_id": question_id,
            "role": role,
            "content_sha256": unit_hash(text),
            "useful": useful,
            "reviewer": reviewer,
            "reason": reason,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.labels[(question_id, role, row["content_sha256"])] = useful
        self.sha256 = sha256_bytes(self.path.read_bytes())


def execution_fingerprint(store):
    """固定索引、ACL、日期與撤回狀態；撤回不一定改變generation_id。"""
    with store.connect() as db:
        db.execute("BEGIN")
        active = store.active(db)
        if active is None:
            raise ValueError("missing_corpus")
        state = {"active": dict(active)}
        for table, columns, order in [
            ("units", "id,chunk_json", "id"),
            (
                "documents",
                "document_id,version_id,record_json",
                "document_id,version_id",
            ),
        ]:
            state[table] = [
                tuple(row)
                for row in db.execute(
                    f"SELECT {columns} FROM {table} "
                    f"WHERE generation_id=? ORDER BY {order}",
                    (active["id"],),
                )
            ]
        state["withdrawals"] = [
            tuple(row)
            for row in db.execute(
                "SELECT document_id,version_id FROM withdrawals "
                "ORDER BY document_id,version_id"
            )
        ]
    return sha256_bytes(json.dumps(state, sort_keys=True).encode("utf-8"))


def validate_comparison(runs):
    keys = (
        "execution_fingerprint",
        "manifest_sha256",
        "development_sha256",
        "models_sha256",
        "prompt_sha256",
        "synonyms_sha256",
        "labels_sha256",
        "supplemental_labels_sha256",
    )
    if runs and any(any(run.get(k) != runs[0].get(k) for k in keys) for run in runs):
        raise ValueError("comparison_inputs_changed")


def verify_baseline():
    freeze = json.loads((PROJECT_ROOT / "eval/baseline.freeze.json").read_text("utf-8"))
    summary = json.loads(
        (PROJECT_ROOT / "eval/holdout.manifest.json").read_text("utf-8")
    )
    if (
        freeze["status"] != "frozen"
        or summary["sha256"] != freeze["holdout_sha256"]
        or summary["question_count"] != 10
        or summary["reviewed_count"] != 10
    ):
        raise ValueError("baseline_not_frozen")
    for relative, key in [
        ("data/manifest.json", "manifest_sha256"),
        ("eval/development.jsonl", "development_sha256"),
    ]:
        if sha256_bytes((PROJECT_ROOT / relative).read_bytes()) != freeze[key]:
            raise ValueError("baseline_changed_revalidation_required")
    if validate_manifest(PROJECT_ROOT / "data/manifest.json"):
        raise ValueError("sources_changed_revalidation_required")
    # 公開版不寫死使用者目錄：HR_RAG_HOLDOUT_PATH優先，否則展開 %LOCALAPPDATA% 等。
    location = os.environ.get("HR_RAG_HOLDOUT_PATH") or freeze["holdout_path"]
    external = Path(os.path.expandvars(location)).resolve()
    if external.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("holdout_must_be_external")
    with external.open("rb") as file:
        actual_hash = hashlib.file_digest(file, "sha256").hexdigest()
    if actual_hash != freeze["holdout_sha256"]:
        raise ValueError("holdout_changed_revalidation_required")
    return freeze


def verify_holdout_file(path) -> str:
    """只核對位置與SHA256；不解析、不輸出內容。"""
    path = Path(path).resolve()
    if path.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("holdout_must_be_external")
    expected = json.loads(HOLDOUT_MANIFEST_PATH.read_text("utf-8"))["sha256"]
    with path.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("holdout_changed_revalidation_required")
    return actual


def _reference(chunk):
    return (chunk.document_id, chunk.version_id, chunk.section_id)


def evaluate(
    cases_path: Path,
    mode: str,
    corpus: str,
    *,
    retriever=None,
    labels=None,
    normalize=True,
    context_config=None,
    split="development",
) -> dict:
    if split == "development":
        if Path(cases_path).resolve() != DEVELOPMENT_PATH.resolve():
            raise ValueError("development_only_path")
        split_sha256 = None
    elif split == "holdout":
        # 保留題標註必須明確指向專案外檔案，不與開發標註混用。
        if labels is None:
            raise ValueError("holdout_labels_required")
        split_sha256 = verify_holdout_file(cases_path)
    else:
        raise ValueError("invalid_split")
    freeze = verify_baseline()
    if mode not in MODES or corpus not in {"full", "official"}:
        raise ValueError("invalid_evaluation_settings")
    if validate_evaluation(
        cases_path,
        split=split,
        manifest_path=PROJECT_ROOT / "data/manifest.json",
    ):
        raise ValueError(f"invalid_{split}_set")
    _, questions = _read(cases_path)
    runner = retriever or Retriever()
    labels = labels or LabelStore()
    config = context_config or ContextSettings(
        mode=mode, min_relevance=0 if mode == "rerank" else 0.75
    )
    if config.mode != mode:
        raise ValueError("context_mode_mismatch")
    # 與正式回答相同的生成設定及payload，確保組裝預算一致。
    _, generation = load_selected_generation()
    fingerprint = execution_fingerprint(runner.store)
    initial = runner.store.snapshot()
    if initial is None:
        raise ValueError("missing_corpus")
    with runner.store.connect() as db:
        if runner.store.active(db)["manifest_hash"] != freeze["manifest_sha256"]:
            raise ValueError("active_manifest_mismatch")
    rows = []
    try:
        for question in questions:
            for role, expectation in question.role_expectations.items():
                principal = Principal(user_id="evaluation-" + role, role=role)
                selected_date = date.fromisoformat(question.as_of)
                groups = [
                    [tuple(ref.model_dump().values()) for ref in group]
                    for group in expectation.required_evidence_groups
                ]
                row = {
                    "question_id": question.question_id,
                    "category": question.category,
                    "question": question.question,
                    "prepared_query": normalize_query(question.question)
                    if normalize
                    else question.question,
                    "role": role,
                    "as_of": question.as_of,
                    "expected_behavior": expectation.expected_behavior,
                    "required_evidence_groups": groups,
                    "status": "ok",
                    "top5": [],
                    "units": [],
                    "dropped_reasons": [],
                    "authorization_errors": 0,
                    "error": None,
                    "top5_coverage": coverage(groups, []),
                }
                started = time.perf_counter()
                try:
                    found = runner.retrieve(
                        question.question,
                        principal,
                        selected_date,
                        mode,
                        normalize=normalize,
                        corpus=corpus,
                    )
                    allowed = {
                        c.id
                        for c in eligible_chunks(
                            principal, selected_date, store=runner.store
                        )
                    }
                    row["authorization_errors"] = sum(
                        e.chunk.id not in allowed for e in found
                    ) + sum(
                        forbidden_source(
                            c.document_id, c.version_id, expectation.forbidden_sources
                        )
                        for c in [e.chunk for e in found]
                    )
                    row["top5"] = [
                        {"chunk": e.chunk.model_dump(mode="json"), "score": e.score}
                        for e in found
                    ]
                    row["top5_coverage"] = coverage(
                        groups, [_reference(e.chunk) for e in found]
                    )
                    assembled = assemble_context(
                        found,
                        principal,
                        selected_date,
                        question.question,
                        store=runner.store,
                        config=config,
                        settings=generation,
                        payload_builder=lambda q, c: build_verbatim_payload(
                            q, c, generation
                        ),
                    )
                    row["authorization_errors"] += sum(
                        forbidden_source(
                            c.document_id, c.version_id, expectation.forbidden_sources
                        )
                        for c in assembled.units
                    )
                    row["units"] = [
                        {
                            "chunk": unit.model_dump(mode="json"),
                            "content_sha256": unit_hash(unit.text),
                            "citations": assembled.citation_map[unit.id],
                            "human_useful": labels.lookup(
                                question.question_id, role, unit.text
                            ),
                        }
                        for unit in assembled.units
                    ]
                    row["context_coverage"] = coverage(
                        groups, [_reference(unit) for unit in assembled.units]
                    )
                    row["context_precision"] = precision(
                        [u["human_useful"] for u in row["units"]]
                    )
                    row["input_tokens"] = assembled.token_count
                    row["dropped_reasons"] = list(assembled.dropped_reasons)
                    row["context_config_hash"] = assembled.config_hash
                except (ProviderError, QueryError, ValueError) as error:
                    row.update(
                        status="error",
                        error=str(error)
                        if isinstance(error, (ProviderError, QueryError))
                        else "evaluation_failed",
                        context_coverage=coverage(groups, []),
                        context_precision=0.0,
                    )
                row["duration_seconds"] = round(time.perf_counter() - started, 6)
                rows.append(row)
        final = runner.store.snapshot()
        if (
            final is None
            or final.generation_id != initial.generation_id
            or execution_fingerprint(runner.store) != fingerprint
        ):
            raise ValueError("corpus_changed_during_evaluation")
    finally:
        if retriever is None:
            runner.close()
    answerable = [
        row
        for row in rows
        if row["category"] in {"direct", "paraphrase_cross", "version"}
    ]
    values = [row["context_precision"] for row in answerable]
    versions = [row for row in rows if row["category"] == "version"]
    return {
        "split": split,
        "mode": mode,
        "corpus": corpus,
        "normalize": normalize,
        "generation_id": initial.generation_id,
        "execution_fingerprint": fingerprint,
        "labels_sha256": labels.sha256,
        "supplemental_labels_sha256": labels.supplemental_sha256,
        "manifest_sha256": freeze["manifest_sha256"],
        "development_sha256": freeze["development_sha256"],
        "holdout_sha256": split_sha256,
        "models_sha256": sha256_bytes(
            (PROJECT_ROOT / "config/models.lock.json").read_bytes()
        ),
        "prompt_sha256": unit_hash(VerbatimGenerator.SYSTEM),
        "synonyms_sha256": synonyms_hash(),
        "context_settings": asdict(config),
        "answerable_count": len(answerable),
        "top5_all_hit": sum(
            row["top5_coverage"]["all_hit"] is True for row in answerable
        ),
        "context_all_hit": sum(
            row["context_coverage"]["all_hit"] is True for row in answerable
        ),
        "mean_context_precision": None
        if any(v is None for v in values)
        else sum(values) / len(values)
        if values
        else 0.0,
        "version_correct": sum(
            row["top5_coverage"]["all_hit"] is True and row["authorization_errors"] == 0
            for row in versions
        ),
        "version_count": len(versions),
        "authorization_errors": sum(row["authorization_errors"] for row in rows),
        "execution_errors": sum(row["status"] == "error" for row in rows),
        "pending_labels": sum(
            u["human_useful"] is None for row in rows for u in row["units"]
        ),
        "api_calls": 0,
        "rows": rows,
    }


def write_review(runs, output):
    unique = {}
    for run in runs:
        for row in run["rows"]:
            for unit in row["units"]:
                if unit["human_useful"] is not None:
                    continue
                key = (row["question_id"], row["role"], unit["content_sha256"])
                if key not in unique:
                    unique[key] = {
                        "question": row["question"],
                        "question_id": row["question_id"],
                        "role": row["role"],
                        "as_of": row["as_of"],
                        "unit": unit,
                        "modes": [],
                    }
                if run["mode"] not in unique[key]["modes"]:
                    unique[key]["modes"].append(run["mode"])
    from hr_rag.review_page import render_review

    items = [
        {"review_id": f"L{number:03}", **item}
        for number, (_, item) in enumerate(sorted(unique.items()), 1)
    ]
    serialized = json.dumps(items, ensure_ascii=False, indent=2) + "\n"
    Path(output).with_suffix(".json").write_text(serialized, encoding="utf-8")
    source_hash = sha256_bytes(Path(output).with_suffix(".json").read_bytes())
    Path(output).write_text(
        render_review(items, source_hash),
        encoding="utf-8",
    )
    return len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development"], required=True)
    parser.add_argument("--mode", choices=[*MODES, "all"], required=True)
    parser.add_argument("--corpus", choices=["full", "official"], required=True)
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--context-max-units", type=int, default=3)
    parser.add_argument("--min-relevance", type=float)
    parser.add_argument("--leave-scope-filter", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports/retrieval-comparison.json",
    )
    args = parser.parse_args()
    verify_baseline()
    runner = Retriever()
    runs = []
    try:
        for mode in MODES if args.mode == "all" else [args.mode]:
            result = evaluate(
                DEVELOPMENT_PATH,
                mode,
                args.corpus,
                retriever=runner,
                normalize=not args.no_normalize,
                context_config=ContextSettings(
                    mode,
                    args.context_max_units,
                    args.min_relevance
                    if args.min_relevance is not None
                    else (0 if mode == "rerank" else 0.75),
                    leave_scope_filter=args.leave_scope_filter,
                ),
            )
            runs.append(result)
            validate_comparison(runs)
            print(
                json.dumps(
                    {k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False
                ),
                flush=True,
            )
    finally:
        runner.close()
    args.output.write_text(
        json.dumps({"runs": runs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    count = write_review(runs, args.output.with_name(args.output.stem + "-review.html"))
    print(
        json.dumps(
            {"unique_pending_labels": count, "output": str(args.output)},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
