"""階段7保留題執行器：只用合成fixture；不讀真實保留題、不連網。"""

import hashlib
import json

import pytest

from hr_rag import answer_evaluation, evaluation, holdout
from hr_rag.answer_review import assess
from hr_rag.evaluation_schema import Question

ROOT = evaluation.PROJECT_ROOT


def _question(qid="H90", category="direct", roles=("employee",), behavior="answered"):
    expectation = {
        "expected_behavior": behavior,
        "answer_key": ["合成答案"] if behavior == "answered" else [],
        "required_evidence_groups": (
            [[{"document_id": "C01", "version_id": "v1", "section_id": "section"}]]
            if behavior == "answered"
            else []
        ),
        "forbidden_sources": [],
    }
    return Question.model_validate(
        {
            "question_id": qid,
            "category": category,
            "split": "holdout",
            "question": "合成保留問題",
            "as_of": "2026-10-01",
            "role_expectations": {role: expectation for role in roles},
            "author": "fixture",
            "reviewer": "fixture",
            "reviewed_at": "2026-10-18",
            "review_status": "verified",
        }
    )


@pytest.fixture
def external(tmp_path, monkeypatch):
    path = tmp_path / "private" / "holdout.jsonl"
    path.parent.mkdir()
    path.write_bytes(b"synthetic-holdout\n")
    manifest = tmp_path / "holdout.manifest.json"
    manifest.write_text(
        json.dumps({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(evaluation, "HOLDOUT_MANIFEST_PATH", manifest)
    return path


def test_holdout_file_must_be_external_and_hash_matched(external, tmp_path):
    assert (
        evaluation.verify_holdout_file(external)
        == hashlib.sha256(b"synthetic-holdout\n").hexdigest()
    )
    with pytest.raises(ValueError, match="holdout_must_be_external"):
        evaluation.verify_holdout_file(ROOT / "eval/development.jsonl")
    external.write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="holdout_changed"):
        evaluation.verify_holdout_file(external)


def test_holdout_source_requires_env(monkeypatch, external):
    monkeypatch.delenv("HR_RAG_HOLDOUT_PATH", raising=False)
    with pytest.raises(ValueError, match="holdout_path_not_set"):
        holdout.holdout_source()
    monkeypatch.setenv("HR_RAG_HOLDOUT_PATH", str(external))
    assert holdout.holdout_source() == external.resolve()
    assert holdout.private_dir(external) == external.parent / "stage7"
    assert not holdout.private_dir(external).resolve().is_relative_to(ROOT)


def test_evaluate_holdout_requires_private_labels(policy_store, external, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        evaluation,
        "verify_baseline",
        lambda: {"manifest_sha256": "test", "development_sha256": "fixture"},
    )
    monkeypatch.setattr(evaluation, "validate_evaluation", lambda *a, **k: [])
    monkeypatch.setattr(evaluation, "_read", lambda path: (b"", [_question()]))
    runner = SimpleNamespace(
        store=policy_store, retrieve=lambda *a, **k: [], close=lambda: None
    )
    with pytest.raises(ValueError, match="holdout_labels_required"):
        evaluation.evaluate(
            external, "dense", "full", retriever=runner, split="holdout"
        )
    labels = evaluation.LabelStore(external.parent / "labels.jsonl")
    report = evaluation.evaluate(
        external, "dense", "full", retriever=runner, labels=labels, split="holdout"
    )
    assert report["split"] == "holdout" and report["holdout_sha256"]
    assert report["answerable_count"] == 1


def test_holdout_answer_jobs_and_output_location(external, monkeypatch, tmp_path):
    questions = [
        _question(),
        _question("H91", "permission", ("hr", "employee", "manager")),
    ]
    monkeypatch.setattr(answer_evaluation, "_read", lambda path: (b"", questions))
    jobs = answer_evaluation.build_jobs("holdout", holdout_path=external)
    assert [(q.question_id, role, r) for q, role, r in jobs] == [
        ("H90", "employee", 1),
        ("H91", "hr", 1),
        ("H91", "employee", 1),
        ("H91", "manager", 1),
    ]
    with pytest.raises(ValueError, match="holdout_path_required"):
        answer_evaluation.build_jobs("holdout")
    with pytest.raises(ValueError, match="holdout_output_must_be_external"):
        answer_evaluation.run(
            "holdout", ROOT / ".runtime/x.json", holdout_path=external
        )


def _report(rows):
    return {"kind": "holdout", "rows": rows}


def _row(qid, category, status="answered", role="employee", expected=None):
    claims = [{"text": "原文", "citation_ids": ["p1"]}] if status == "answered" else []
    return {
        "question_id": qid,
        "category": category,
        "role": role,
        "repeat": 1,
        "expected": {"expected_behavior": expected or status, "answer_key": []},
        "answer": {"status": status, "claims": claims, "citations": []},
    }


def _review(report, raw):
    rows = []
    for row in report["rows"]:
        pairs = [
            {"claim_index": i, "citation_id": c}
            for i, claim in enumerate(row["answer"]["claims"])
            for c in claim["citation_ids"]
        ]
        rows.append(
            {
                "question_id": row["question_id"],
                "role": row["role"],
                "repeat": 1,
                "claim_citation_pairs": pairs,
                "correct": True,
                "key_claims_covered": True,
                "citation_reviews": [p | {"supported": True} for p in pairs],
                "reason": "",
            }
        )
    return {
        "schema_version": 1,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "kind": "holdout",
        "reviewer": "使用者",
        "reviewed_at": "2026-10-20T00:00:00Z",
        "complete": True,
        "rows": rows,
    }


def _holdout_rows():
    rows = [_row(f"H{i}", "direct") for i in range(7)] + [_row("H7", "version")]
    rows.append(_row("H8", "insufficient", "insufficient"))
    rows += [
        _row("H9", "permission", role="hr"),
        _row("H9", "permission", "insufficient", role="employee"),
        _row("H9", "permission", "insufficient", role="manager"),
    ]
    return rows


def test_holdout_answer_thresholds_seven_of_eight():
    report = _report(_holdout_rows())
    raw = json.dumps(report).encode()
    review = _review(report, raw)
    result = assess(report, raw, review)
    assert result["answerable"] == {"passed": 8, "total": 8}
    assert result["permission"] == {"passed": 3, "total": 3}
    assert result["passed"] is True
    review["rows"][0]["correct"] = False
    assert assess(report, raw, review)["passed"] is True
    review["rows"][1]["correct"] = False
    assert assess(report, raw, review)["passed"] is False
    review = _review(report, raw)
    review["rows"][10]["correct"] = False  # 權限題employee
    assert assess(report, raw, review)["passed"] is False


def test_clarify_expectation_matches_insufficient_status():
    report = _report([_row("H8", "insufficient", "insufficient", expected="clarify")])
    raw = json.dumps(report).encode()
    assert assess(report, raw, _review(report, raw))["status_mismatches"] == []


def test_import_labels_requires_matching_complete_export(tmp_path):
    items = [
        {
            "review_id": "L001",
            "question_id": "H01",
            "role": "employee",
            "unit": {"content_sha256": "a" * 64, "chunk": {"text": "x"}},
        },
    ]
    items_path = tmp_path / "context-review.json"
    items_path.write_text(json.dumps(items), encoding="utf-8")
    review_hash = hashlib.sha256(items_path.read_bytes()).hexdigest()
    labels_path = tmp_path / "context-labels.jsonl"

    def export(**changes):
        data = {
            "schema_version": 1,
            "review_set_sha256": review_hash,
            "complete": True,
            "labels": [
                {
                    "review_id": "L001",
                    "question_id": "H01",
                    "role": "employee",
                    "content_sha256": "a" * 64,
                    "useful": True,
                    "reason": "有助回答",
                    "reviewer": "使用者",
                }
            ],
        } | changes
        path = tmp_path / "export.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    with pytest.raises(ValueError, match="review_set_mismatch"):
        holdout.import_labels(
            export(review_set_sha256="0" * 64), items_path, labels_path
        )
    with pytest.raises(ValueError, match="labels_incomplete"):
        holdout.import_labels(export(complete=False), items_path, labels_path)
    assert holdout.import_labels(export(), items_path, labels_path) == 1
    store = evaluation.LabelStore(labels_path)
    assert store.labels[("H01", "employee", "a" * 64)] is True
    with pytest.raises(ValueError, match="labels_already_imported"):
        holdout.import_labels(export(), items_path, labels_path)


def _retrieval(top5, context, precision, total=8, version=1):
    return {
        "answerable_count": total,
        "top5_all_hit": top5,
        "context_all_hit": context,
        "mean_context_precision": precision,
        "version_correct": version,
        "version_count": 1 if total == 8 else 3,
        "authorization_errors": 0,
        "execution_errors": 0,
        "pending_labels": 0,
    }


def _assessment(answerable, *, total, insufficient, version, permission, pairs):
    return {
        "answerable": {"passed": answerable, "total": total},
        "insufficient": {"passed": insufficient, "total": insufficient},
        "version": {"passed": version, "total": version},
        "permission": {"passed": permission, "total": permission},
        "citation_support": {"supported": pairs, "total": pairs, "rate": 1.0},
        "key_claims_covered": {"passed": 10, "total": 10},
        "status_mismatches": [],
    }


def test_combined_thirty_question_thresholds():
    dev_r = _retrieval(14, 14, 0.82, total=14, version=3)
    dev_a = _assessment(14, total=14, insufficient=3, version=3, permission=9, pairs=36)
    hold_r = _retrieval(7, 7, 0.85)
    hold_a = _assessment(7, total=8, insufficient=1, version=1, permission=3, pairs=20)
    result = holdout.combine(dev_r, dev_a, hold_r, hold_a)
    assert result["top5"] == {
        "development": 14,
        "holdout": 7,
        "total": 21,
        "denominator": 22,
        "passed": True,
    }
    assert result["answers"]["total"] == 21 and result["permission"]["total"] == 12
    assert result["passed"] is True
    worse = holdout.combine(dev_r, dev_a, _retrieval(6, 7, 0.85), hold_a)
    assert worse["top5"]["passed"] is False and worse["passed"] is False
    low = holdout.combine(dev_r, dev_a, _retrieval(8, 8, 0.79), hold_a)
    assert low["precision"]["passed"] is False
    pending = _retrieval(8, 8, None) | {"pending_labels": 2}
    with pytest.raises(ValueError, match="labels_pending"):
        holdout.combine(dev_r, dev_a, pending, hold_a)
    text = json.dumps(result, ensure_ascii=False)
    assert "合成" not in text


def test_score_writes_aggregates_without_private_text(external, tmp_path, monkeypatch):
    folder = holdout.private_dir(external)
    folder.mkdir()
    rows = _holdout_rows()
    for row in rows:
        row["question"] = "保留題正文不得外洩"
    report = _report(rows)
    raw = json.dumps(report, ensure_ascii=False).encode()
    (folder / "answers-holdout.json").write_bytes(raw)
    (folder / "retrieval-holdout.json").write_text(
        json.dumps(_retrieval(8, 8, 0.9)), encoding="utf-8"
    )
    review = _review(report, raw)
    review["rows"][0]["reason"] = "理由也可能含保留題內容"
    review_path = folder / "review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    frozen = tmp_path / "final.freeze.json"
    frozen.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(holdout, "_check_frozen", lambda: None)
    monkeypatch.setattr(holdout, "FREEZE_PATH", frozen)
    monkeypatch.setattr(holdout, "SUMMARY_PATH", tmp_path / "summary.json")
    summary = holdout.score(external, review_path)
    assert summary["passed"] is True and summary["answers"]["total"] == 22
    assert summary["top5"]["denominator"] == 22
    text = (tmp_path / "summary.json").read_text("utf-8")
    assert "保留題正文" not in text and "理由也可能" not in text
