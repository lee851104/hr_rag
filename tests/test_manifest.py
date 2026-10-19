import hashlib
import json
from copy import deepcopy
from datetime import date

import pytest

from hr_rag.corpus.manifest import (
    allowlisted_data_paths,
    due_reviews,
    roc_to_iso,
    validate_manifest,
)


@pytest.fixture
def manifest(tmp_path):
    raw = tmp_path / "data/raw/a.txt"
    normalized = tmp_path / "data/normalized/a.json"
    raw.parent.mkdir(parents=True)
    normalized.parent.mkdir(parents=True)
    raw.write_text("官方正文", encoding="utf-8")
    normalized.write_text(
        json.dumps(
            {
                "document_id": "O01",
                "version_id": "v1",
                "title": "法規",
                "sections": [{"section_id": "1", "title": "第一條", "text": "正文"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    record = dict(
        document_id="O01",
        version_id="v1",
        title="法規",
        source_type="official",
        source_url="https://law.moj.gov.tw/test",
        is_synthetic=False,
        published_at=None,
        revised_at=None,
        effective_from="2020-01-01",
        effective_to=None,
        fetched_at="2026-10-18T00:00:00+08:00",
        date_evidence="來源日期",
        allowed_roles=["employee", "manager", "hr"],
        content_sha256=hashlib.sha256(normalized.read_bytes()).hexdigest(),
        raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        review_status="verified",
        raw_path="data/raw/a.txt",
        normalized_path="data/normalized/a.json",
        source_publisher="官方",
        maintenance_owner="維護者",
        last_reviewed_at="2026-01-01",
        next_review_due="2026-10-01",
        author="編輯者",
        reviewer="人工核對者",
        indexed_sections=[
            dict(
                section_id="1",
                effective_from="2020-01-01",
                effective_to=None,
                date_evidence="來源日期",
            )
        ],
    )
    path = tmp_path / "manifest.json"

    def save():
        path.write_text(
            json.dumps({"schema_version": 1, "documents": [record]}), encoding="utf-8"
        )
        return path

    save()
    return record, save


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("修正日期：民國 113 年 07 月 31 日", "2024-07-31"),
        ("自一百零六年一月一日施行", "2017-01-01"),
        ("民國113年2月30日", None),
        ("一百百年一月一日", None),
        ("113年1月1日及114年1月1日", None),
        ("2024-01-01", None),
        ("民國前一年一月一日", None),
        ("-113年1月1日", None),
        ("民國 −113年1月1日", None),
        ("西元2024年1月1日", None),
        ("千一百年一月一日", None),
        ("民國113年-1月1日", None),
    ],
)
def test_roc(text, expected):
    assert roc_to_iso(text) == expected


def test_valid_and_due(manifest):
    _, save = manifest
    path = save()
    assert validate_manifest(path, check_counts=False) == []
    assert due_reviews(path, as_of=date(2026, 10, 18))[0]["document_id"] == "O01"
    assert len(allowlisted_data_paths(path, check_counts=False)) == 2


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("raw_sha256", "0" * 64),
        ("source_url", None),
        ("allowed_roles", []),
        ("maintenance_owner", ""),
        ("effective_from", None),
        ("last_reviewed_at", "2027-01-01"),
        ("next_review_due", "2026-01-01"),
        ("raw_path", "../secret"),
        ("reviewer", None),
    ],
)
def test_invalid_record(manifest, key, value):
    record, save = manifest
    record[key] = value
    assert validate_manifest(save(), check_counts=False)


def test_pending_structural(manifest):
    record, save = manifest
    record.update(
        review_status="pending",
        reviewer=None,
        last_reviewed_at=None,
        next_review_due=None,
    )
    path = save()
    assert validate_manifest(path, check_counts=False)
    assert not validate_manifest(path, require_reviewed=False, check_counts=False)
    assert due_reviews(path, as_of=date(2026, 10, 18))[0]["reason"] == "pending"


def test_overlap_duplicate_and_boundary(manifest):
    record, save = manifest
    path = save()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["documents"].append(dict(record))
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("duplicate" in e for e in validate_manifest(path, check_counts=False))
    data["documents"][1]["version_id"] = "v2"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("overlap" in e for e in validate_manifest(path, check_counts=False))
    data["documents"][0]["effective_to"] = "2020-01-02"
    data["documents"][1]["effective_from"] = "2020-01-02"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not any("overlap" in e for e in validate_manifest(path, check_counts=False))


def test_unknown_section_date_and_missing_publisher(manifest):
    record, save = manifest
    record["indexed_sections"][0]["effective_from"] = None
    assert validate_manifest(save(), require_reviewed=False, check_counts=False)
    record["indexed_sections"][0]["effective_from"] = "2020-01-01"
    del record["source_publisher"]
    assert validate_manifest(save(), check_counts=False)


def test_escaping_path_is_rejected_before_read(manifest, monkeypatch):
    record, save = manifest
    record["raw_path"] = "../secret"
    path = save()
    original = type(path).read_bytes

    def guarded_read(target):
        assert target.name != "secret"
        return original(target)

    monkeypatch.setattr(type(path), "read_bytes", guarded_read)
    assert validate_manifest(path, check_counts=False)
    with pytest.raises(ValueError, match="structural"):
        allowlisted_data_paths(path, check_counts=False)


def test_default_fixed_counts(manifest):
    _, save = manifest
    assert any("ten documents" in e for e in validate_manifest(save()))


@pytest.mark.parametrize(
    "payload",
    [
        ["document_id", "version_id", "title", "sections"],
        {
            "document_id": "O01",
            "version_id": "v1",
            "title": "法規",
            "sections": [["section_id", "title", "text"]],
        },
    ],
)
def test_normalized_non_object_is_safe_error(manifest, payload):
    record, save = manifest
    path = save()
    normalized = path.parent / record["normalized_path"]
    normalized.write_text(json.dumps(payload), encoding="utf-8")
    record["content_sha256"] = hashlib.sha256(normalized.read_bytes()).hexdigest()
    assert any(
        "invalid section structure" in e
        for e in validate_manifest(save(), check_counts=False)
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2019-12-31", "2020-02-01"),
        ("2020-02-01", None),
        ("2020-01-01", "2020-02-02"),
    ],
)
def test_section_cannot_exceed_document_interval(manifest, start, end):
    record, save = manifest
    record["effective_to"] = "2020-02-01"
    record["indexed_sections"][0].update(effective_from=start, effective_to=end)
    assert any(
        "section interval" in e for e in validate_manifest(save(), check_counts=False)
    )


