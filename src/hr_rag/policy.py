"""所有候選／引用共用前置授權；Principal只接受伺服器驗證結果。"""

import re
from datetime import date

from pydantic import ValidationError

from hr_rag.contracts import Chunk, Principal
from hr_rag.storage import CorpusStore


def authorized_units(
    principal: Principal,
    as_of: date,
    *,
    store: CorpusStore | None = None,
    citation_id: str | None = None,
) -> list[Chunk]:
    """每次讀現行世代、ACL、日期與撤回；不快取授權結果。"""
    if not isinstance(principal, Principal) or type(as_of) is not date:
        raise ValueError("invalid_authorization_context")
    store = store or CorpusStore()
    with store.connect() as db:
        db.execute("BEGIN")
        query = (
            "SELECT u.chunk_json FROM units u "
            "JOIN active a ON u.generation_id=a.generation_id WHERE "
        )
        if citation_id is None:
            rows = db.execute(query + "u.parent=0 ORDER BY u.row_index,u.id")
        else:
            rows = db.execute(query + "u.id=?", (citation_id,))
        withdrawn = {tuple(r) for r in db.execute("SELECT * FROM withdrawals")}
        result = []
        for row in rows:
            try:
                chunk = Chunk.model_validate_json(row[0])
            except ValidationError:
                # 缺ACL／日期或不合法metadata一律排除，不能以預設角色補足。
                continue
            if (
                principal.role in chunk.allowed_roles
                and (chunk.document_id, chunk.version_id) not in withdrawn
                and chunk.effective_from is not None
                and chunk.effective_from <= as_of
                and (chunk.effective_to is None or as_of < chunk.effective_to)
            ):
                result.append(chunk)
        return result


def eligible_chunks(
    principal: Principal, as_of: date, *, store: CorpusStore | None = None
) -> list[Chunk]:
    return authorized_units(principal, as_of, store=store)


_DATES = re.compile(
    r"(?<!\d)(?:(?P<roc>民國)\s*)?(?P<year>\d{2,4})"
    r"(?:\s*年(?:\s*(?P<month>\d{1,2})\s*月"
    r"(?:\s*(?P<day>\d{1,2})\s*日)?)?"
    r"|-(?P<iso_month>\d{2})(?:-(?P<iso_day>\d{2}))?)(?!\d)"
)
_DURATION_PREFIX = re.compile(
    r"(?:年資|任職|工作|服務|受僱|到職|滿|達|超過|未滿|不足)"
    r"(?:已|屆|連續|約|近|滿|達|超過|未滿|不足|累計|\s)*$"
)
_DURATION_SUFFIX = re.compile(r"^\s*(?:的)?(?:年資|資歷|工作經驗)")


def clarify_date(question: str, as_of: date) -> str | None:
    """明確日期按日／月／年比較；相對說法不推算、不改查詢日期。"""
    if type(as_of) is not date:
        raise ValueError("invalid_date")
    for match in _DATES.finditer(question):
        # 年資期間不當曆年；明示民國、ISO、四位年及完整年月日優先。
        if (
            not match["roc"]
            and match["iso_month"] is None
            and len(match["year"]) < 4
            and match["day"] is None
            and (
                _DURATION_PREFIX.search(question[: match.start()])
                or _DURATION_SUFFIX.match(question[match.end() :])
            )
        ):
            continue
        year = int(match["year"])
        if match["roc"] or (len(match["year"]) <= 3 and match["iso_month"] is None):
            year += 1911
        month = match["month"] or match["iso_month"]
        day = match["day"] or match["iso_day"]
        try:
            date(year, int(month or 1), int(day or 1))
        except ValueError:
            return (
                f"問題「{question}」含無效日期「{match[0]}」；"
                f"查詢日期為{as_of.isoformat()}，請釐清。"
            )
        if (
            year != as_of.year
            or (month and int(month) != as_of.month)
            or (day and int(day) != as_of.day)
        ):
            return (
                f"問題「{question}」指定「{match[0]}」，"
                f"與查詢日期{as_of.isoformat()}不同，請釐清採用日期。"
            )
    return None
