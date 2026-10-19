"""真SQLite與NumPy測試；只有耗時模型使用可記錄的替身。"""

import importlib

import numpy as np
import pytest


def setup(corpus):
    module = importlib.import_module("hr_rag.corpus.ingest")
    store = importlib.import_module("hr_rag.storage").CorpusStore(corpus.root / "index")
    return module, store


def run(corpus, module, store, **kwargs):
    return module.ingest(
        corpus.manifest, store=store, embedder=corpus.embedder, **kwargs
    )


def test_ingest_twice_is_idempotent(corpus):
    module, store = setup(corpus)
    first = run(corpus, module, store)
    before = store.snapshot()
    corpus.embedder.calls.clear()
    second = run(corpus, module, store)
    after = store.snapshot()
    assert first == second
    assert [c.id for c in before.chunks] == [c.id for c in after.chunks]
    np.testing.assert_array_equal(before.vectors, after.vectors)
    assert corpus.embedder.calls == []
    assert len(after.parents) == 44
    assert len(after.documents) == 11
    for document in after.documents:
        assert len(document["raw_sha256"]) == 64
    for child in after.chunks:
        span = after.locations[child.id]
        assert (
            after.parents[child.parent_id].text[span["start"] : span["end"]]
            == child.text
        )


def test_failed_generation_preserves_active(corpus):
    module, store = setup(corpus)
    first = run(corpus, module, store)
    before = store.snapshot()
    corpus.change(
        "C02",
        edit_sections=lambda ss: [
            s.update(text=s["text"] + " 新增虛構說明。") for s in ss
        ],
    )
    corpus.embedder.calls.clear()
    corpus.embedder.fail_on = 2
    with pytest.raises(module.IngestionError):
        run(corpus, module, store, batch_size=1)
    assert store.snapshot().generation_id == first
    np.testing.assert_array_equal(store.snapshot().vectors, before.vectors)
    assert len(list((store.root / "snapshots").glob("*.npy"))) == 1
    assert store.failures()[-1]["code"] == "embedding_failed"
    corpus.embedder.fail_on = None
    corpus.embedder.calls.clear()
    run(corpus, module, store, batch_size=1)
    assert len(corpus.embedder.calls) == 4  # 失敗交易不能留下一半cache。


def test_snapshot_write_failure_preserves_active(corpus, monkeypatch):
    module, store = setup(corpus)
    first = run(corpus, module, store)
    corpus.change(
        "C02",
        edit_sections=lambda ss: ss[0].update(text=ss[0]["text"] + " 虛構新規則。"),
    )

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(store, "write_snapshot", fail)
    with pytest.raises(module.IngestionError):
        run(corpus, module, store)
    assert store.snapshot().generation_id == first


@pytest.mark.parametrize("invalid", ["nan", "wrong_count", "wrong_dimensions"])
def test_invalid_vectors_cannot_replace_active(corpus, invalid):
    module, store = setup(corpus)
    first = run(corpus, module, store)
    corpus.change(
        "C02",
        edit_sections=lambda ss: ss[0].update(text=ss[0]["text"] + " 虛構新規則。"),
    )

    def embed(texts):
        if invalid == "nan":
            return np.full((len(texts), 3), np.nan)
        return np.ones(
            (
                len(texts) + (invalid == "wrong_count"),
                4 if invalid == "wrong_dimensions" else 3,
            )
        )

    corpus.embedder.embed = embed
    with pytest.raises(module.IngestionError, match="invalid_vectors"):
        run(corpus, module, store)
    assert store.snapshot().generation_id == first


def test_change_one_document_only_recomputes_its_changed_text(corpus):
    module, store = setup(corpus)
    run(corpus, module, store)
    before = store.snapshot()
    corpus.embedder.calls.clear()
    corpus.change(
        "C02",
        edit_sections=lambda ss: ss[0].update(text=ss[0]["text"] + " 虛構更新一段。"),
    )
    run(corpus, module, store)
    after = store.snapshot()
    assert sum(map(len, corpus.embedder.calls)) == 1
    old = {
        c.id: v for c, v in zip(before.chunks, before.vectors) if c.document_id != "C02"
    }
    new = {
        c.id: v for c, v in zip(after.chunks, after.vectors) if c.document_id != "C02"
    }
    assert old.keys() == new.keys()
    for key in old:
        np.testing.assert_array_equal(old[key], new[key])


