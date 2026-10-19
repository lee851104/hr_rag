"""一般事件只存白名單診斷欄位；完整問題／模型交換存受限追溯，可重播與清除。"""

import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from hr_rag.contracts import Answer
from hr_rag.settings import PROJECT_ROOT

STAGES = {"embed", "rerank", "generate", "runtime", "query", "guard"}
STATUSES = {"ok", "error"}
ERROR_CODES = {
    "timeout",
    "invalid_output",
    "unavailable",
    "budget",
    "audit_failure",
    "rate_limited",
    "cost_limit",
    "not_configured",
    "illegal_evidence",
    "invalid_input",
    "citation_expired",
    "service_error",
}
ROLES = {"employee", "manager", "hr"}
MODES = {"dense", "hybrid", "rerank"}
ANSWER_STATUSES = {"answered", "insufficient", "conflict", "error"}
REFUSAL_CODES = {
    "no_evidence",
    "date_clarification",
    "personal_record",
    "form_identity",
    "model_insufficient",
    "conflict",
}
STAGE_KEYS = {"retrieve", "assemble", "generate", "validate", "total"}
RETENTION_SECONDS = 30 * 86400
SECRET_KEYS = {"authorization", "api_key", "headers", "password", "cookie"}
SECRET_TEXT = re.compile(r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+", re.IGNORECASE)
# 進行中查詢的(trace_id, collector)；每個請求執行緒各自一份。
_TRACE = ContextVar("query_trace", default=None)

_PRIVATE_MODEL_CALL = ContextVar("private_model_call", default=False)


@contextmanager
def private_model_logs():
    previous = logging.getLogRecordFactory()
    if not getattr(previous, "_hr_rag_private_factory", False):

        def factory(*args, **kwargs):
            record = previous(*args, **kwargs)
            if _PRIVATE_MODEL_CALL.get() and record.name.split(".")[0] in {
                "openai",
                "httpx2",
                "httpcore2",
            }:
                # 在LogRecord建立時遮蔽，連稍後lazy import的logger亦受保護。
                record.msg = "模型傳輸診斷已遮蔽"
                record.args = ()
                record.exc_info = None
                record.exc_text = None
                record.stack_info = None
            return record

        factory._hr_rag_private_factory = True
        logging.setLogRecordFactory(factory)
    # Factory保留但只處理當前呼叫的ContextVar；不影響其他執行緒的日誌。
    token = _PRIVATE_MODEL_CALL.set(True)
    try:
        yield
    finally:
        _PRIVATE_MODEL_CALL.reset(token)


def safe_usage(value):
    """只接受API用量數值，不將任意巢狀欄位帶進一般日誌。"""
    if not isinstance(value, dict):
        return None
    result = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        number = value.get(name)
        if type(number) is not int or number < 0:
            return None
        result[name] = number
    for parent, child in (
        ("input_tokens_details", "cached_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
    ):
        detail = value.get(parent)
        number = detail.get(child) if isinstance(detail, dict) else None
        if number is not None and (type(number) is not int or number < 0):
            return None
        result[parent] = {child: number}
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        return None
    for parent, child, total in (
        ("input_tokens_details", "cached_tokens", "input_tokens"),
        ("output_tokens_details", "reasoning_tokens", "output_tokens"),
    ):
        if result[parent][child] is not None and result[parent][child] > result[total]:
            return None
    return result


def _safe_identifier(value):
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value):
        if not value.startswith("sk-"):
            return value
    return None


def _safe_ids(value):
    if not isinstance(value, (list, tuple)) or len(value) > 50:
        return None
    ids = [_safe_identifier(item) for item in value]
    return ids if all(ids) else None


def _hex64(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    return None


def _iso_date(value):
    try:
        return date.fromisoformat(value).isoformat() if len(value) == 10 else None
    except (TypeError, ValueError):
        return None


def _stage_ms(value):
    if not isinstance(value, dict):
        return None
    return {
        name: number
        for name, number in value.items()
        if name in STAGE_KEYS
        and type(number) in (int, float)
        and math.isfinite(number)
        and number >= 0
    }


def _snapshot(value):
    if not isinstance(value, dict) or set(value) != {
        "generation_id",
        "manifest_sha256",
    }:
        return None
    clean = {k: _safe_identifier(v) for k, v in value.items()}
    return clean if all(clean.values()) else None


def _uuid(value):
    try:
        return str(UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def record_event(event: dict, *, trace_id: str | None = None) -> str:
    trace_id = _uuid(trace_id) or str(uuid4())
    current = _TRACE.get()
    duration = event.get("duration_ms")
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or duration < 0
    ):
        duration = None
    row = {
        "trace_id": trace_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "stage": event.get("stage") if event.get("stage") in STAGES else None,
        "status": event.get("status") if event.get("status") in STATUSES else None,
        "error_code": (
            event.get("error_code") if event.get("error_code") in ERROR_CODES else None
        ),
        "duration_ms": duration,
        "cost": (
            event.get("cost")
            if type(event.get("cost")) in (int, float)
            and math.isfinite(event["cost"])
            and event["cost"] >= 0
            else None
        ),
        "response_id": _safe_identifier(event.get("response_id")),
        "model": _safe_identifier(event.get("model")),
        "usage": safe_usage(event.get("usage")),
        "input_token_delta": (
            event.get("input_token_delta")
            if type(event.get("input_token_delta")) is int
            else None
        ),
        "safety_margin": (
            event.get("safety_margin")
            if type(event.get("safety_margin")) is int and event["safety_margin"] >= 0
            else None
        ),
        "query_id": current[0] if current and current[0] != trace_id else None,
    }
    if row["stage"] in {"query", "guard"}:
        row |= {
            "user_ref": _hex64(event.get("user_ref")),
            "role": event.get("role") if event.get("role") in ROLES else None,
            "as_of": _iso_date(event.get("as_of")),
            "mode": event.get("mode") if event.get("mode") in MODES else None,
            "snapshot": _snapshot(event.get("snapshot")),
            "candidate_ids": _safe_ids(event.get("candidate_ids")),
            "evidence_ids": _safe_ids(event.get("evidence_ids")),
            "response_ids": _safe_ids(event.get("response_ids")),
            "prompt_sha256": _hex64(event.get("prompt_sha256")),
            "settings_sha256": _hex64(event.get("settings_sha256")),
            "stage_ms": _stage_ms(event.get("stage_ms")),
            "answer_status": (
                event.get("answer_status")
                if event.get("answer_status") in ANSWER_STATUSES
                else None
            ),
            "refusal_code": (
                event.get("refusal_code")
                if event.get("refusal_code") in REFUSAL_CODES
                else None
            ),
        }
    path = Path(os.environ.get("HR_RAG_EVENT_PATH", "reports/events.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    return trace_id


class CostLedger:
    """跨實例／程序的持久累計；未知用量保留上限，不假填實際成本。"""

    def __init__(self, path: Path):
        self.path = path

    def reserve(self, amount: Decimal, limit: Decimal) -> str | None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS costs "
                "(id TEXT PRIMARY KEY, amount TEXT NOT NULL, settled INTEGER NOT NULL)"
            )
            rows = db.execute("SELECT amount FROM costs").fetchall()
            total = sum((Decimal(row[0]) for row in rows), Decimal(0))
            if total >= limit or total + amount > limit:
                return None
            ticket = str(uuid4())
            db.execute("INSERT INTO costs VALUES (?, ?, 0)", (ticket, str(amount)))
            return ticket

    def settle(self, ticket: str, amount: Decimal):
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute(
                "UPDATE costs SET amount = ?, settled = 1 WHERE id = ? AND settled = 0",
                (str(amount), ticket),
            )
            if cursor.rowcount != 1:
                raise ValueError("費用預留不存在或已結算")


# ---- 受限追溯 ----


def note(**values):
    """AnswerService回報階段資訊；不在追溯範圍內時不做事。"""
    current = _TRACE.get()
    if current is None:
        return
    notes = current[1]["notes"]
    for name, value in values.items():
        if name == "stage_ms":
            notes.setdefault("stage_ms", {}).update(value)
        else:
            notes[name] = value


def collect_exchange(exchange):
    current = _TRACE.get()
    if current is not None:
        current[1]["exchanges"].append(exchange)


def collect_context(context):
    current = _TRACE.get()
    if current is not None:
        current[1]["contexts"].append(context)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def input_hash(exchanges):
    requests = [exchange.get("request") for exchange in exchanges]
    return hashlib.sha256(_canonical(requests).encode("utf-8")).hexdigest()


def _scrub(value):
    if isinstance(value, dict):
        return {
            name: _scrub(item)
            for name, item in value.items()
            if str(name).lower() not in SECRET_KEYS
        }
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


class TraceStore:
    """本機開發者可讀的受限追溯；內容以SHA256防竄改，預設保存30天。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(
            path
            or os.environ.get("HR_RAG_TRACE_PATH")
            or PROJECT_ROOT / ".runtime/audit-private/traces.sqlite3"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS traces (trace_id TEXT PRIMARY KEY, "
                "user_ref TEXT NOT NULL, created_at INTEGER NOT NULL, "
                "expires_at INTEGER NOT NULL, content TEXT NOT NULL, "
                "content_sha256 TEXT NOT NULL)"
            )
        key_path = self.path.parent / "pseudonym.key"
        if not key_path.exists():
            try:
                with key_path.open("xb") as stream:
                    stream.write(secrets.token_bytes(32))
            except FileExistsError:
                pass
        self._key = key_path.read_bytes()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def user_ref(self, user_id: str) -> str:
        """去識別化：本機金鑰HMAC，事件與追溯都不存帳號名稱。"""
        return hmac.new(self._key, user_id.encode("utf-8"), "sha256").hexdigest()

    def save(self, trace: dict):
        content = _canonical(_scrub(trace))
        if SECRET_TEXT.search(content):
            raise ValueError("secret_in_trace")
        with self.connect() as db:
            db.execute(
                "INSERT INTO traces VALUES (?,?,?,?,?,?)",
                (
                    trace["trace_id"],
                    trace["user_ref"],
                    trace["created_at"],
                    trace["expires_at"],
                    content,
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                ),
            )

    def get(self, trace_id: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT content,content_sha256 FROM traces WHERE trace_id=?",
                (str(trace_id),),
            ).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row[0].encode("utf-8")).hexdigest() != row[1]:
            raise ValueError("trace_tampered")
        return json.loads(row[0])

    def load(self, trace_id: str) -> dict:
        trace = self.get(trace_id)
        if trace is None:
            raise ValueError("trace_not_found")
        return trace

    def owned(self, trace_id: str, user_id: str):
        """一般使用者只取本人紀錄；他人與不存在同樣回None。"""
        if _uuid(trace_id) is None:
            return None
        trace = self.get(trace_id)
        if trace is None or not hmac.compare_digest(
            trace["user_ref"], self.user_ref(user_id)
        ):
            return None
        return trace

    def recent(self, user_id: str, limit: int = 20) -> list[dict]:
        """本人最近查詢（新的在前）；只回問題、日期與狀態，不含證據。"""
        with self.connect() as db:
            rows = db.execute(
                "SELECT trace_id FROM traces WHERE user_ref=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (self.user_ref(user_id), limit),
            ).fetchall()
        items = []
        for (trace_id,) in rows:
            trace = self.get(trace_id)
            items.append(
                {
                    "trace_id": trace["trace_id"],
                    "question": trace["question"],
                    "as_of": trace["as_of"],
                    "status": trace["answer"]["status"],
                    "error_code": trace.get("error_code"),
                    "created_at": trace["created_at"],
                }
            )
        return items

    def purge(self, *, before: datetime) -> int:
        with self.connect() as db:
            return db.execute(
                "DELETE FROM traces WHERE created_at<?", (int(before.timestamp()),)
            ).rowcount

    def purge_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self.connect() as db:
            return db.execute(
                "DELETE FROM traces WHERE expires_at<=?", (int(now),)
            ).rowcount


def _sum_usage(exchanges):
    usages = [safe_usage(e.get("usage")) for e in exchanges]
    if not usages or any(u is None for u in usages):
        return None
    total = {k: sum(u[k] for u in usages) for k in ("input_tokens", "output_tokens")}
    total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    for parent, child in (
        ("input_tokens_details", "cached_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
    ):
        values = [u[parent][child] for u in usages]
        total[parent] = {child: None if None in values else sum(values)}
    return total


def _sum_cost(exchanges):
    costs = [e.get("cost") for e in exchanges]
    if not costs or any(type(c) not in (int, float) for c in costs):
        return None
    return sum(costs)


def _settings_json(generator):
    settings = getattr(generator, "settings", None)
    if settings is None:
        return None
    return settings.model_dump(mode="json", exclude={"cost_ledger_path"})


def traced_answer(service, request, principal, *, traces: TraceStore):
    """回答並寫入受限追溯；追溯或事件寫入失敗時不回傳成功答案。"""
    trace_id = str(uuid4())
    collector = {"exchanges": [], "contexts": [], "notes": {}}
    token = _TRACE.set((trace_id, collector))
    start = time.monotonic()
    try:
        answer = service.answer(request, principal)
    finally:
        _TRACE.reset(token)
    total_ms = (time.monotonic() - start) * 1000
    notes = collector["notes"]
    exchanges = [_scrub(e) for e in collector["exchanges"]]
    context = collector["contexts"][-1] if collector["contexts"] else None
    generator = getattr(service, "generator", None)
    prompt = getattr(generator, "SYSTEM", None)
    created = int(time.time())
    try:
        settings_json = _settings_json(generator)
        user_ref = traces.user_ref(principal.user_id)
        trace = {
            "trace_id": trace_id,
            "created_at": created,
            "expires_at": created + RETENTION_SECONDS,
            "user_ref": user_ref,
            "role": principal.role,
            "as_of": notes.get("as_of")
            or (request.as_of.isoformat() if request.as_of else None),
            "question": request.question,
            "normalized_question": notes.get("normalized_question"),
            "snapshot": notes.get("snapshot"),
            "mode": notes.get("mode"),
            "candidate_ids": notes.get("candidate_ids"),
            "dropped_reasons": list(context.dropped_reasons) if context else None,
            "context": context.model_dump(mode="json") if context else None,
            "generation": {
                "settings": settings_json,
                "prompt_sha256": (
                    hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                    if prompt
                    else None
                ),
            },
            "exchanges": exchanges,
            "input_sha256": input_hash(exchanges),
            "answer": answer.model_dump(mode="json"),
            "claim_citations": [
                {"claim_index": index, "citation_ids": list(claim.citation_ids)}
                for index, claim in enumerate(answer.claims)
            ],
            "validation": notes.get("validation"),
            "refusal_code": notes.get("refusal_code"),
            "error_code": notes.get("error_code"),
            "stage_ms": {**notes.get("stage_ms", {}), "total": total_ms},
        }
        traces.save(trace)
        record_event(
            {
                "stage": "query",
                "status": "error" if answer.status == "error" else "ok",
                "error_code": notes.get("error_code"),
                "answer_status": answer.status,
                "refusal_code": notes.get("refusal_code"),
                "duration_ms": total_ms,
                "user_ref": user_ref,
                "role": principal.role,
                "as_of": trace["as_of"],
                "mode": notes.get("mode"),
                "snapshot": notes.get("snapshot"),
                "candidate_ids": notes.get("candidate_ids"),
                "evidence_ids": notes.get("evidence_ids"),
                "response_ids": [e.get("response_id") for e in exchanges],
                "model": settings_json["model"] if settings_json else None,
                "prompt_sha256": trace["generation"]["prompt_sha256"],
                "settings_sha256": (
                    hashlib.sha256(_canonical(settings_json).encode()).hexdigest()
                    if settings_json
                    else None
                ),
                "usage": _sum_usage(exchanges),
                "cost": _sum_cost(exchanges),
                "stage_ms": trace["stage_ms"],
            },
            trace_id=trace_id,
        )
    except Exception:
        try:
            record_event(
                {"stage": "query", "status": "error", "error_code": "audit_failure"},
                trace_id=trace_id,
            )
        except Exception:
            pass
        return trace_id, Answer(
            status="error",
            claims=(),
            citations=(),
            reason="稽核紀錄失敗，暫時無法回答。",
        )
    return trace_id, answer


REPLAY_FIELDS = (
    "created_at",
    "role",
    "as_of",
    "question",
    "normalized_question",
    "snapshot",
    "mode",
    "candidate_ids",
    "dropped_reasons",
    "generation",
    "exchanges",
    "answer",
    "claim_citations",
    "validation",
    "refusal_code",
    "error_code",
    "stage_ms",
)


def replay(trace_id: str, *, traces: TraceStore | None = None) -> dict:
    """檢視保存的當次輸入輸出；不呼叫模型，也不讀現在的正文。"""
    traces = traces or TraceStore()
    trace = traces.load(trace_id)
    if input_hash(trace["exchanges"]) != trace["input_sha256"]:
        raise ValueError("trace_tampered")
    return {
        "trace_id": trace["trace_id"],
        "input_sha256": trace["input_sha256"],
        "input_sha256_verified": True,
        "model_called": False,
        "note": "重播只顯示當次保存的模型交換；重新生成不保證逐字相同。",
        **{name: trace[name] for name in REPLAY_FIELDS},
    }


def main():
    parser = argparse.ArgumentParser(description="本機開發者受限稽核：重播與清除")
    commands = parser.add_subparsers(dest="command", required=True)
    shown = commands.add_parser("replay")
    shown.add_argument("--trace-id", required=True)
    purge = commands.add_parser("purge")
    purge.add_argument("--before", type=date.fromisoformat)
    args = parser.parse_args()
    traces = TraceStore()
    if args.command == "replay":
        result = replay(args.trace_id, traces=traces)
    elif args.before is None:
        result = {"purged": traces.purge_expired()}
    else:
        cutoff = datetime.combine(args.before, datetime.min.time(), timezone.utc)
        result = {"purged": traces.purge(before=cutoff)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
