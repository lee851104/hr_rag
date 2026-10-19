"""Fail-closed local corpus validation; no network or review mutation."""

import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, ValidationError

from hr_rag.contracts import DocumentVersion, EffectiveInterval, NonEmpty


class IndexedSection(EffectiveInterval):
    section_id: NonEmpty
    date_evidence: NonEmpty


class ManifestRecord(DocumentVersion):
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    indexed_sections: tuple[IndexedSection, ...] = Field(min_length=1)
    author: NonEmpty
    reviewer: NonEmpty | None


def _number(text):
    if text.isascii() and text.isdigit():
        return int(text)
    digits = dict(zip("零一二三四五六七八九", range(10)))
    pattern = (
        r"[一二三四五六七八九]?百(零[一二三四五六七八九]|"
        r"[一二三四五六七八九]?十[一二三四五六七八九]?)?|"
        r"[一二三四五六七八九]?十[一二三四五六七八九]?|[一二三四五六七八九]"
    )
    if not re.fullmatch(pattern, text):
        raise ValueError
    total, current = 0, 0
    for char in text:
        if char in digits:
            current = digits[char]
        else:
            total += (current or 1) * {"百": 100, "十": 10}[char]
            current = 0
    return total + current


def roc_to_iso(text: str) -> str | None:
    """Parse one explicit ROC date; ambiguity or invalidity stays unknown."""
    if not isinstance(text, str):
        return None
    if re.search(r"民國\s*前|西元|公元", text):
        return None
    number = r"[\d零一二三四五六七八九十百]+"
    matches = list(
        re.finditer(rf"({number})\s*年\s*({number})\s*月\s*({number})\s*日", text)
    )
    if len(matches) != 1:
        return None
    match = matches[0]
    prefix = text[: match.start()].rstrip()
    if prefix and (
        prefix[-1] in "前負千萬億兆兩〇○-−﹣－+＋.．"
        or prefix[-1].isascii()
        and prefix[-1].isalnum()
    ):
        return None
    try:
        year, month, day = map(_number, match.groups())
        if not 1 <= year <= 999:
            return None
        return date(year + 1911, month, day).isoformat()
    except (ValueError, TypeError):
        return None


def _load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) != {"schema_version", "documents"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or not isinstance(data["documents"], list)
    ):
        raise ValueError
    return data["documents"]


def _data_path(manifest, value, kind):
    root = Path(manifest).resolve().parent
    if root.name == "data":
        root = root.parent
    supplied = Path(value)
    if supplied.is_absolute() or ".." in supplied.parts:
        raise ValueError
    target = (root / supplied).resolve()
    allowed = root / "data" / kind
    if target == allowed or not target.is_relative_to(allowed):
        raise ValueError
    return target


