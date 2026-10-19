"""Regression checks on the actual draft corpus; never open a holdout body."""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from hr_rag.corpus.manifest import (
    allowlisted_data_paths,
    due_reviews,
    validate_manifest,
)
from hr_rag.corpus.source_text import extract_law, extract_qa
from hr_rag.evaluation_schema import validate_evaluation

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifest.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_actual_corpus_structure_and_allowlist():
    assert validate_manifest(MANIFEST, require_reviewed=False) == []
    records = load(MANIFEST)["documents"]
    assert Counter(r["document_id"] for r in records) == {
        "O01": 1,
        "O02": 1,
        "O03": 1,
        "O04": 1,
        "O05": 1,
        "O06": 1,
        "C01": 2,
        "C02": 1,
        "C03": 1,
        "C04": 1,
    }
    assert all(
        p.is_relative_to(ROOT / "data") for p in allowlisted_data_paths(MANIFEST)
    )
    assert all("eval" not in p.parts for p in allowlisted_data_paths(MANIFEST))
    pending = [r for r in records if r["review_status"] == "pending"]
    assert all(r["reviewer"] is None and r["last_reviewed_at"] is None for r in pending)
    assert len(validate_manifest(MANIFEST)) == len(pending)
    if pending:
        assert {
            r["document_id"] for r in due_reviews(MANIFEST, as_of=date(2026, 10, 18))
        } >= {r["document_id"] for r in pending}


def test_selected_official_text_is_exact_extraction_of_saved_sources():
    for record in load(MANIFEST)["documents"]:
        if record["source_type"] != "official":
            continue
        page = (ROOT / record["raw_path"]).read_text(encoding="utf-8")
        normalized = load(ROOT / record["normalized_path"])
        if record["document_id"] in {"O05", "O06"}:
            qa = extract_qa(page)
            assert normalized["sections"] == [qa["section"]]
            assert record["effective_from"] == qa["published_at"]
            assert record["revised_at"] is None
        else:
            ids = [s["section_id"] for s in record["indexed_sections"]]
            assert normalized["sections"] == extract_law(page, ids)
            assert all("沿革" in s["date_evidence"] for s in record["indexed_sections"])


def test_company_versions_change_only_application():
    versions = [
        load(ROOT / r["normalized_path"])
        for r in load(MANIFEST)["documents"]
        if r["document_id"] == "C01"
    ]
    left, right = [{s["section_id"]: s for s in v["sections"]} for v in versions]
    assert left.keys() == right.keys()
    assert [key for key in left if left[key] != right[key]] == ["application"]
    for record in load(MANIFEST)["documents"]:
        if record["source_type"] == "company":
            raw = (ROOT / record["raw_path"]).read_text(encoding="utf-8")
            assert all(
                s["text"] in raw
                for s in load(ROOT / record["normalized_path"])["sections"]
            )


def test_development_references_and_frozen_stability_selection():
    development = ROOT / "eval/development.jsonl"
    assert (
        validate_evaluation(
            development,
            split="development",
            manifest_path=MANIFEST,
            require_reviewed=False,
        )
        == []
    )
    questions = {
        q["question_id"]: q
        for q in map(json.loads, development.read_text(encoding="utf-8").splitlines())
    }
    selection = load(ROOT / "eval/stability-cases.json")
    assert (
        selection["development_sha256"]
        == hashlib.sha256(development.read_bytes()).hexdigest()
    )
    assert Counter(c["case_type"] for c in selection["cases"]) == {
        "official": 1,
        "company": 1,
        "cross_document": 1,
        "version": 1,
        "permission": 1,
        "insufficient": 1,
    }
    assert len({c["question_id"] for c in selection["cases"]}) == 6
    for case in selection["cases"]:
        question = questions[case["question_id"]]
        canonical = json.dumps(
            question, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        assert (
            case["question_sha256"]
            == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        )
        assert case["as_of"] == question["as_of"]
        assert case["expected_result"] == question["role_expectations"][case["role"]]
