import hashlib
import json

import pytest

from hr_rag import evaluation_schema as schema


def rows(split="development"):
    result = []
    for category, count in schema.DISTRIBUTIONS[split].items():
        for _ in range(count):
            expected = {
                "expected_behavior": "answered",
                "answer_key": ["fixture-key"],
                "required_evidence_groups": [
                    [{"document_id": "D", "version_id": "v1", "section_id": "S"}]
                ],
                "forbidden_sources": [],
            }
            if category == "insufficient":
                expected.update(
                    expected_behavior="insufficient",
                    answer_key=[],
                    required_evidence_groups=[],
                )
            roles = {"hr": expected}
            if category == "permission":
                roles.update(
                    {
                        role: {
                            "expected_behavior": "insufficient",
                            "answer_key": [],
                            "required_evidence_groups": [],
                            "forbidden_sources": ["D"],
                        }
                        for role in ("employee", "manager")
                    }
                )
            result.append(
                {
                    "question_id": f"fixture-{len(result)}",
                    "category": category,
                    "split": split,
                    "question": "fixture-question",
                    "as_of": "2026-10-18",
                    "role_expectations": roles,
                    "author": "fixture-author",
                    "reviewer": "fixture-reviewer",
                    "reviewed_at": "2026-10-18",
                    "review_status": "verified",
                }
            )
    return result


def write(tmp_path, items):
    path = tmp_path / "fixture.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in items), encoding="utf-8")
    return path


def test_valid_and_pending_review(tmp_path):
    items = rows()
    path = write(tmp_path, items)
    assert schema.validate_evaluation(path, split="development") == []
    for item in items:
        item.update(review_status="pending", reviewer=None, reviewed_at=None)
    path = write(tmp_path, items)
    assert schema.validate_evaluation(path, split="development")
    assert (
        schema.validate_evaluation(path, split="development", require_reviewed=False)
        == []
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.pop(),
        lambda x: x[0].update(question_id=x[1]["question_id"]),
        lambda x: x[0].update(split="holdout"),
        lambda x: x[0].update(as_of="2026-02-30"),
        lambda x: x[0].update(role_expectations={}),
        lambda x: x[14]["role_expectations"].pop("employee"),
        lambda x: x[0]["role_expectations"]["hr"].update(required_evidence_groups=[]),
        lambda x: x[0]["role_expectations"]["hr"].update(forbidden_sources=["D"]),
    ],
)
def test_reject_invalid_structure(tmp_path, mutation):
    items = rows()
    mutation(items)
    assert schema.validate_evaluation(write(tmp_path, items), split="development")


def test_holdout_summary_is_aggregate_and_hash(tmp_path):
    path = write(tmp_path, rows("holdout"))
    result = schema.summarize_evaluation(path, "holdout")
    assert result["question_count"] == 10
    assert result["independently_answerable_count"] == 8
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert all(
        value not in json.dumps(result)
        for value in ("fixture-question", "fixture-key", "fixture-0")
    )


def test_holdout_inside_project_rejected_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "PROJECT_ROOT", tmp_path)
    path = write(tmp_path, rows("holdout"))
    assert schema.validate_evaluation(path, split="holdout") == [
        "holdout_path_inside_project"
    ]


def test_errors_never_echo_input_and_summary_fails_closed(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"question":"SECRET_RAW_BODY"}', encoding="utf-8")
    assert "SECRET_RAW_BODY" not in str(
        schema.validate_evaluation(path, split="development")
    )
    with pytest.raises(ValueError, match="evaluation_invalid"):
        schema.summarize_evaluation(path, "development")


@pytest.mark.parametrize("change", ["missing", "acl", "section_date", "document_date"])
def test_manifest_references_acl_and_dates(tmp_path, change):
    path = write(tmp_path, rows())
    document = {
        "document_id": "D",
        "version_id": "v1",
        "allowed_roles": ["hr"],
        "effective_from": "2026-01-01",
        "effective_to": None,
        "indexed_sections": [
            {"section_id": "S", "effective_from": "2026-01-01", "effective_to": None}
        ],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [document]}), encoding="utf-8")
    assert (
        schema.validate_evaluation(path, split="development", manifest_path=manifest)
        == []
    )
    if change == "missing":
        document["indexed_sections"][0]["section_id"] = "other"
    elif change == "acl":
        document["allowed_roles"] = ["employee"]
    elif change == "section_date":
        document["indexed_sections"][0]["effective_to"] = "2026-10-18"
    else:
        document["effective_from"] = "2026-10-19"
    manifest.write_text(json.dumps({"documents": [document]}), encoding="utf-8")
    assert schema.validate_evaluation(
        path, split="development", manifest_path=manifest
    ) == ["manifest_reference_invalid"]


def test_cli_failed_validation_does_not_write_summary(tmp_path, capsys):
    path = write(tmp_path, [])
    output = tmp_path / "summary.json"
    assert (
        schema.main(
            [
                "--split",
                "development",
                "--path",
                str(path),
                "--summary-output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_symlink_into_project_is_rejected(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    path = write(project, rows("holdout"))
    link = tmp_path / "linked.jsonl"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    monkeypatch.setattr(schema, "PROJECT_ROOT", project)
    assert schema.validate_evaluation(link, split="holdout") == [
        "holdout_path_inside_project"
    ]


@pytest.mark.parametrize("category", ["direct", "paraphrase_cross", "version"])
@pytest.mark.parametrize("behavior", ["insufficient", "clarify"])
def test_answerable_categories_cannot_reduce_answerable_denominator(
    tmp_path, category, behavior
):
    items = rows()
    question = next(item for item in items if item["category"] == category)
    question["role_expectations"]["hr"].update(
        expected_behavior=behavior, answer_key=[], required_evidence_groups=[]
    )
    path = write(tmp_path, items)
    assert schema.validate_evaluation(path, split="development") == [
        "evaluation_unreadable_or_invalid_schema"
    ]
    with pytest.raises(ValueError, match="evaluation_invalid"):
        schema.summarize_evaluation(path, "development")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"documents": None},
        {"documents": [None]},
        {"documents": [{"indexed_sections": None}]},
    ],
)
def test_malformed_manifest_fails_closed_with_fixed_code(tmp_path, payload):
    path = write(tmp_path, rows())
    manifest = tmp_path / "malformed.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert schema.validate_evaluation(
        path, split="development", manifest_path=manifest
    ) == ["manifest_reference_invalid"]