def validate_manifest(
    path: Path,
    *,
    require_reviewed=True,
    check_counts=True,
    allow_acl_restrictions=False,
):
    """Return safe diagnostics without echoing source text or supplied values."""
    try:
        documents = _load(path)
    except (OSError, ValueError, TypeError):
        return ["manifest: invalid JSON or schema"]
    errors, records, seen = [], [], set()
    for index, item in enumerate(documents):
        loc = f"documents[{index}]"
        try:
            record = ManifestRecord.model_validate(item)
        except ValidationError as exc:
            for error in exc.errors():
                field = ".".join(
                    str(p)
                    for p in error["loc"]
                    if isinstance(p, int)
                    or p in ManifestRecord.model_fields
                    or p in IndexedSection.model_fields
                )
                errors.append(f"{loc}.{field}: invalid or missing field")
            continue
        records.append(record)
        key = record.document_id, record.version_id
        if key in seen:
            errors.append(f"{loc}: duplicate version ID")
        seen.add(key)
        official = record.document_id in {f"O{i:02}" for i in range(1, 7)}
        company = record.document_id in {"C01", "C02", "C03", "C04"}
        roles = {"employee", "manager", "hr"}
        if record.document_id == "C03":
            roles = {"manager", "hr"}
        if record.document_id == "C04":
            roles = {"hr"}
        if (
            not (official or company)
            or not record.allowed_roles
            or (
                not set(record.allowed_roles) <= roles
                if allow_acl_restrictions
                else set(record.allowed_roles) != roles
            )
            or len(record.allowed_roles) != len(set(record.allowed_roles))
        ):
            errors.append(f"{loc}.allowed_roles: invalid document or ACL")
        if record.source_type != ("official" if official else "company"):
            errors.append(f"{loc}.source_type: invalid source")
        if record.is_synthetic != company:
            errors.append(f"{loc}.is_synthetic: invalid provenance")
        if official:
            try:
                url = urlsplit(record.source_url or "")
                domain = (
                    "law.moj.gov.tw"
                    if record.document_id <= "O04"
                    else "www.mol.gov.tw"
                )
                if url.scheme != "https" or url.hostname != domain or url.username:
                    raise ValueError
            except ValueError:
                errors.append(f"{loc}.source_url: invalid official source")
        if record.effective_from is None:
            errors.append(f"{loc}.effective_from: unknown date; pending")
        if record.document_id in {"O05", "O06"} and (
            record.published_at is None
            or record.effective_from != record.published_at
            or "發布" not in record.date_evidence
            or "非法規生效日" not in record.date_evidence
        ):
            errors.append(f"{loc}: Q&A requires publication-date evidence")
        if any(s.effective_from is None for s in record.indexed_sections):
            errors.append(f"{loc}.indexed_sections: unknown date; pending")
        for section in record.indexed_sections:
            if (
                record.effective_from
                and section.effective_from
                and section.effective_from < record.effective_from
            ) or (
                record.effective_to
                and (
                    section.effective_to is None
                    or section.effective_to > record.effective_to
                )
            ):
                errors.append(
                    f"{loc}.indexed_sections: section interval exceeds document"
                )
        starts = [s.effective_from for s in record.indexed_sections if s.effective_from]
        if official and starts and record.effective_from != min(starts):
            errors.append(f"{loc}.effective_from: section dates disagree")
        section_ids = {s.section_id for s in record.indexed_sections}
        if len(section_ids) != len(record.indexed_sections):
            errors.append(f"{loc}.indexed_sections: duplicate section")
        reviewed, due = record.last_reviewed_at, record.next_review_due
        if (reviewed is None) != (due is None) or (
            reviewed and (reviewed > date.today() or due <= reviewed)
        ):
            errors.append(f"{loc}: invalid review dates")
        if require_reviewed and (
            record.review_status != "verified"
            or not record.reviewer
            or not reviewed
            or not due
        ):
            errors.append(f"{loc}: pending human review")
        if record.review_status == "verified" and not record.reviewer:
            errors.append(f"{loc}.reviewer: verified requires human reviewer")
        contents = {}
        for kind, field, digest in [
            ("raw", record.raw_path, record.raw_sha256),
            ("normalized", record.normalized_path, record.content_sha256),
        ]:
            try:
                target = _data_path(path, field, kind)
                content = target.read_bytes()
                if hashlib.sha256(content).hexdigest() != digest:
                    errors.append(f"{loc}.{kind}: hash mismatch")
                contents[kind] = content
                if company and "虛構" not in content.decode("utf-8"):
                    errors.append(f"{loc}.{kind}: missing synthetic label")
            except (ValueError, OSError, UnicodeError):
                errors.append(f"{loc}.{kind}: unsafe or unreadable path")
        if "normalized" in contents:
            try:
                normalized = json.loads(contents["normalized"])
                if not isinstance(normalized, dict):
                    raise ValueError
                sections = normalized["sections"]
                expected_fields = {"document_id", "version_id", "title", "sections"}
                if (
                    set(normalized) != expected_fields
                    or normalized["document_id"] != record.document_id
                    or normalized["version_id"] != record.version_id
                    or normalized["title"] != record.title
                    or not isinstance(sections, list)
                    or any(
                        not isinstance(s, dict)
                        or set(s) != {"section_id", "title", "text"}
                        or any(
                            not isinstance(v, str) or not v.strip() for v in s.values()
                        )
                        for s in sections
                    )
                    or len({s["section_id"] for s in sections}) != len(sections)
                    or {s["section_id"] for s in sections} != section_ids
                ):
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                errors.append(f"{loc}.normalized: invalid section structure")
    for i, left in enumerate(records):
        for right in records[i + 1 :]:
            if (
                left.document_id == right.document_id
                and left.effective_from
                and right.effective_from
                and left.effective_from < (right.effective_to or date.max)
                and right.effective_from < (left.effective_to or date.max)
            ):
                errors.append(f"documents[{i}]: overlapping version intervals")
    if check_counts:
        ids = {r.document_id for r in records}
        expected = {f"O{i:02}" for i in range(1, 7)} | {f"C{i:02}" for i in range(1, 5)}
        if ids != expected or len(records) != 11:
            errors.append("manifest: expected ten documents and eleven versions")
        if sum(r.source_type == "official" for r in records) != 6:
            errors.append("manifest: expected six official versions")
        counts = Counter(r.document_id for r in records)
        if counts != Counter({key: 2 if key == "C01" else 1 for key in expected}):
            errors.append("manifest: invalid version distribution; C01 requires two")
    return errors


def allowlisted_data_paths(path: Path, *, check_counts=True) -> list[Path]:
    if validate_manifest(path, require_reviewed=False, check_counts=check_counts):
        raise ValueError("manifest failed structural validation")
    return sorted(
        {
            _data_path(path, item[field], kind)
            for item in _load(path)
            for field, kind in [("raw_path", "raw"), ("normalized_path", "normalized")]
        }
    )


def due_reviews(path: Path, *, as_of: date) -> list[dict]:
    """Report pending or due documents without updating review metadata."""
    pending = {}
    for item in _load(path):
        record = ManifestRecord.model_validate(item)
        reason = None
        if record.review_status != "verified" or record.next_review_due is None:
            reason = "pending"
        elif record.next_review_due <= as_of:
            reason = "overdue"
        if reason:
            existing = pending.get(record.document_id)
            if existing is None or reason == "pending":
                pending[record.document_id] = dict(
                    document_id=record.document_id,
                    maintenance_owner=record.maintenance_owner,
                    reason=reason,
                )
    return [pending[key] for key in sorted(pending)]
