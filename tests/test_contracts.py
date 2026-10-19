"""驗證不可信輸入不會變成有效的執行契約。"""

from datetime import date

import pytest
from pydantic import ValidationError

from hr_rag.contracts import Answer, Chunk, DocumentVersion, Principal, QueryRequest
from hr_rag.settings import RuntimeSettings


@pytest.mark.parametrize("role", ["admin", "HR", "", None])
def test_unknown_role_rejected(role):
    with pytest.raises(ValidationError):
        Principal(user_id="demo", role=role)


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_blank_question_rejected(question):
    with pytest.raises(ValidationError):
        QueryRequest(question=question)


@pytest.mark.parametrize("value", ["2026-02-30", "yesterday", 0, "2026-10-18T12:00:00"])
def test_invalid_date_rejected(value):
    with pytest.raises(ValidationError):
        QueryRequest(question="測試", as_of=value)


def test_query_does_not_accept_role_or_evidence():
    with pytest.raises(ValidationError):
        QueryRequest(question="測試", role="hr", evidence=["假證據"])
    query = QueryRequest(question="  測試  ", as_of="2026-10-18")
    assert query.question == "測試"
    assert query.as_of == date(2026, 10, 18)


@pytest.mark.parametrize("end", ["2026-09-30", "2026-10-01"])
def test_invalid_effective_interval_rejected(end):
    with pytest.raises(ValidationError):
        Chunk(
            id="p1",
            document_id="fixture",
            version_id="v1",
            section_id="s1",
            parent_id="p1",
            text="虛構測試",
            allowed_roles=["employee"],
            effective_from="2026-10-01",
            effective_to=end,
        )


def test_answer_status_and_claim_contract():
    with pytest.raises(ValidationError):
        Answer(status="success", claims=[], citations=[], reason=None)
    with pytest.raises(ValidationError):
        Answer(status="answered", claims=[], citations=[], reason=None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"evidence_budget": -1},
        {"output_reserve": 0},
        {"safety_margin": -1},
        {"context_limit": 256},
        {"evidence_budget": 4096},
        {"timeout_seconds": 0},
        {"base_url": "https://example.com"},
    ],
)
def test_invalid_runtime_settings_rejected(overrides):
    with pytest.raises(ValidationError):
        RuntimeSettings(**overrides)


def test_exact_context_boundary_and_overflow():
    settings = RuntimeSettings(
        context_limit=1000,
        evidence_budget=500,
        output_reserve=200,
        safety_margin=100,
    )
    settings.check_request_tokens(700, evidence_tokens=500)
    with pytest.raises(ValueError):
        settings.check_request_tokens(701, evidence_tokens=500)
    with pytest.raises(ValueError):
        settings.check_request_tokens(600, evidence_tokens=501)


@pytest.mark.parametrize("value", [0, 86400, "2026-10-18T00:00:00"])
def test_chunk_date_never_infers_a_timestamp(value):
    with pytest.raises(ValidationError):
        Chunk(
            id="p1",
            document_id="fixture",
            version_id="v1",
            section_id="s1",
            parent_id="p1",
            text="虛構測試",
            allowed_roles=["employee"],
            effective_from=value,
        )


@pytest.mark.parametrize(
    "field",
    [
        "effective_from",
        "effective_to",
        "published_at",
        "revised_at",
        "last_reviewed_at",
        "next_review_due",
    ],
)
@pytest.mark.parametrize("value", [86400, "2026-10-18T00:00:00"])
def test_document_calendar_dates_reject_numeric_and_datetime(field, value):
    payload = dict(
        document_id="fixture",
        version_id="v1",
        title="虛構制度",
        source_type="company",
        source_url=None,
        is_synthetic=True,
        effective_from=None,
        effective_to=None,
        published_at=None,
        revised_at=None,
        fetched_at="2026-10-18T00:00:00+08:00",
        date_evidence="待核對",
        allowed_roles=["employee"],
        content_sha256="a" * 64,
        review_status="pending",
        raw_path="fixture.txt",
        normalized_path="fixture.txt",
        source_publisher="模擬公司",
        maintenance_owner="專案維護者",
        last_reviewed_at=None,
        next_review_due=None,
    )
    assert DocumentVersion(**payload).effective_from is None
    payload[field] = value
    with pytest.raises(ValidationError):
        DocumentVersion(**payload)
