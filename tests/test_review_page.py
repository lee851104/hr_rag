import hashlib
import json
import re

from hr_rag.evaluation import write_review


def review_fixture():
    return [
        {
            "mode": "dense",
            "rows": [
                {
                    "question_id": "D01",
                    "question": "問題 </script><script>alert(1)</script>",
                    "role": "employee",
                    "as_of": "2026-10-18",
                    "units": [
                        {
                            "human_useful": None,
                            "content_sha256": "a" * 64,
                            "chunk": {
                                "document_id": "C01",
                                "version_id": "v1",
                                "section_id": "section",
                                "text": "證據 <img onerror=alert(1)>",
                            },
                        }
                    ],
                }
            ],
        }
    ]


def test_review_has_explicit_pending_and_safe_export_metadata(tmp_path):
    path = tmp_path / "review.html"
    assert write_review(review_fixture(), path) == 1
    page = path.read_text("utf-8")
    assert 'id="export-json"' in page
    assert 'value="useful"' in page and 'value="not-useful"' in page
    assert 'value="pending" checked' in page
    payload = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    data = json.loads(payload)
    assert (
        data["review_set_sha256"]
        == hashlib.sha256(path.with_suffix(".json").read_bytes()).hexdigest()
    )
    assert data["items"] == [
        {
            "review_id": "L001",
            "question_id": "D01",
            "role": "employee",
            "content_sha256": "a" * 64,
        }
    ]
    assert "</script><script>alert" not in page
    assert "<img onerror" not in page


def test_review_keeps_original_companion_data_and_deduplicates(tmp_path):
    runs = review_fixture()
    runs.append({**runs[0], "mode": "rerank"})
    path = tmp_path / "review.html"
    assert write_review(runs, path) == 1
    rows = json.loads(path.with_suffix(".json").read_text("utf-8"))
    assert rows[0]["modes"] == ["dense", "rerank"]
    assert rows[0]["unit"] == runs[0]["rows"][0]["units"][0]
