"""只依版本化同義詞建立共同表示；不刪除條號、日期或否定。"""

import hashlib
import json
import re

from hr_rag.corpus.chunking import encoder_token_count, load_tokenizer
from hr_rag.settings import PROJECT_ROOT

SYNONYMS_PATH = PROJECT_ROOT / "config/query-synonyms.json"


class QueryError(ValueError):
    def __init__(self, code, clarification=None):
        super().__init__(code)
        self.clarification = clarification


def synonyms_hash():
    return hashlib.sha256(SYNONYMS_PATH.read_bytes()).hexdigest()


def normalize_query(question: str) -> str:
    if not isinstance(question, str) or not question.strip():
        raise QueryError("empty_question")
    rules = json.loads(SYNONYMS_PATH.read_text("utf-8"))["replacements"]
    pattern = "|".join(
        re.escape(term) for term in sorted(rules, key=lambda s: (-len(s), s))
    )
    return re.sub(pattern, lambda match: rules[match[0]], question.strip())


def prepare_query(question, *, tokenizers=None, normalize=True):
    if not isinstance(question, str) or not question.strip():
        raise QueryError("empty_question")
    prepared = normalize_query(question) if normalize else question.strip()
    tokenizers = tokenizers or (load_tokenizer(), load_tokenizer("reranker"))
    if encoder_token_count(tokenizers, prepared) > 96:
        raise QueryError("query_too_long")
    return prepared


def rerank_queries(prepared: str) -> tuple[str, ...]:
    """保留完整表示，再補最多兩個明示並列的子句；不改數字或否定。"""
    clauses = [part.strip(" ，,。？！?!；;\n") for part in prepared.split("以及")[1:]]
    return tuple(dict.fromkeys([prepared, *(c for c in clauses if len(c) >= 6)]))[:3]
