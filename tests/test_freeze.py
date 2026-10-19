"""7.1最終凍結：記錄並核對設定、程式、評估與語料hash；離線。"""

import json

import pytest

from hr_rag import freeze


@pytest.fixture
def root(tmp_path):
    for name, text in {
        "config/models.lock.json": "{}",
        "src/hr_rag/a.py": "x = 1\n",
        "src/hr_rag/templates/base.html": "<html>",
        "eval/development.jsonl": "{}\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def patterns():
    return [
        "config/*.json",
        "src/hr_rag/**/*.py",
        "src/hr_rag/templates/*.html",
        "eval/*.jsonl",
    ]


def test_write_then_verify_and_detect_changes(root):
    target = root / "eval/final.freeze.json"
    record = freeze.write_freeze(
        target, root=root, patterns=patterns(), extra={"cost_cap_usd": "1"}
    )
    assert set(record["files"]) == {
        "config/models.lock.json",
        "src/hr_rag/a.py",
        "src/hr_rag/templates/base.html",
        "eval/development.jsonl",
    }
    assert freeze.verify_final_freeze(target, root=root) == record["files"]
    (root / "src/hr_rag/a.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="final_freeze_changed:src/hr_rag/a.py"):
        freeze.verify_final_freeze(target, root=root)


def test_added_or_removed_files_are_changes(root):
    target = root / "eval/final.freeze.json"
    freeze.write_freeze(target, root=root, patterns=patterns())
    (root / "src/hr_rag/new.py").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="src/hr_rag/new.py"):
        freeze.verify_final_freeze(target, root=root)


def test_freeze_is_not_silently_overwritten(root):
    target = root / "eval/final.freeze.json"
    freeze.write_freeze(target, root=root, patterns=patterns())
    with pytest.raises(ValueError, match="freeze_exists"):
        freeze.write_freeze(target, root=root, patterns=patterns())


def test_project_freeze_covers_final_configuration():
    names = set(freeze.collect(freeze.PROJECT_ROOT, freeze.PATTERNS))
    for required in (
        "config/models.lock.json",
        "config/generation.selected.json",
        "config/retrieval.selected.json",
        "config/query-synonyms.json",
        "config/monitoring.json",
        "data/manifest.json",
        "eval/development.jsonl",
        "eval/labels.jsonl",
        "eval/holdout.manifest.json",
        "src/hr_rag/verbatim.py",
        "src/hr_rag/holdout.py",
        "src/hr_rag/answer_review.py",
        "reports/stage5-human-review-development-v3.json",
        "reports/retrieval-stage5-verbatim-v3.json",
    ):
        assert required in names, required
    assert not any(n.startswith(".runtime") for n in names)
    assert "eval/final.freeze.json" not in names
    summary = freeze.configuration_summary()
    assert summary["generation"]["model"] == "gpt-4.1-2025-04-14"
    assert summary["cost_cap_usd"] == "1"
    assert summary["monitoring"]["p95_seconds"] < summary["generation"]["timeout"]
    json.dumps(summary)