def test_metadata_only_update_reuses_vectors_and_updates_visibility(corpus):
    from datetime import date

    module, store = setup(corpus)
    run(corpus, module, store)
    before = store.snapshot()
    corpus.embedder.calls.clear()

    def edit(d):
        d["allowed_roles"] = ["hr"]
        d["effective_from"] = "2026-10-01"
        for section in d["indexed_sections"]:
            section["effective_from"] = "2026-10-01"

    corpus.change("C02", edit_document=edit)
    run(corpus, module, store)
    after = store.snapshot()
    assert corpus.embedder.calls == []
    assert [c.id for c in before.chunks] == [c.id for c in after.chunks]
    np.testing.assert_array_equal(before.vectors, after.vectors)
    assert not any(
        c.document_id == "C02"
        for c in store.snapshot(role="employee", as_of=date(2026, 10, 18)).chunks
    )
    assert not any(
        c.document_id == "C02"
        for c in store.snapshot(role="hr", as_of=date(2026, 9, 30)).chunks
    )
    assert any(
        c.document_id == "C02"
        for c in store.snapshot(role="hr", as_of=date(2026, 10, 1)).chunks
    )


def test_deleted_section_leaves_active_chunks_parents_and_vectors(corpus):
    module, store = setup(corpus)
    run(corpus, module, store)
    before = store.snapshot()
    removed = {
        c.id
        for c in before.chunks
        if c.document_id == "C02" and c.section_id == "tracking"
    }
    corpus.change(
        "C02",
        edit_sections=lambda ss: ss.__setitem__(
            slice(None), [s for s in ss if s["section_id"] != "tracking"]
        ),
    )
    corpus.embedder.calls.clear()
    run(corpus, module, store)
    after = store.snapshot()
    assert removed and removed.isdisjoint(c.id for c in after.chunks)
    assert len(after.vectors) == len(after.chunks) == len(before.chunks) - len(removed)
    assert not any(
        p.document_id == "C02" and p.section_id == "tracking"
        for p in after.parents.values()
    )
    assert corpus.embedder.calls == []


@pytest.mark.parametrize("changed", ["model", "chunking"])
def test_config_change_rebuilds_all_vectors_with_reason(corpus, changed):
    module, store = setup(corpus)
    run(corpus, module, store)
    corpus.embedder.calls.clear()
    kwargs = (
        {"embedding_revision": "synthetic-revision-2"}
        if changed == "model"
        else {"max_tokens": 390}
    )
    run(corpus, module, store, **kwargs)
    after = store.snapshot()
    assert sum(map(len, corpus.embedder.calls)) == len({c.text for c in after.chunks})
    assert after.metadata["rebuild_reason"] == (
        "embedding_model_changed" if changed == "model" else "chunking_config_changed"
    )


def test_corrupt_snapshot_is_rejected(corpus):
    module, store = setup(corpus)
    run(corpus, module, store)
    target = next((store.root / "snapshots").glob("*.npy"))
    target.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="snapshot_integrity"):
        store.snapshot()


def test_manifest_cannot_expand_original_acl(corpus):
    module, store = setup(corpus)
    corpus.change(
        "C04", edit_document=lambda d: d.update(allowed_roles=["employee", "hr"])
    )
    with pytest.raises(module.IngestionError, match="manifest_invalid"):
        run(corpus, module, store)
    assert store.snapshot() is None


def test_no_eval_or_holdout_files_are_ingested(corpus):
    module, store = setup(corpus)
    (corpus.root / "eval").mkdir()
    (corpus.root / "eval/holdout.jsonl").write_text(
        "DO_NOT_READ_SYNTHETIC_SENTINEL", encoding="utf-8"
    )
    run(corpus, module, store)
    assert all("DO_NOT_READ" not in c.text for c in store.snapshot().chunks)


def test_actual_tokenizer_configuration_changes_invalidate_vector_cache(corpus):
    from tokenizers import Tokenizer, normalizers

    from hr_rag.corpus.chunking import load_tokenizer

    module, store = setup(corpus)
    original = run(corpus, module, store)
    corpus.embedder.calls.clear()
    changed = Tokenizer.from_str(load_tokenizer().to_str())
    changed.normalizer = normalizers.Lowercase()
    current = run(corpus, module, store, tokenizer=changed)
    assert current != original
    assert corpus.embedder.calls
    assert store.snapshot().metadata["rebuild_reason"] == "chunking_config_changed"
