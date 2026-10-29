"""先授權再計分；本機dense／BM25-RRF／重排共用候選邊界。"""

import logging
import re
import threading
import time
from datetime import date

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from hr_rag.audit import note
from hr_rag.contracts import Evidence, Principal
from hr_rag.corpus.chunking import load_tokenizer
from hr_rag.local_models import LocalEncoder
from hr_rag.policy import clarify_date, eligible_chunks
from hr_rag.providers import ProviderError
from hr_rag.query import QueryError, prepare_query, rerank_queries
from hr_rag.settings import PROJECT_ROOT, RuntimeSettings
from hr_rag.storage import CorpusStore

MODES = ("dense", "hybrid", "rerank")
_SPECIAL = re.compile(
    r"第[零〇一二三四五六七八九十百千\d]+條(?:之\d+)?|\d{4}-\d{2}-\d{2}|\d+"
)
jieba.setLogLevel(logging.WARNING)


def lexical_tokens(text):
    tokens = []
    start = 0
    for match in _SPECIAL.finditer(text):
        tokens.extend(t for t in jieba.cut(text[start : match.start()]) if t.strip())
        tokens.append(match[0])
        start = match.end()
    tokens.extend(t for t in jieba.cut(text[start:]) if t.strip())
    return tokens or ["<empty>"]


def rrf(dense_ids, lexical_ids):
    result = {}
    for ranking in (dense_ids[:20], lexical_ids[:20]):
        for rank, chunk_id in enumerate(ranking, 1):
            result[chunk_id] = result.get(chunk_id, 0.0) + 1 / (60 + rank)
    return result


