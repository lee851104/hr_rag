"""切片保留完整來源、條款與例外，不允許靜默截斷。"""

import importlib
import json
from pathlib import Path

import pytest

from hr_rag.corpus.manifest import ManifestRecord

ROOT = Path(__file__).resolve().parents[1]


def api():
    return importlib.import_module("hr_rag.corpus.chunking")


def source(document_id="O01"):
    record = next(
        r
        for r in json.loads((ROOT / "data/manifest.json").read_text("utf-8"))[
            "documents"
        ]
        if r["document_id"] == document_id
    )
    return ManifestRecord.model_validate(record), (
        ROOT / record["normalized_path"]
    ).read_text("utf-8")


def test_actual_tokenizer_bounds_and_exact_source_spans():
    module = api()
    tokenizer = module.load_tokenizer()
    document, text = source()
    result = module.plan_chunks(document, text, tokenizer=tokenizer)
    assert len(result.parents) == 3
    parents = {p.id: p for p in result.parents}
    children = [c.chunk for c in result.children]
    assert len([c for c in children if c.section_id == "38"]) >= 2
    assert "但年度終結未休之日數" in next(
        p.text for p in parents.values() if p.section_id == "38"
    )
    for child in result.children:
        parent = parents[child.chunk.parent_id]
        assert parent.text[child.start : child.end] == child.chunk.text
        assert child.token_count == len(tokenizer.encode(child.chunk.text).ids) <= 400
        assert child.chunk.allowed_roles == document.allowed_roles
        assert (
            child.chunk.effective_from.isoformat()
            == {"38": "2018-03-01", "39": "2016-12-23", "43": "1984-08-01"}[
                child.chunk.section_id
            ]
        )
    for parent in parents.values():
        spans = sorted(
            (c.start, c.end) for c in result.children if c.chunk.parent_id == parent.id
        )
        cursor = 0
        for start, end in spans:
            assert not parent.text[cursor:start].strip()
            cursor = end
        assert not parent.text[cursor:].strip()


def test_qa_is_one_complete_parent_and_ids_survive_metadata_change():
    module = api()
    document, text = source("O06")
    first = module.plan_chunks(document, text)
    assert len(first.parents) == 1
    changed = document.model_copy(update={"allowed_roles": ("hr",)})
    second = module.plan_chunks(changed, text)
    assert [c.chunk.id for c in first.children] == [c.chunk.id for c in second.children]
    assert all(c.chunk.allowed_roles == ("hr",) for c in second.children)
    assert module.chunk_document(document, text) == [c.chunk for c in first.children]


def test_oversize_sentence_is_rejected_without_truncation():
    module = api()
    document, text = source()
    normalized = json.loads(text)
    normalized["sections"][0]["text"] = "請" * 450
    with pytest.raises(module.ChunkingError, match="sentence_over_limit"):
        module.plan_chunks(document, json.dumps(normalized, ensure_ascii=False))


def test_repeated_paragraphs_have_distinct_stable_ids():
    module = api()
    document, text = source()
    normalized = json.loads(text)
    normalized["sections"] = [normalized["sections"][0]]
    normalized["sections"][0]["text"] = "請假應通知。\n請假應通知。\n但緊急時可補件。"
    result = module.plan_chunks(
        document, json.dumps(normalized, ensure_ascii=False), max_tokens=12
    )
    assert len(result.children) == 3
    assert len({c.chunk.id for c in result.children}) == 3
    assert result.children[0].chunk.text == result.children[1].chunk.text


def test_unknown_section_date_fails_closed():
    module = api()
    document, text = source()
    sections = list(document.indexed_sections)
    sections[0] = sections[0].model_copy(update={"effective_from": None})
    document = document.model_copy(update={"indexed_sections": tuple(sections)})
    with pytest.raises(module.ChunkingError, match="unknown_date"):
        module.plan_chunks(document, text)


def test_embedding_unknown_token_cannot_hide_reranker_overflow():
    module = api()
    document, text = source()
    normalized = json.loads(text)
    normalized["sections"][0]["text"] = "請假條件：" + "😀" * 600 + "。"
    with pytest.raises(module.ChunkingError, match="sentence_over_limit"):
        module.plan_chunks(document, json.dumps(normalized, ensure_ascii=False))


def test_tokenizer_file_update_is_visible_in_same_process(tmp_path, monkeypatch):
    from tokenizers import Tokenizer, models, pre_tokenizers

    module = api()
    path = tmp_path / "tokenizer.json"
    first = Tokenizer(models.WordLevel({"[UNK]": 0, "one": 1}, unk_token="[UNK]"))
    first.save(str(path))
    monkeypatch.setattr(module, "TOKENIZER_PATH", path)
    clear_cache = getattr(module.load_tokenizer, "cache_clear", lambda: None)
    clear_cache()
    try:
        old = module.load_tokenizer()
        assert len(old.encode("one two three").ids) == 1
        first.pre_tokenizer = pre_tokenizers.Whitespace()
        first.save(str(path))
        new = module.load_tokenizer()
        assert len(new.encode("one two three").ids) == 3
    finally:
        clear_cache()
