"""證據式回答：授權、引用白名單及繁體輸出防線。"""

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import opencc
from pydantic import ValidationError

from hr_rag.audit import collect_context, collect_exchange, note, record_event
from hr_rag.citations import CitationNotFound, citation_details, read_citation
from hr_rag.context import ContextSettings, assemble_context
from hr_rag.contracts import Answer, Claim, Principal, QueryRequest
from hr_rag.generation import selected_generator
from hr_rag.policy import clarify_date
from hr_rag.providers import ProviderError
from hr_rag.query import QueryError, normalize_query
from hr_rag.retrieval import Retriever
from hr_rag.settings import PROJECT_ROOT

_ST_HASH = "9207708da9f2e2a248f39c457b2fccad26ec42e7efaf47a860e6900464f4cac5"


@lru_cache(maxsize=1)
def _simplified_only():
    raw = (Path(opencc.__file__).parent / "dictionary/STCharacters.txt").read_bytes()
    if version("opencc-python-reimplemented") != "0.1.7" or (
        hashlib.sha256(raw).hexdigest() != _ST_HASH
    ):
        raise ProviderError("not_configured")
    pairs = [line.split("\t", 1) for line in raw.decode().splitlines() if "\t" in line]
    traditional = {char for _, targets in pairs for char in targets.split()}
    # 教育部簡編本「雇」為正字，不能把OpenCC的偏好轉換當簡體專用。
    # https://dict.concised.moe.edu.tw/dictView.jsp?ID=16833&la=0&powerMode=0
    traditional.add("雇")
    # 后／里／干等本來也是繁體合法字；不做自動轉換或把歧義字當簡體專用字。
    return frozenset(source for source, _ in pairs if source not in traditional)


def contains_simplified(text: str) -> bool:
    return bool(set(text) & _simplified_only())


def validate_citations(answer: Answer, context) -> list[str]:
    allowed = {unit.id for unit in context.units}
    cited = set(answer.citations)
    used = {cid for claim in answer.claims for cid in claim.citation_ids}
    if not cited <= allowed or not used <= allowed:
        return ["unknown_citation"]
    if cited != used:
        return ["unused_citation"]
    return []


def _response(status, reason):
    return Answer(status=status, claims=(), citations=(), reason=reason)


def missing_form_identity(question: str, texts: list[str]) -> bool:
    """只處理明示名稱詢問；必要條件通過不等於完整語意支持。"""
    form = r"(?:表單|補件單|覆核單)"
    identity_question = (
        rf"(?:哪張|哪份|哪個|什麼|何種)(?:識別|專用|內部)?{form}"
        rf"|{form}(?:的)?(?:名稱|識別|代碼|叫什麼|是哪|是什麼)"
    )
    if not re.search(identity_question, question):
        return False
    for text in texts:
        if re.search(r"(?:表單|[\u4e00-\u9fff]{1,8}單)\s*[A-Za-z][A-Za-z0-9-]*", text):
            return False
        if re.search(r"表單(?:名稱|識別|代碼)\s*[：:]\s*[^，。；：？!?\n]{2,30}", text):
            return False
        for match in re.finditer(
            r"(?:使用|填寫|採用|提交|附)([^，。；：？!?\n]{2,20}?(?:表單|單))", text
        ):
            name = match[1].strip()
            if not re.fullmatch(
                r"(?:此|該|原|內部|相關|指定|一般|申請|補件|必要的?|本次的?)*(?:表單|單)",
                name,
            ):
                return False
    return True