class Retriever:
    def __init__(self, *, store=None, embedder=None, reranker=None, tokenizers=None):
        self.store = store or CorpusStore()
        self.embedder = embedder
        self.reranker = reranker
        self.tokenizers = tokenizers or (load_tokenizer(), load_tokenizer("reranker"))
        self._owned = []
        self._lock = threading.Lock()
        # 送入重排的候選數；量測不同k時可調，正式值為20。
        self.candidate_limit = 20

    def close(self):
        for model in self._owned:
            model.close()
        self._owned.clear()

    def _model(self, role, timings=None):
        name = "embedder" if role == "embedding" else "reranker"
        # 載入期間持鎖：預熱與首查同時到時只建立一個子程序，後到者等它完成。
        with self._lock:
            model = getattr(self, name)
            if model is None:
                started = time.monotonic()
                model = LocalEncoder(
                    role, PROJECT_ROOT / ".cache/models" / role, RuntimeSettings()
                )
                setattr(self, name, model)
                self._owned.append(model)
                if timings is not None:
                    timings["model_load"] = (
                        timings.get("model_load", 0.0)
                        + (time.monotonic() - started) * 1000
                    )
            return model

    def warmup(self):
        """服務啟動時先載入並實際推論一次，把冷啟動移出使用者的第一個查詢。"""
        self._model("embedding").embed(["暖機"])
        self._model("reranker").rerank("暖機", ["暖機"])

    def retrieve(
        self,
        query: str,
        principal: Principal,
        as_of: date,
        mode: str,
        k: int = 5,
        *,
        normalize=True,
        corpus="full",
    ) -> list[Evidence]:
        if (
            mode not in MODES
            or type(k) is not int
            or not 1 <= k <= 5
            or corpus not in {"full", "official"}
        ):
            raise ValueError("invalid_retrieval_settings")
        timings = {}
        try:
            return self._retrieve(
                query, principal, as_of, mode, k, normalize, corpus, timings
            )
        finally:
            if timings:
                note(stage_ms=timings)

    def _retrieve(
        self, query, principal, as_of, mode, k, normalize, corpus, timings
    ) -> list[Evidence]:
        if not isinstance(query, str) or not query.strip():
            raise QueryError("empty_question")
        clarification = clarify_date(query, as_of)
        if clarification:
            raise QueryError("date_conflict", clarification)
        query = prepare_query(query, tokenizers=self.tokenizers, normalize=normalize)
        allowed = {c.id: c for c in eligible_chunks(principal, as_of, store=self.store)}
        snapshot = self.store.snapshot(role=principal.role, as_of=as_of)
        if snapshot is None:
            return []
        official = {
            d["document_id"]
            for d in snapshot.documents
            if d["source_type"] == "official"
        }
        indices = [
            i
            for i, c in enumerate(snapshot.chunks)
            if c.id in allowed and (corpus == "full" or c.document_id in official)
        ]
        if not indices:
            return []
        chunks = [allowed[snapshot.chunks[i].id] for i in indices]
        vectors = snapshot.vectors[indices]
        embedder = self._model("embedding", timings)
        started = time.monotonic()
        embedded = np.asarray(embedder.embed([query]), dtype=np.float64)
        timings["embed"] = (time.monotonic() - started) * 1000
        if (
            embedded.shape != (1, vectors.shape[1])
            or not np.isfinite(embedded).all()
            or np.linalg.norm(embedded[0]) == 0
        ):
            raise ProviderError("invalid_embedding")
        query_vector = embedded[0] / np.linalg.norm(embedded[0])
        norms = np.linalg.norm(vectors, axis=1)
        scores = (vectors @ query_vector) / np.where(norms == 0, 1, norms)
        dense = sorted(
            zip(chunks, scores, strict=True),
            key=lambda pair: (-float(pair[1]), pair[0].id),
        )
        if mode == "dense":
            ranked = [(c.id, float(score)) for c, score in dense[:k]]
        else:
            lex = BM25Okapi([lexical_tokens(c.text) for c in chunks]).get_scores(
                lexical_tokens(query)
            )
            lexical = sorted(
                zip(chunks, lex, strict=True),
                key=lambda pair: (-float(pair[1]), pair[0].id),
            )
            fused = rrf([c.id for c, _ in dense], [c.id for c, _ in lexical])
            ranked = sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))[
                : self.candidate_limit
            ]
            if mode == "rerank":
                current = {
                    c.id: c for c in eligible_chunks(principal, as_of, store=self.store)
                }
                ranked = [(cid, score) for cid, score in ranked if cid in current]
                if not ranked:
                    return []
                values = None
                reranker = self._model("reranker", timings)
                timings["rerank"] = 0.0
                for representation in rerank_queries(query):
                    # 每次計分前重驗權；來源若中途撤回，不把舊正文送入下一次重排。
                    current = {
                        c.id: c
                        for c in eligible_chunks(principal, as_of, store=self.store)
                    }
                    if any(cid not in current for cid, _ in ranked):
                        raise ProviderError("corpus_changed")
                    started = time.monotonic()
                    clause_scores = np.asarray(
                        reranker.rerank(
                            representation, [current[cid].text for cid, _ in ranked]
                        ),
                        dtype=float,
                    )
                    timings["rerank"] += (time.monotonic() - started) * 1000
                    if (
                        clause_scores.shape != (len(ranked),)
                        or not np.isfinite(clause_scores).all()
                    ):
                        raise ProviderError("invalid_reranking")
                    values = (
                        clause_scores
                        if values is None
                        else np.maximum(values, clause_scores)
                    )
                ranked = sorted(
                    (
                        (item[0], float(score))
                        for item, score in zip(ranked, values, strict=True)
                    ),
                    key=lambda pair: (-pair[1], pair[0]),
                )
        current = {c.id: c for c in eligible_chunks(principal, as_of, store=self.store)}
        with self.store.connect() as db:
            active = self.store.active(db)
            if active is None or active["id"] != snapshot.generation_id:
                raise ProviderError("corpus_changed")
        return [
            Evidence(chunk=current[cid], score=score)
            for cid, score in ranked[:k]
            if cid in current
        ]


def retrieve(
    query: str, principal: Principal, as_of: date, mode: str, k: int = 5
) -> list[Evidence]:
    runner = Retriever()
    try:
        return runner.retrieve(query, principal, as_of, mode, k)
    finally:
        runner.close()
