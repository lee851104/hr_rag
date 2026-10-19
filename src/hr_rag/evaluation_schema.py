"""Offline evaluation contracts; diagnostics never contain supplied content."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTIONS = {
    "development": dict(
        zip(
            ("direct", "paraphrase_cross", "version", "permission", "insufficient"),
            (6, 5, 3, 3, 3),
        )
    ),
    "holdout": dict(
        zip(
            ("direct", "paraphrase_cross", "version", "permission", "insufficient"),
            (4, 3, 1, 1, 1),
        )
    ),
}
ROLES = {"employee", "manager", "hr"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Reference(StrictModel):
    document_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)


class Expectation(StrictModel):
    expected_behavior: Literal["answered", "insufficient", "clarify"]
    answer_key: list[str]
    required_evidence_groups: list[list[Reference]]
    forbidden_sources: list[str]

    @model_validator(mode="after")
    def check_evidence(self):
        if any(not group for group in self.required_evidence_groups):
            raise ValueError("empty_group")
        if self.expected_behavior == "answered":
            if not self.answer_key or not self.required_evidence_groups:
                raise ValueError("missing_answer_evidence")
        elif self.answer_key or self.required_evidence_groups:
            raise ValueError("unexpected_answer_evidence")
        if any(not value.strip() for value in self.answer_key + self.forbidden_sources):
            raise ValueError("empty_value")
        if any(
            ref.document_id in self.forbidden_sources
            for group in self.required_evidence_groups
            for ref in group
        ):
            raise ValueError("forbidden_evidence")
        return self


class Question(StrictModel):
    question_id: str = Field(min_length=1)
    category: Literal[
        "direct", "paraphrase_cross", "version", "permission", "insufficient"
    ]
    split: Literal["development", "holdout"]
    question: str = Field(min_length=1)
    as_of: str
    role_expectations: dict[str, Expectation]
    author: str = Field(min_length=1)
    reviewer: str | None
    reviewed_at: str | None
    review_status: Literal["pending", "verified"]

    @model_validator(mode="after")
    def check_question(self):
        _date(self.as_of)
        roles = set(self.role_expectations)
        if not roles <= ROLES or not roles:
            raise ValueError("roles")
        if self.category == "permission":
            if (
                roles != ROLES
                or self.role_expectations["hr"].expected_behavior != "answered"
            ):
                raise ValueError("permission_roles")
        elif len(roles) != 1:
            raise ValueError("single_role")
        if self.category in {"direct", "paraphrase_cross", "version"} and any(
            e.expected_behavior != "answered" for e in self.role_expectations.values()
        ):
            raise ValueError("answerable_behavior")
        if self.category == "insufficient" and any(
            e.expected_behavior != "insufficient"
            for e in self.role_expectations.values()
        ):
            raise ValueError("insufficient_behavior")
        if self.review_status == "verified":
            if not self.reviewer or not self.reviewer.strip() or not self.reviewed_at:
                raise ValueError("review_missing")
        elif self.reviewer is not None or self.reviewed_at is not None:
            raise ValueError("pending_review_metadata")
        if self.reviewed_at:
            _date(self.reviewed_at)
        if any(
            not value.strip()
            for value in (self.question_id, self.question, self.author)
        ):
            raise ValueError("blank")
        return self


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date_format")
    return date.fromisoformat(value)


def _read(path):
    raw = Path(path).read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    if any(not line.strip() for line in lines):
        raise ValueError("blank_line")
    return raw, [Question.model_validate(json.loads(line)) for line in lines]


def _interval(record, as_of):
    start = _date(record["effective_from"])
    end = _date(record["effective_to"]) if record.get("effective_to") else None
    if end is not None and end <= start:
        return False
    return start <= as_of and (end is None or as_of < end)


def validate_evaluation(
    path: Path,
    *,
    split: str,
    manifest_path: Path | None = None,
    require_reviewed: bool = True,
) -> list[str]:
    """Return fixed error codes only; never serialize input or exceptions."""
    if split not in DISTRIBUTIONS:
        return ["invalid_split"]
    try:
        if split == "holdout" and Path(path).resolve().is_relative_to(
            PROJECT_ROOT.resolve()
        ):
            return ["holdout_path_inside_project"]
        _, questions = _read(path)
    except (OSError, ValueError, TypeError, ValidationError, RecursionError):
        return ["evaluation_unreadable_or_invalid_schema"]
    errors = []
    if Counter(q.category for q in questions) != DISTRIBUTIONS[split]:
        errors.append("category_distribution")
    if len({q.question_id for q in questions}) != len(questions):
        errors.append("duplicate_question_id")
    if any(q.split != split for q in questions):
        errors.append("split_mismatch")
    if require_reviewed and any(q.review_status != "verified" for q in questions):
        errors.append("human_review_pending")
    if manifest_path is not None:
        try:
            documents = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))[
                "documents"
            ]
            refs = {}
            for document in documents:
                for section in document["indexed_sections"]:
                    key = (
                        document["document_id"],
                        document["version_id"],
                        section["section_id"],
                    )
                    if key in refs:
                        raise ValueError("duplicate_reference")
                    refs[key] = (document, section)
            for question in questions:
                for role, expectation in question.role_expectations.items():
                    for group in expectation.required_evidence_groups:
                        for ref in group:
                            document, section = refs[
                                (ref.document_id, ref.version_id, ref.section_id)
                            ]
                            if (
                                role not in document["allowed_roles"]
                                or not _interval(document, _date(question.as_of))
                                or not _interval(section, _date(question.as_of))
                            ):
                                raise ValueError("ineligible_reference")
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            errors.append("manifest_reference_invalid")
    return errors


def summarize_evaluation(path, split, *, require_reviewed=True):
    """Allowlisted aggregate only; invalid inputs cannot produce a valid summary."""
    if validate_evaluation(path, split=split, require_reviewed=require_reviewed):
        raise ValueError("evaluation_invalid")
    raw, questions = _read(path)
    return {
        "split": split,
        "question_count": len(questions),
        "category_counts": dict(Counter(q.category for q in questions)),
        "independently_answerable_count": sum(
            q.category not in {"permission", "insufficient"} for q in questions
        ),
        "role_execution_count": sum(len(q.role_expectations) for q in questions),
        "reviewed_count": sum(q.review_status == "verified" for q in questions),
        "authors": sorted({q.author for q in questions}),
        "reviewers": sorted({q.reviewer for q in questions if q.reviewer}),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True, choices=DISTRIBUTIONS)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--allow-pending-review", action="store_true")
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args(argv)
    errors = validate_evaluation(
        args.path,
        split=args.split,
        manifest_path=args.manifest,
        require_reviewed=not args.allow_pending_review,
    )
    if errors:
        print(json.dumps({"valid": False, "errors": errors}))
        return 1
    try:
        summary = summarize_evaluation(
            args.path, args.split, require_reviewed=not args.allow_pending_review
        )
        output = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        if args.summary_output:
            if args.summary_output.resolve() == args.path.resolve():
                raise ValueError("output_overwrites_input")
            args.summary_output.write_text(output, encoding="utf-8")
        print(output, end="")
    except (OSError, ValueError):
        print('{"valid": false, "errors": ["summary_failed"]}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
