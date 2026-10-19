"""實際初始語料的版本邊界、分條日期與撤回回歸。"""

from datetime import date

import pytest
from test_ingestion import run, setup


def test_version_transition_and_section_dates(corpus):
    module, store = setup(corpus)
    run(corpus, module, store)
    for day, version in [(date(2026, 9, 30), "v1"), (date(2026, 10, 1), "v2")]:
        snapshot = store.snapshot(role="employee", as_of=day)
        assert {c.version_id for c in snapshot.chunks if c.document_id == "C01"} == {
            version
        }
    historical = store.snapshot(role="hr", as_of=date(2017, 1, 1))
    assert {c.section_id for c in historical.chunks if c.document_id == "O01"} == {
        "39",
        "43",
    }
    assert not any(c.document_id in {"O05", "O06"} for c in historical.chunks)


@pytest.mark.parametrize("problem", ["unknown", "overlap", "pending"])
def test_invalid_manifest_is_quarantined_without_partial_publish(corpus, problem):
    module, store = setup(corpus)
    first = run(corpus, module, store)

    def edit(d):
        if problem == "unknown":
            d["indexed_sections"][0]["effective_from"] = None
        elif problem == "overlap":
            d["effective_from"] = "2026-09-30"
        else:
            d["review_status"] = "pending"

    corpus.change("C01", edit_document=edit, version_id="v2")
    corpus.embedder.calls.clear()
    with pytest.raises(module.IngestionError, match="manifest_invalid"):
        run(corpus, module, store)
    assert store.snapshot().generation_id == first
    assert corpus.embedder.calls == []
    assert store.failures()[-1]["code"] == "manifest_invalid"


def test_withdrawal_filters_vectors_parents_and_survives_reingest(corpus):
    module, store = setup(corpus)
    run(corpus, module, store)
    before = store.snapshot()
    module.withdraw("C04", "v1", store=store)
    after = store.snapshot()
    assert len(after.chunks) < len(before.chunks)
    assert not any(c.document_id == "C04" for c in after.chunks)
    assert not any(c.document_id == "C04" for c in after.parents.values())
    assert len(after.vectors) == len(after.chunks)
    assert {c.document_id for c in after.chunks} == {
        c.document_id for c in before.chunks
    } - {"C04"}
    run(corpus, module, store)
    assert not any(c.document_id == "C04" for c in store.snapshot().chunks)
