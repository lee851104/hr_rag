"""引用ID只有定位作用，每次讀取都重新驗權。"""

import json
from datetime import date

from hr_rag.contracts import Chunk, Principal
from hr_rag.policy import authorized_units
from hr_rag.storage import CorpusStore


class CitationNotFound(Exception):
    def __init__(self):
        super().__init__("citation_not_found")


def read_citation(
    principal: Principal,
    citation_id: str,
    as_of: date,
    *,
    store: CorpusStore | None = None,
) -> Chunk:
    chunks = authorized_units(principal, as_of, store=store, citation_id=citation_id)
    if not chunks:
        raise CitationNotFound()
    return chunks[0]


def citation_details(principal, citation_id, as_of, *, store=None):
    """來源資訊只在引用重新驗權後取出；不信任模型提供的標題或分類。"""
    store = store or CorpusStore()
    chunk = read_citation(principal, citation_id, as_of, store=store)
    with store.connect() as db:
        row = db.execute(
            "SELECT d.record_json FROM documents d JOIN active a "
            "ON d.generation_id=a.generation_id "
            "WHERE d.document_id=? AND d.version_id=?",
            (chunk.document_id, chunk.version_id),
        ).fetchone()
    if row is None:
        raise CitationNotFound()
    document = json.loads(row[0])
    if read_citation(principal, citation_id, as_of, store=store) != chunk:
        raise CitationNotFound()
    return {
        "citation_id": citation_id,
        **{
            name: document[name]
            for name in (
                "title",
                "source_type",
                "source_url",
                "is_synthetic",
                "document_id",
                "version_id",
            )
        },
        "section_id": chunk.section_id,
        "effective_from": chunk.effective_from.isoformat(),
        "effective_to": chunk.effective_to.isoformat() if chunk.effective_to else None,
    }
