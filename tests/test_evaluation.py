import json

import pytest

from hr_rag.evaluation import LabelStore, coverage, forbidden_source, precision


def test_required_groups_alternatives_and_zero_denominator():
    groups = [[("O01", "v1", "38"), ("O02", "v1", "24")], [("C01", "v2", "apply")]]
    assert coverage(groups, [("O02", "v1", "24")]) == {
        "covered": 1,
        "total": 2,
        "coverage": 0.5,
        "all_hit": False,
    }
    assert coverage(groups, [("O02", "v1", "24"), ("C01", "v2", "apply")])["all_hit"]
    assert coverage([], []) == {
        "covered": 0,
        "total": 0,
        "coverage": None,
        "all_hit": None,
    }


def test_document_and_version_forbidden_sources():
    assert forbidden_source("C01", "v1", ["C01/v1"])
    assert not forbidden_source("C01", "v2", ["C01/v1"])
    assert forbidden_source("C01", "v2", ["C01"])


def test_labels_reuse_by_question_role_content_hash(tmp_path):
    path = tmp_path / "labels.jsonl"
    labels = LabelStore(path)
    assert labels.lookup("D01", "employee", "內容") is None
    labels.record(
        "D01", "employee", "內容", True, reviewer="測試人工", reason="合成測試"
    )
    assert LabelStore(path).lookup("D01", "employee", "內容") is True
    assert labels.lookup("D01", "hr", "內容") is None
    assert labels.lookup("D02", "employee", "內容") is None
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert "內容" not in rows[0].values()


def test_precision_errors_empty_missing_and_merged_sources():
    assert precision([True, True, False, False, False]) == 0.4
    assert precision([]) == 0
    assert precision([True], error=True) == 0
    assert precision([True, None]) is None
    assert precision([True]) == 1  # 一個合併單位的多來源映射不增加分母


def test_holdout_path_rejected_without_opening_it(tmp_path):
    import pytest

    from hr_rag.evaluation import evaluate

    with pytest.raises(ValueError, match="development_only_path"):
        evaluate(tmp_path / "holdout.jsonl", "dense", "full")


@pytest.fixture
def eval_case(monkeypatch):
    from hr_rag import evaluation as module
    from hr_rag.evaluation_schema import Question

    question = Question.model_validate(
        {
            "question_id": "fixture",
            "category": "direct",
            "split": "development",
            "question": "合成問題",
            "as_of": "2026-10-01",
            "role_expectations": {
                "employee": {
                    "expected_behavior": "answered",
                    "answer_key": ["合成答案"],
                    "required_evidence_groups": [
                        [
                            {
                                "document_id": "C01",
                                "version_id": "v1",
                                "section_id": "section",
                            }
                        ]
                    ],
                    "forbidden_sources": [],
                }
            },
            "author": "fixture",
            "reviewer": "fixture",
            "reviewed_at": "2026-10-18",
            "review_status": "verified",
        }
    )
    monkeypatch.setattr(
        module,
        "verify_baseline",
        lambda: {"manifest_sha256": "test", "development_sha256": "fixture"},
    )
    monkeypatch.setattr(module, "validate_evaluation", lambda *a, **k: [])
    monkeypatch.setattr(module, "_read", lambda path: (b"", [question]))
    return question


def test_failed_case_stays_in_denominator(policy_store, eval_case):
    from types import SimpleNamespace

    from hr_rag import evaluation as module
    from hr_rag.providers import ProviderError

    def fail(*args, **kwargs):
        raise ProviderError("timeout")

    runner = SimpleNamespace(store=policy_store, retrieve=fail)
    report = module.evaluate(module.DEVELOPMENT_PATH, "dense", "full", retriever=runner)
    assert report["answerable_count"] == 1 and report["execution_errors"] == 1
    assert report["top5_all_hit"] == 0 and report["mean_context_precision"] == 0


def test_context_error_preserves_top5_and_security(
    policy_store, eval_case, monkeypatch
):
    from types import SimpleNamespace

    from hr_rag import evaluation as module
    from hr_rag.contracts import Evidence
    from hr_rag.providers import ProviderError

    found = [
        Evidence(chunk=c, score=1)
        for c in policy_store.snapshot().chunks
        if c.version_id in {"v1", "v3"}
    ]
    runner = SimpleNamespace(store=policy_store, retrieve=lambda *a, **k: found)

    def fail(*a, **k):
        raise ProviderError("budget")

    monkeypatch.setattr(module, "assemble_context", fail)
    report = module.evaluate(module.DEVELOPMENT_PATH, "dense", "full", retriever=runner)
    assert report["top5_all_hit"] == 1
    assert report["context_all_hit"] == 0
    assert report["authorization_errors"] == 1
    assert report["rows"][0]["error"] == "budget"
    assert len(report["rows"][0]["top5"]) == 2


def test_withdrawal_invalidates_evaluation(policy_store, eval_case):
    from types import SimpleNamespace

    from hr_rag import evaluation as module

    def withdraw(*a, **k):
        policy_store.withdraw("C01", "v1")
        return []

    runner = SimpleNamespace(store=policy_store, retrieve=withdraw)
    with pytest.raises(ValueError, match="corpus_changed_during_evaluation"):
        module.evaluate(module.DEVELOPMENT_PATH, "dense", "full", retriever=runner)