class AnswerService:
    def __init__(self, *, retriever=None, generator=None, config=None, on_context=None):
        self.retriever = retriever or Retriever()
        self.generator = generator or selected_generator(
            on_exchange=collect_exchange
        )
        if config is None:
            selected = json.loads(
                (PROJECT_ROOT / "config/retrieval.selected.json").read_text("utf-8")
            )
            if selected["status"] != "stage4_passed":
                raise ValueError("retrieval_not_accepted")
            config = ContextSettings(**selected["context_settings"])
        self.config = config
        self.on_context = on_context

    def _current(self, context, principal, as_of):
        for unit in context.units:
            if (
                read_citation(principal, unit.id, as_of, store=self.retriever.store)
                != unit
            ):
                raise CitationNotFound()

    def _snapshot(self):
        try:
            with self.retriever.store.connect() as db:
                row = self.retriever.store.active(db)
            return (
                {"generation_id": row["id"], "manifest_sha256": row["manifest_hash"]}
                if row
                else None
            )
        except Exception:
            return None

    def _refuse(self, code, reason):
        note(refusal_code=code)
        return _response("insufficient", reason)

    def answer(self, request: QueryRequest, principal: Principal) -> Answer:
        phase = "prepare"
        try:
            if not isinstance(principal, Principal):
                raise ValueError("invalid_principal")
            principal = Principal.model_validate(principal.model_dump())
            request = QueryRequest.model_validate(
                request.model_dump() if isinstance(request, QueryRequest) else request
            )
            as_of = request.as_of or datetime.now(timezone(timedelta(hours=8))).date()
            note(as_of=as_of.isoformat(), mode=self.config.mode)
            try:
                note(normalized_question=normalize_query(request.question))
            except QueryError:
                pass
            clarification = clarify_date(request.question, as_of)
            if clarification:
                return self._refuse("date_clarification", clarification)
            note(snapshot=self._snapshot())
            started = time.monotonic()
            evidence = self.retriever.retrieve(
                request.question, principal, as_of, self.config.mode
            )
            note(
                candidate_ids=[item.chunk.id for item in evidence],
                stage_ms={"retrieve": (time.monotonic() - started) * 1000},
            )
            started = time.monotonic()
            context = assemble_context(
                evidence,
                principal,
                as_of,
                request.question,
                store=self.retriever.store,
                config=self.config,
                settings=getattr(self.generator, "settings", None),
                payload_builder=getattr(self.generator, "_payload", None),
            )
            blocked = [
                reason
                for reason in context.dropped_reasons
                if reason.endswith(
                    (":unauthorized_or_inactive", ":unauthorized_or_changed")
                )
            ]
            if blocked:
                # 檢索應只回傳有權候選；下游防線攔到即告警，證據已不送模型。
                record_event(
                    {
                        "stage": "guard",
                        "status": "error",
                        "error_code": "illegal_evidence",
                    }
                )
            self._current(context, principal, as_of)
            note(
                evidence_ids=[unit.id for unit in context.units],
                stage_ms={"assemble": (time.monotonic() - started) * 1000},
            )
            collect_context(context)
            if self.on_context:
                self.on_context(context)
            if not context.units:
                return self._refuse(
                    "no_evidence", "目前可用資料不足以回答，缺少適用的證據。"
                )
            started = time.monotonic()
            phase = "generate"
            generated = self.generator.generate(request.question, context)
            phase = "validate"
            note(stage_ms={"generate": (time.monotonic() - started) * 1000})
            generated = Answer.model_validate(generated.model_dump())
            problems = validate_citations(generated, context)
            simplified = any(
                contains_simplified(text)
                for text in [
                    *(c.text for c in generated.claims),
                    generated.reason or "",
                ]
            )
            note(validation={"citations": problems, "simplified": simplified})
            if (
                generated.status == "error"
                or (generated.status == "conflict" and not generated.claims)
                or problems
            ) or simplified:
                raise ProviderError("invalid_output")
            self._current(context, principal, as_of)
            if (
                re.search(r"我|本人|個人", request.question)
                and re.search(r"剩|餘額|結餘|余额|還有", request.question)
                or re.search(r"餘額|結餘|余额", request.question)
                and re.search(r"幾|多少|查詢", request.question)
            ) and re.search(r"假|特休", request.question):
                # 本語料只有規範與虛構流程，沒有任何個人假勤資料。
                return self._refuse(
                    "personal_record",
                    "目前可用資料不足以回答，缺少個人假勤與已休紀錄。",
                )
            if missing_form_identity(request.question, [u.text for u in context.units]):
                return self._refuse(
                    "form_identity",
                    "目前可用資料不足以回答，缺少所問表單名稱或識別的直接依據。",
                )
            claims = []
            for claim in generated.claims:
                types = {
                    citation_details(principal, cid, as_of, store=self.retriever.store)[
                        "source_type"
                    ]
                    for cid in claim.citation_ids
                }
                label = "＋".join(
                    label
                    for kind, label in (
                        ("official", "官方依據"),
                        ("company", "虛構公司流程"),
                    )
                    if kind in types
                )
                claims.append(
                    Claim(
                        text=f"【{label}】{claim.text}", citation_ids=claim.citation_ids
                    )
                )
            # 自由reason沒有引用映射，不作為展示事實的另一條通道。
            # 有支持的內容必須寫入claims，語意是否正確仍需人工評估。
            reason = None
            if generated.status in ("insufficient", "conflict"):
                note(
                    refusal_code="model_insufficient"
                    if generated.status == "insufficient"
                    else "conflict"
                )
            if generated.status == "insufficient":
                reason = (
                    "目前可用資料不足以回答。缺少適用規則或流程的完整依據；"
                    "下列主張僅涵蓋已有證據的部分。"
                )
            elif generated.status == "conflict":
                reason = "來源衝突，待人工核對。請比對下列主張所列的引用來源。"
            self._current(context, principal, as_of)
            return Answer(
                status=generated.status,
                claims=tuple(claims),
                citations=generated.citations,
                reason=reason,
            )
        except QueryError as error:
            if error.clarification:
                return self._refuse("date_clarification", error.clarification)
            note(error_code="invalid_input")
            return _response("error", "問題過長或格式不符，請縮短後重試。")
        except ProviderError as error:
            messages = {
                "not_configured": "生成服務未設定。",
                "cost_limit": "已達生成費用上限。",
                "invalid_output": "生成輸出格式不符，無法顯示答案。",
                "timeout": "生成服務逾時，暫時無法回答。",
            }
            note(error_code=str(error))
            try:
                # 生成器自身已記錄的錯誤不重複計入連續模型失敗。
                if getattr(error, "trace_id", None) is None:
                    record_event(
                        {
                            "stage": "generate" if phase == "generate" else "runtime",
                            "status": "error",
                            "error_code": str(error),
                        }
                    )
            except Exception:
                return _response("error", "稽核紀錄失敗，暫時無法回答。")
            return _response(
                "error", messages.get(str(error), "生成服務暫時無法使用。")
            )
        except CitationNotFound:
            note(error_code="citation_expired")
            try:
                record_event(
                    {
                        "stage": "guard",
                        "status": "error",
                        "error_code": "illegal_evidence",
                    }
                )
            except Exception:
                pass
            return _response("error", "引用證據已失效，請重新查詢。")
        except (ValidationError, ValueError, TypeError, AttributeError):
            note(error_code="invalid_input")
            return _response("error", "問題、日期或輸出格式不符。")
        except Exception:
            note(error_code="service_error")
            return _response("error", "服務暫時無法使用。")


def answer(request: QueryRequest, principal: Principal) -> Answer:
    runner = AnswerService()
    try:
        return runner.answer(request, principal)
    finally:
        runner.retriever.close()
