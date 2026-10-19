"""明確執行的階段2本機實測；不讀保留題或.env，不呼叫生成API。"""

import hashlib
import html
import json
import time
from collections import Counter

from hr_rag.corpus.chunking import encoder_token_count, load_tokenizer, token_count
from hr_rag.corpus.ingest import ingest
from hr_rag.local_models import LocalEncoder
from hr_rag.settings import PROJECT_ROOT, RuntimeSettings
from hr_rag.storage import CorpusStore


class MeasuredEncoder:
    def __init__(self):
        self.model = None
        self.calls = []

    def embed(self, texts):
        if self.model is None:
            self.model = LocalEncoder(
                "embedding", PROJECT_ROOT / ".cache/models/embedding", RuntimeSettings()
            )
        self.calls.append(len(texts))
        return self.model.embed(texts)

    def close(self):
        if self.model is not None:
            self.model.close()


def main():
    manifest = PROJECT_ROOT / "data/manifest.json"
    destination = PROJECT_ROOT / "reports/stage-2-artifacts.json"
    previous = None
    if destination.exists():
        previous = json.loads(destination.read_text("utf-8"))
        if previous.get("human_review_status") != "pending":
            raise ValueError("reviewed_report_exists")
    store = CorpusStore()
    encoder = MeasuredEncoder()
    started = time.perf_counter()
    try:
        generation = ingest(manifest, store=store, embedder=encoder)
        initial_calls = list(encoder.calls)
        encoder.calls.clear()
        second = ingest(manifest, store=store, embedder=encoder)
        assert generation == second and encoder.calls == []
    finally:
        encoder.close()
    snapshot = store.snapshot()
    tokenizer = load_tokenizer()
    reranker_tokenizer = load_tokenizer("reranker")
    records = {(d["document_id"], d["version_id"]): d for d in snapshot.documents}
    for child in snapshot.chunks:
        location = snapshot.locations[child.id]
        parent = snapshot.parents[child.parent_id]
        assert parent.text[location["start"] : location["end"]] == child.text
        assert (
            encoder_token_count((tokenizer, reranker_tokenizer), child.text)
            == location["token_count"]
            <= 400
        )
        record = records[(child.document_id, child.version_id)]
        normalized = json.loads(
            (PROJECT_ROOT / record["normalized_path"]).read_text("utf-8")
        )
        section = next(
            s for s in normalized["sections"] if s["section_id"] == child.section_id
        )
        assert section["text"] == parent.text
    selected = []
    documents = sorted({c.document_id for c in snapshot.chunks})
    for doc_id in documents:
        selected.append(next(c for c in snapshot.chunks if c.document_id == doc_id))
    for child in snapshot.chunks:
        if child not in selected:
            selected.append(child)
        if len(selected) >= 20:
            break
    assert len(selected) >= 20 and len(documents) == 10
    examples = []
    for index, child in enumerate(selected, 1):
        parent = snapshot.parents[child.parent_id]
        record = records[(child.document_id, child.version_id)]
        wrong_parent = next(
            p
            for p in snapshot.parents.values()
            if p.document_id != child.document_id and p.text != parent.text
        )
        wrong_record = records[(wrong_parent.document_id, wrong_parent.version_id)]
        examples.append(
            {
                "review_id": f"S{index:02}",
                "chunk": child.model_dump(mode="json"),
                "location": snapshot.locations[child.id],
                "parent_text": parent.text,
                "raw_path": record["raw_path"],
                "normalized_path": record["normalized_path"],
                "raw_sha256": record["raw_sha256"],
                "review_status": "pending",
                "reviewer": None,
                "reviewed_at": None,
                "negative_example": {
                    "wrong_document_id": wrong_parent.document_id,
                    "wrong_version_id": wrong_parent.version_id,
                    "wrong_section_id": wrong_parent.section_id,
                    "wrong_parent_id": wrong_parent.id,
                    "wrong_parent_text": wrong_parent.text,
                    "wrong_raw_path": wrong_record["raw_path"],
                    "wrong_normalized_path": wrong_record["normalized_path"],
                    "wrong_raw_sha256": wrong_record["raw_sha256"],
                    "expected": (
                        "不得將此片段當成其他條文或其他版本的證據；"
                        "須回到上列原節與完整父段"
                    ),
                },
            }
        )
    report = {
        "generation_id": generation,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "document_count": len(documents),
        "version_count": len(records),
        "parent_count": len(snapshot.parents),
        "child_count": len(snapshot.chunks),
        "max_child_tokens": max(v["token_count"] for v in snapshot.locations.values()),
        "max_embedding_tokens": max(
            token_count(tokenizer, c.text) for c in snapshot.chunks
        ),
        "max_reranker_tokens": max(
            token_count(reranker_tokenizer, c.text) for c in snapshot.chunks
        ),
        "vectors_shape": list(snapshot.vectors.shape),
        "vectors_finite": True,
        "vector_snapshot_sha256": hashlib.sha256(
            (store.root / "snapshots" / (generation + ".npy")).read_bytes()
        ).hexdigest(),
        "document_chunk_vector_sha256": {
            doc_id: hashlib.sha256(
                b"".join(
                    child.id.encode() + vector.tobytes()
                    for child, vector in zip(snapshot.chunks, snapshot.vectors)
                    if child.document_id == doc_id
                )
            ).hexdigest()
            for doc_id in documents
        },
        "embedding_batches": initial_calls,
        "embedding_texts": sum(initial_calls),
        "repeat_embedding_calls": 0,
        "repeat_generation_unchanged": True,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "children_by_document": dict(
            sorted(Counter(c.document_id for c in snapshot.chunks).items())
        ),
        "config": snapshot.metadata["config"],
        "review_examples": examples,
        "human_review_status": "pending",
        "api_calls": 0,
    }
    # 保留前次實測摘要，不把重跑零呼叫覆蓋為首次建置成績。
    report["previous_runs"] = (
        []
        if previous is None
        else [
            *previous.get("previous_runs", []),
            {
                k: v
                for k, v in previous.items()
                if k not in {"review_examples", "previous_runs"}
            },
        ]
    )
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    parts = [
        "<!doctype html><meta charset='utf-8'><title>階段2片段核對</title>",
        "<style>body{max-width:1000px;margin:32px auto;font:16px/1.6 system-ui}"
        "pre{white-space:pre-wrap;background:#f3f4f6;padding:16px}"
        "details{margin:20px 0;border:1px solid #ddd;padding:16px}</style>",
        "<h1>階段2片段核對（20項）</h1><p>全部待使用者核對；程式定位比對通過不等於人工驗收。每項核對子片段、完整父段、版本、權限與日期。</p>",
    ]
    for item in examples:
        child = item["chunk"]
        label = (
            f"{item['review_id']} — {child['document_id']} / "
            f"{child['version_id']} / {child['section_id']}"
        )
        parts.append(f"<details><summary>{html.escape(label)}</summary>")
        metadata = {k: v for k, v in child.items() if k != "text"}
        parts.append(
            "<h3>定位與權限</h3><pre>"
            + html.escape(
                json.dumps(
                    {**metadata, **item["location"], "raw_path": item["raw_path"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            + "</pre>"
        )
        for heading, content in [
            ("子片段", child["text"]),
            ("完整父段（含條件與例外）", item["parent_text"]),
            (
                "錯配反例：下列其他來源不能作為此片段的引用",
                json.dumps(item["negative_example"], ensure_ascii=False, indent=2),
            ),
        ]:
            parts.append(f"<h3>{heading}</h3><pre>{html.escape(content)}</pre>")
        parts.append(
            "<p>核對狀態：待確認。通過時請回報S編號；此頁不自動保存簽核。</p></details>"
        )
    (PROJECT_ROOT / "reports/stage-2-review.html").write_text(
        "\n".join(parts), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"review_examples", "config", "previous_runs"}
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
