"""以固定本機 tokenizer 切片；完整父段與原文位置永遠保留。"""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass

from tokenizers import Tokenizer

from hr_rag.contracts import Chunk, DocumentVersion
from hr_rag.settings import PROJECT_ROOT

CHUNKING_VERSION = "paragraph-sentence-dual-tokenizer-v2"
TOKENIZER_PATH = PROJECT_ROOT / ".cache/models/embedding/tokenizer.json"
RERANKER_TOKENIZER_PATH = PROJECT_ROOT / ".cache/models/reranker/tokenizer.json"


class ChunkingError(ValueError):
    """僅包含固定錯誤碼，不帶來源正文。"""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def load_tokenizer(role="embedding") -> Tokenizer:
    if role not in {"embedding", "reranker"}:
        raise ValueError("invalid_tokenizer_role")
    path = TOKENIZER_PATH if role == "embedding" else RERANKER_TOKENIZER_PATH
    return unbounded_tokenizer(Tokenizer.from_file(str(path)))


def unbounded_tokenizer(tokenizer) -> Tokenizer:
    # 使用獨立計數實例，不能受呼叫者的截斷／padding設定或後續變更影響。
    tokenizer = Tokenizer.from_str(tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def token_count(tokenizer, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=True).ids)


@dataclass(frozen=True)
class LocatedChunk:
    chunk: Chunk
    start: int
    end: int
    token_count: int


@dataclass(frozen=True)
class ChunkPlan:
    parents: tuple[Chunk, ...]
    children: tuple[LocatedChunk, ...]


def _trim_span(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def encoder_token_count(tokenizers, text):
    return max(token_count(tokenizer, text) for tokenizer in tokenizers)


def _spans(text, tokenizers, limit):
    units = []
    for paragraph in re.finditer(r"[^\n]+", text):
        start, end = _trim_span(text, *paragraph.span())
        if start == end:
            continue
        if encoder_token_count(tokenizers, text[start:end]) <= limit:
            units.append((start, end))
            continue
        for sentence in re.finditer(r'.+?(?:[。！？!?]+[」』”’"]*|$)', text[start:end]):
            left, right = _trim_span(
                text, start + sentence.start(), start + sentence.end()
            )
            if encoder_token_count(tokenizers, text[left:right]) > limit:
                raise ChunkingError("sentence_over_limit")
            units.append((left, right))
    packed = []
    for start, end in units:
        if (
            packed
            and encoder_token_count(tokenizers, text[packed[-1][0] : end]) <= limit
        ):
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return packed


def plan_chunks(
    document: DocumentVersion,
    text: str,
    *,
    tokenizer=None,
    reranker_tokenizer=None,
    max_tokens=400,
) -> ChunkPlan:
    if type(max_tokens) is not int or not 3 <= max_tokens <= 400:
        raise ChunkingError("invalid_chunk_limit")
    tokenizers = (
        unbounded_tokenizer(tokenizer) if tokenizer is not None else load_tokenizer(),
        unbounded_tokenizer(reranker_tokenizer)
        if reranker_tokenizer is not None
        else load_tokenizer("reranker"),
    )
    return plan_with_tokenizers(document, text, tokenizers, max_tokens=max_tokens)


def plan_with_tokenizers(document, text, tokenizers, *, max_tokens=400):
    """共用匯入開始時已停用截斷的兩個計數實例，避免逐文件重載模型詞表。"""
    normalized = json.loads(text)
    if (
        normalized["document_id"] != document.document_id
        or normalized["version_id"] != document.version_id
    ):
        raise ChunkingError("source_identity_mismatch")
    intervals = {s.section_id: s for s in getattr(document, "indexed_sections", ())}
    parents, children = [], []
    for section in normalized["sections"]:
        section_id, body = section["section_id"], section["text"].strip()
        interval = intervals.get(section_id, document)
        if interval.effective_from is None or document.effective_from is None:
            raise ChunkingError("unknown_date")
        identity = [document.document_id, document.version_id, section_id]
        parent_id = "p-" + digest([*identity, body])
        common = dict(
            document_id=document.document_id,
            version_id=document.version_id,
            section_id=section_id,
            parent_id=parent_id,
            allowed_roles=document.allowed_roles,
            effective_from=interval.effective_from,
            effective_to=interval.effective_to,
        )
        parents.append(Chunk(id=parent_id, text=body, **common))
        occurrences = Counter()
        for start, end in _spans(body, tokenizers, max_tokens):
            part = body[start:end]
            occurrence = occurrences[part]
            occurrences[part] += 1
            chunk = Chunk(
                id="c-" + digest([*identity, part, occurrence]), text=part, **common
            )
            children.append(
                LocatedChunk(chunk, start, end, encoder_token_count(tokenizers, part))
            )
    if not children:
        raise ChunkingError("empty_document")
    return ChunkPlan(tuple(parents), tuple(children))


def chunk_document(document: DocumentVersion, text: str) -> list[Chunk]:
    return [item.chunk for item in plan_chunks(document, text).children]
