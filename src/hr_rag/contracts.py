"""跨模組資料契約；不包含登入、檢索或法律判斷。"""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Role = Literal["employee", "manager", "hr"]
NonEmpty = Annotated[str, Field(min_length=1)]


def calendar_date_only(value):
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    raise ValueError("日期必須是YYYY-MM-DD，不接受時間戳或日期時間")


CalendarDate = Annotated[date, BeforeValidator(calendar_date_only)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Principal(Contract):
    user_id: NonEmpty
    role: Role


class QueryRequest(Contract):
    question: NonEmpty
    as_of: CalendarDate | None = None


class EffectiveInterval(Contract):
    effective_from: CalendarDate | None
    effective_to: CalendarDate | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to <= self.effective_from
        ):
            raise ValueError("有效區間必須是含起日、不含迄日的正長度區間")
        return self


class DocumentVersion(EffectiveInterval):
    document_id: NonEmpty
    version_id: NonEmpty
    title: NonEmpty
    source_type: Literal["official", "company"]
    source_url: str | None
    is_synthetic: bool
    published_at: CalendarDate | None
    revised_at: CalendarDate | None
    fetched_at: datetime
    date_evidence: NonEmpty
    allowed_roles: tuple[Role, ...]
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    review_status: Literal["pending", "verified", "withdrawn"]
    raw_path: NonEmpty
    normalized_path: NonEmpty
    source_publisher: NonEmpty
    maintenance_owner: NonEmpty
    last_reviewed_at: CalendarDate | None
    next_review_due: CalendarDate | None


class Chunk(EffectiveInterval):
    id: NonEmpty
    document_id: NonEmpty
    version_id: NonEmpty
    section_id: NonEmpty
    parent_id: NonEmpty
    text: NonEmpty
    allowed_roles: tuple[Role, ...]


class Evidence(Contract):
    chunk: Chunk
    score: Annotated[float, Field(allow_inf_nan=False)]


class ContextBundle(Contract):
    units: tuple[Chunk, ...]
    # 每個實際輸入單位對應一或多個原始證據定位，供階段4組裝。
    citation_map: dict[str, tuple[str, ...]]
    token_count: Annotated[int, Field(ge=0)]
    dropped_reasons: tuple[str, ...]
    config_hash: NonEmpty

    @model_validator(mode="after")
    def consistent_sources(self):
        ids = [unit.id for unit in self.units]
        if len(ids) != len(set(ids)) or set(ids) != set(self.citation_map):
            raise ValueError("上下文單位必須唯一且完整對應引用映射")
        if any(not refs for refs in self.citation_map.values()):
            raise ValueError("引用映射不可缺少來源定位")
        return self


class Claim(Contract):
    text: NonEmpty
    citation_ids: tuple[NonEmpty, ...]


class Answer(Contract):
    status: Literal["answered", "insufficient", "conflict", "error"]
    claims: tuple[Claim, ...]
    citations: tuple[NonEmpty, ...]
    reason: str | None

    @model_validator(mode="after")
    def coherent_answer(self):
        if self.status == "answered" and (not self.claims or not self.citations):
            raise ValueError("已回答狀態需要主張與引用")
        if self.status != "answered" and not self.reason:
            raise ValueError("非完整回答必須交代原因")
        if any(not claim.citation_ids for claim in self.claims):
            raise ValueError("主張必須具引用")
        if any(
            cid not in self.citations
            for claim in self.claims
            for cid in claim.citation_ids
        ):
            raise ValueError("主張引用必須出現在答案引用清單")
        return self
