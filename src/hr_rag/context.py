"""完整父段組裝、重驗權、相關度篩選與實際provider提示預算。"""

import re
from dataclasses import asdict, dataclass
from datetime import date

from hr_rag.citations import CitationNotFound, read_citation
from hr_rag.contracts import ContextBundle, Evidence, Principal
from hr_rag.corpus.chunking import digest
from hr_rag.providers import ProviderError, build_openai_payload
from hr_rag.query import synonyms_hash
from hr_rag.settings import OpenAISettings
from hr_rag.storage import CorpusStore

_LEAVE_NAMES = {
    "陪產檢及陪產假": "陪產假",
    "陪產檢假": "陪產假",
    "陪產假": "陪產假",
    "普通傷病假": "病假",
    "傷病假": "病假",
    "病假": "病假",
    "公傷病假": "公傷病假",
    "家庭照顧假": "家庭照顧假",
    "特別休假": "特別休假",
    "特休": "特別休假",
    "補休": "補休",
    "產檢假": "產檢假",
    "產假": "產假",
    "生理假": "生理假",
    "婚假": "婚假",
    "喪假": "喪假",
    "事假": "事假",
    "公假": "公假",
}
_LEAVE_PATTERN = "|".join(sorted(_LEAVE_NAMES, key=len, reverse=True))


def leave_scope_mismatch(question: str, text: str) -> bool:
    """僅排除明確不同假別的給假條文；不使用題號、金標或人工標註。"""

    def kinds(value):
        return {_LEAVE_NAMES[match[0]] for match in re.finditer(_LEAVE_PATTERN, value)}

    requested = kinds(question)
    if len(requested) != 1 or any(
        word in question
        for word in ("不", "非", "無", "未", "沒", "除", "比較", "差別", "差異")
    ):
        return False
    if any(
        word in text
        for word in (
            "另有規定",
            "從其規定",
            "依相關法令",
            "依其他法令",
            "準用",
            "依本法",
            "依第",
            "各類請假",
            "所有請假",
            "各種請假",
            "申請流程",
            "申請",
            "通知",
            "補件",
            "證明",
            "核准",
            "主管",
            "表單",
            "程序",
            "窗口",
            "緊急",
            "委託",
            "提出",
            "不得",
        )
    ):
        return False
    # 不把混合的一般程序或跨法規條款誤判為單一假別的給假規則。
    if re.search(r"依[^。；;\n]{0,12}(?:法令|法律|本法|第\S{1,8}條)", text):
        return False
    sentences = [part.strip() for part in re.split(r"[。；;\n]", text) if part.strip()]
    if any(not kinds(part) for part in sentences):
        return False
    grants_leave = re.search(r"(?:得請|給予)\s*(?:" + _LEAVE_PATTERN + ")", text)
    return bool(grants_leave and not requested.intersection(kinds(text)))


@dataclass(frozen=True)
class ContextSettings:
    mode: str = "dense"
    context_max_units: int = 3
    min_relevance: float = 0.75
    leave_scope_filter: bool = False

    def __post_init__(self):
        if (
            self.mode not in {"dense", "hybrid", "rerank"}
            or type(self.context_max_units) is not int
            or not 1 <= self.context_max_units <= 5
            or type(self.leave_scope_filter) is not bool
        ):
            raise ValueError("invalid_context_settings")
        import math

        if not math.isfinite(self.min_relevance) or (
            self.mode != "rerank" and not 0 <= self.min_relevance <= 1
        ):
            raise ValueError("invalid_relevance")


def assemble_context(
    evidence: list[Evidence],
    principal: Principal,
    as_of: date,
    question: str,
    *,
    store=None,
    config=None,
    settings=None,
    payload_builder=None,
) -> ContextBundle:
    store = store or CorpusStore()
    config = config or ContextSettings()
    settings = settings or OpenAISettings()
    build = payload_builder or (
        lambda question, context: build_openai_payload(question, context, settings)
    )
    config_hash = digest(
        {
            "assembly": "whole-parent-v2",
            "leave_scope_rule": "explicit-grant-v1",
            "citation_transport": "short-id-v1",
            "filter": asdict(config),
            "synonyms": synonyms_hash(),
            "settings": settings.model_dump(mode="json", exclude={"cost_ledger_path"}),
        }
    )
    dropped = []

    def bundle(units, mapping, tokens=0):
        return ContextBundle(
            units=tuple(units),
            citation_map=mapping,
            token_count=tokens,
            dropped_reasons=tuple(dropped),
            config_hash=config_hash,
        )

    # 即使沒有證據，也先檢查系統提示、schema與原問題的完整成本。
    build(question, bundle([], {}))
    candidates = []
    by_parent = {}
    for item in evidence:
        try:
            child = read_citation(principal, item.chunk.id, as_of, store=store)
            parent = read_citation(principal, child.parent_id, as_of, store=store)
            if (parent.document_id, parent.version_id, parent.section_id) != (
                child.document_id,
                child.version_id,
                child.section_id,
            ):
                raise CitationNotFound()
        except CitationNotFound:
            dropped.append(f"{item.chunk.id}:unauthorized_or_inactive")
            continue
        if parent.id in by_parent:
            entry = by_parent[parent.id]
            if child.id not in entry["refs"]:
                entry["refs"].append(child.id)
            continue
        entry = {"parent": parent, "score": item.score, "refs": [child.id]}
        by_parent[parent.id] = entry
        candidates.append(entry)
    units = []
    mapping = {}
    selected = 0
    first_score = candidates[0]["score"] if candidates else 0
    for rank, entry in enumerate(candidates):
        parent = entry["parent"]
        score = entry["score"]
        relevance = (
            score
            if config.mode == "rerank"
            else (score / first_score if first_score > 0 else (1 if rank == 0 else 0))
        )
        if rank > 0 and (
            selected >= config.context_max_units or relevance < config.min_relevance
        ):
            dropped.append(f"{parent.id}:relevance_filter")
            continue
        selected += 1
        if (
            rank > 0
            and config.leave_scope_filter
            and leave_scope_mismatch(question, parent.text)
        ):
            dropped.append(f"{parent.id}:leave_scope_mismatch")
            continue
        proposed = units + [parent]
        proposed_map = {**mapping, parent.id: tuple(entry["refs"])}
        try:
            build(question, bundle(proposed, proposed_map))
        except ProviderError as error:
            if str(error) != "budget":
                raise
            dropped.append(f"{parent.id}:whole_unit_over_budget")
            continue
        units = proposed
        mapping = proposed_map
    # 完成計數後再重驗，避免組裝中途撤回的舊物件成為模型輸入。
    for unit in tuple(units):
        try:
            current = read_citation(principal, unit.id, as_of, store=store)
            if current != unit:
                raise CitationNotFound()
        except CitationNotFound:
            units.remove(unit)
            mapping.pop(unit.id)
            dropped.append(f"{unit.id}:unauthorized_or_changed")
    _, tokens, _ = build(question, bundle(units, mapping))
    return bundle(units, mapping, tokens)
