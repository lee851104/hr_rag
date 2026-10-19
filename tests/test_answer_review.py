import hashlib
import json

import pytest

from hr_rag.answer_review import assess, render


def test_review_is_pending_escaped_and_exports_only_decisions():
    report = {
        "kind": "development",
        "rows": [
            {
                "question_id": "D01",
                "role": "employee",
                "repeat": 1,
                "question": "<script>bad()</script>",
                "expected": {"answer_key": ["標準答案"]},
                "answer": {
                    "status": "answered",
                    "reason": None,
                    "claims": [{"text": "測試答案", "citation_ids": ["p1"]}],
                },
                "context": {
                    "units": [
                        {
                            "id": "p1",
                            "text": "證據",
                            "document_id": "O01",
                            "version_id": "v1",
                            "section_id": "1",
                        }
                    ]
                },
            }
        ],
    }
    page = render(report, "a" * 64)
    assert "<script>bad()</script>" not in page
    assert "&lt;script&gt;bad()&lt;/script&gt;" in page
    assert "尚未核對" in page and "匯出核對JSON" in page
    assert 'data-kind="citation"' in page
    assert "a" * 64 in page


def _row(qid, category, role="employee", repeat=1, status="answered", cites=("p1",)):
    claims = [{"text": "原文", "citation_ids": list(cites)}] if cites else []
    return {
        "question_id": qid,
        "category": category,
        "role": role,
        "repeat": repeat,
        "expected": {"expected_behavior": status, "answer_key": []},
        "answer": {"status": status, "claims": claims, "citations": list(cites)},
    }


def _development():
    rows = [_row(f"A{i:02d}", "direct") for i in range(11)]
    rows += [_row(f"V{i}", "version") for i in range(3)]
    rows += [_row(f"N{i}", "insufficient", status="insufficient", cites=())
             for i in range(3)]
    rows += [_row("P1", "permission", role=r) for r in ("hr", "employee", "manager")]
    return {"kind": "development", "rows": rows}


def _review(report, raw, **override):
    rows = []
    for row in report["rows"]:
        pairs = [
            {"claim_index": i, "citation_id": cid}
            for i, claim in enumerate(row["answer"]["claims"])
            for cid in claim["citation_ids"]
        ]
        rows.append({
            "question_id": row["question_id"], "role": row["role"],
            "repeat": row["repeat"], "claim_citation_pairs": pairs,
            "correct": True, "key_claims_covered": True,
            "citation_reviews": [p | {"supported": True} for p in pairs],
            "reason": "",
        })
    review = {
        "schema_version": 1, "source_sha256": hashlib.sha256(raw).hexdigest(),
        "kind": report["kind"], "reviewer": "使用者",
        "reviewed_at": "2026-10-19T01:49:42.311Z", "complete": True, "rows": rows,
    }
    return review | override


def _bytes(report):
    return json.dumps(report, ensure_ascii=False).encode()


def test_development_thresholds_allow_one_answerable_failure():
    report = _development()
    raw = _bytes(report)
    review = _review(report, raw)
    review["rows"][0]["correct"] = False
    result = assess(report, raw, review)
    assert result["answerable"] == {"passed": 13, "total": 14}
    assert result["insufficient"] == {"passed": 3, "total": 3}
    assert result["version"] == {"passed": 3, "total": 3}
    assert result["citation_support"]["rate"] == 1.0
    assert result["passed"] is True


def test_development_fails_below_thresholds():
    report = _development()
    raw = _bytes(report)
    review = _review(report, raw)
    review["rows"][0]["correct"] = False
    review["rows"][1]["correct"] = False
    assert assess(report, raw, review)["passed"] is False
    review = _review(report, raw)
    review["rows"][14]["correct"] = False  # 資料不足題
    assert assess(report, raw, review)["passed"] is False
    review = _review(report, raw)
    review["rows"][2]["key_claims_covered"] = False
    assert assess(report, raw, review)["passed"] is False


def test_citation_support_rate_is_pairs_and_threshold_95():
    report = _development()
    raw = _bytes(report)
    review = _review(report, raw)
    review["rows"][3]["citation_reviews"][0]["supported"] = False
    result = assess(report, raw, review)
    assert result["citation_support"] == {"supported": 16, "total": 17,
                                          "rate": 16 / 17}
    assert result["passed"] is False
    assert result["unsupported_citations"] == [
        {"question_id": "A03", "role": "employee", "repeat": 1,
         "claim_index": 0, "citation_id": "p1"}
    ]


def test_model_status_mismatch_never_passes_even_if_marked_correct():
    report = _development()
    report["rows"][0]["answer"]["status"] = "error"
    raw = _bytes(report)
    review = _review(report, raw)
    review["rows"][1]["correct"] = False
    result = assess(report, raw, review)
    assert result["answerable"]["passed"] == 12
    assert result["status_mismatches"][0]["question_id"] == "A00"
    assert result["passed"] is False


def test_stability_requires_every_run_and_citation():
    rows = [_row(q, "direct", repeat=r) for q in "ABCDEF" for r in (1, 2, 3)]
    report = {"kind": "stability", "rows": rows}
    raw = _bytes(report)
    assert assess(report, raw, _review(report, raw))["passed"] is True
    review = _review(report, raw)
    review["rows"][4]["citation_reviews"][0]["supported"] = False
    result = assess(report, raw, review)
    assert result["runs"] == {"passed": 17, "total": 18}
    assert result["passed"] is False


@pytest.mark.parametrize(
    "mutate, error",
    [
        (lambda r: r.update(source_sha256="0" * 64), "source_sha256_mismatch"),
        (lambda r: r.update(kind="stability"), "kind_mismatch"),
        (lambda r: r.update(complete=False), "review_incomplete"),
        (lambda r: r.update(reviewer=" "), "reviewer_missing"),
        (lambda r: r.update(reviewed_at="昨天"), "reviewed_at_invalid"),
        (lambda r: r["rows"].pop(), "row_identity_mismatch"),
        (lambda r: r["rows"][0].update(repeat=2), "row_identity_mismatch"),
        (lambda r: r["rows"][0].update(correct=None), "decision_missing"),
        (lambda r: r["rows"][0]["citation_reviews"][0].update(supported=None),
         "decision_missing"),
        (lambda r: r["rows"][0]["claim_citation_pairs"][0].update(citation_id="x"),
         "citation_pairs_mismatch"),
    ],
)
def test_invalid_review_is_rejected(mutate, error):
    report = _development()
    raw = _bytes(report)
    review = _review(report, raw)
    mutate(review)
    with pytest.raises(ValueError, match=error):
        assess(report, raw, review)

