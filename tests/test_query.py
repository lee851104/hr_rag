from types import SimpleNamespace

import pytest

from hr_rag.query import QueryError, normalize_query, prepare_query


class CharacterTokenizer:
    def encode(self, text, **kwargs):
        return SimpleNamespace(ids=list(range(len(text) + 2)))


def test_synonyms_preserve_distinct_leave_negation_numbers_and_dates():
    assert normalize_query("特休幾天？") == normalize_query("特別休假幾天？")
    result = normalize_query("不是特休，補休依第38條於2026-10-01有14日嗎？")
    assert all(
        term in result for term in ("不是", "補休", "第38條", "2026-10-01", "14日")
    )
    assert normalize_query("補休") == "補休"


def test_query_limit_checks_both_tokenizers_without_truncation():
    tokenizer = CharacterTokenizer()
    assert prepare_query("甲" * 94, tokenizers=(tokenizer, tokenizer))
    with pytest.raises(QueryError, match="query_too_long"):
        prepare_query("甲" * 95, tokenizers=(tokenizer, tokenizer))
    with pytest.raises(QueryError, match="empty_question"):
        prepare_query(" ", tokenizers=(tokenizer, tokenizer))


def test_reranker_tokenizer_can_reject_when_embedding_length_fits():
    class WiderTokenizer(CharacterTokenizer):
        def encode(self, text, **kwargs):
            return SimpleNamespace(ids=list(range(len(text) * 2 + 2)))

    with pytest.raises(QueryError, match="query_too_long"):
        prepare_query("甲" * 60, tokenizers=(CharacterTokenizer(), WiderTokenizer()))