@pytest.mark.parametrize("historical_id", ["C01", "C02", "C03", "C04"])
def test_fixed_version_distribution(manifest, historical_id):
    template, save = manifest
    path = save()
    records = []
    ids = [f"O{i:02}" for i in range(1, 7)] + [f"C{i:02}" for i in range(1, 5)]
    for document_id in ids + [historical_id]:
        record = deepcopy(template)
        record["document_id"] = document_id
        company = document_id.startswith("C")
        record.update(
            source_type="company" if company else "official", is_synthetic=company
        )
        if document_id in {"O05", "O06"}:
            record.update(
                source_url="https://www.mol.gov.tw/test",
                published_at="2020-01-01",
                date_evidence="依問答發布日期，非法規生效日",
            )
        if document_id == "C03":
            record["allowed_roles"] = ["manager", "hr"]
        elif document_id == "C04":
            record["allowed_roles"] = ["hr"]
        if any(r["document_id"] == document_id for r in records):
            record.update(version_id="v2", effective_from="2021-01-01")
            next(r for r in records if r["document_id"] == document_id)[
                "effective_to"
            ] = "2021-01-01"
            next(r for r in records if r["document_id"] == document_id)[
                "indexed_sections"
            ][0]["effective_to"] = "2021-01-01"
            record["indexed_sections"][0]["effective_from"] = "2021-01-01"
        suffix = document_id + record["version_id"]
        raw = path.parent / "data/raw" / (suffix + ".txt")
        normalized = path.parent / "data/normalized" / (suffix + ".json")
        raw.write_text("虛構正文" if company else "官方正文", encoding="utf-8")
        normalized.write_text(
            json.dumps(
                dict(
                    document_id=document_id,
                    version_id=record["version_id"],
                    title=record["title"],
                    sections=[
                        dict(
                            section_id="1",
                            title="條文",
                            text="虛構正文" if company else "正文",
                        )
                    ],
                ),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        record.update(
            raw_path=raw.relative_to(path.parent).as_posix(),
            normalized_path=normalized.relative_to(path.parent).as_posix(),
            raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
            content_sha256=hashlib.sha256(normalized.read_bytes()).hexdigest(),
        )
        records.append(record)
    path.write_text(
        json.dumps(dict(schema_version=1, documents=records)), encoding="utf-8"
    )
    errors = validate_manifest(path)
    if historical_id == "C01":
        assert errors == []
    else:
        assert any("version distribution" in error for error in errors)