def test_comparison_rejects_different_snapshot():
    from hr_rag.evaluation import validate_comparison

    with pytest.raises(ValueError, match="comparison_inputs_changed"):
        validate_comparison(
            [{"execution_fingerprint": "before"}, {"execution_fingerprint": "after"}]
        )


@pytest.mark.parametrize("changed", ["holdout", "manifest", "development", "source"])
def test_baseline_mutations_require_revalidation(tmp_path, monkeypatch, changed):
    from hr_rag import evaluation as module

    monkeypatch.delenv("HR_RAG_HOLDOUT_PATH", raising=False)
    root = tmp_path / "project"
    (root / "eval").mkdir(parents=True)
    (root / "data").mkdir()
    external = tmp_path / "private-fixture.bin"
    external.write_bytes(b"opaque synthetic bytes, not evaluation questions")
    holdout_hash = module.sha256_bytes(external.read_bytes())
    for relative in ["data/manifest.json", "eval/development.jsonl"]:
        (root / relative).write_bytes(b"synthetic")
    freeze = {
        "status": "frozen",
        "holdout_sha256": holdout_hash,
        "holdout_path": str(external),
        "manifest_sha256": module.sha256_bytes(b"synthetic"),
        "development_sha256": module.sha256_bytes(b"synthetic"),
    }
    (root / "eval/baseline.freeze.json").write_text(json.dumps(freeze), "utf-8")
    (root / "eval/holdout.manifest.json").write_text(
        json.dumps(
            {
                "sha256": holdout_hash,
                "question_count": 10,
                "reviewed_count": 10,
            }
        ),
        "utf-8",
    )
    monkeypatch.setattr(module, "PROJECT_ROOT", root)
    monkeypatch.setattr(module, "validate_manifest", lambda path: [])
    assert module.verify_baseline() == freeze
    if changed == "source":
        monkeypatch.setattr(module, "validate_manifest", lambda path: ["hash_mismatch"])
    else:
        target = {
            "holdout": external,
            "manifest": root / "data/manifest.json",
            "development": root / "eval/development.jsonl",
        }[changed]
        target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="revalidation_required"):
        module.verify_baseline()


def test_supplemental_labels_do_not_replace_original(tmp_path):
    import json

    from hr_rag.evaluation import LabelStore, unit_hash

    original = tmp_path / "original.jsonl"
    extra = tmp_path / "extra.jsonl"

    def row(text, useful):
        return dict(
            question_id="D",
            role="employee",
            content_sha256=unit_hash(text),
            useful=useful,
            reviewer="human",
            reason="reviewed",
        )

    original.write_text(json.dumps(row("old", False)) + "\n", encoding="utf-8")
    before = original.read_bytes()
    extra.write_text(json.dumps(row("new", True)) + "\n", encoding="utf-8")
    store = LabelStore(original, supplemental_path=extra)
    assert store.lookup("D", "employee", "old") is False
    assert store.lookup("D", "employee", "new") is True
    assert original.read_bytes() == before
    extra.write_text(json.dumps(row("old", True)) + "\n", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="supplemental_label_collision"):
        LabelStore(original, supplemental_path=extra)


def test_holdout_location_from_env_or_generic_path(tmp_path, monkeypatch):
    """公開版不寫死使用者目錄：環境變數優先，否則展開 %LOCALAPPDATA% 等變數。"""
    from hr_rag import evaluation as module

    root = tmp_path / "project"
    (root / "eval").mkdir(parents=True)
    (root / "data").mkdir()
    for relative in ["data/manifest.json", "eval/development.jsonl"]:
        (root / relative).write_bytes(b"synthetic")
    private = tmp_path / "appdata" / "hr-leave-rag-private" / "holdout"
    private.mkdir(parents=True)
    (private / "holdout.jsonl").write_bytes(b"opaque fixture")
    digest = module.sha256_bytes(b"opaque fixture")
    freeze = {
        "status": "frozen",
        "holdout_sha256": digest,
        "holdout_path": "%HR_TEST_APPDATA%/hr-leave-rag-private/holdout/holdout.jsonl",
        "manifest_sha256": module.sha256_bytes(b"synthetic"),
        "development_sha256": module.sha256_bytes(b"synthetic"),
    }
    (root / "eval/baseline.freeze.json").write_text(json.dumps(freeze), "utf-8")
    (root / "eval/holdout.manifest.json").write_text(
        json.dumps({"sha256": digest, "question_count": 10, "reviewed_count": 10}),
        "utf-8",
    )
    monkeypatch.setattr(module, "PROJECT_ROOT", root)
    monkeypatch.setattr(module, "validate_manifest", lambda path: [])
    monkeypatch.delenv("HR_RAG_HOLDOUT_PATH", raising=False)
    monkeypatch.setenv("HR_TEST_APPDATA", str(tmp_path / "appdata"))
    assert module.verify_baseline() == freeze
    moved = tmp_path / "elsewhere.jsonl"
    moved.write_bytes(b"opaque fixture")
    monkeypatch.setenv("HR_TEST_APPDATA", str(tmp_path / "missing"))
    monkeypatch.setenv("HR_RAG_HOLDOUT_PATH", str(moved))
    assert module.verify_baseline() == freeze
