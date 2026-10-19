"""本機展示頁：登入、單輪提問、本人紀錄、引用檢視與回饋；角色一律來自伺服器session。"""

import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hr_rag.audit import TraceStore, traced_answer
from hr_rag.auth import SESSION_SECONDS, AuthenticationError, AuthStore
from hr_rag.citations import CitationNotFound, citation_details, read_citation
from hr_rag.contracts import QueryRequest
from hr_rag.feedback import REASONS, STATUS_LABELS, FeedbackStore
from hr_rag.storage import CorpusStore

COOKIE = "hr_session"
CSRF_COOKIE = "hr_csrf"
CHALLENGE_COOKIE = "hr_login"
HERE = Path(__file__).resolve().parent
TEMPLATES = Environment(
    loader=FileSystemLoader(HERE / "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
)
STATUS_TEXT = {
    "answered": "已回答",
    "insufficient": "資料不足",
    "conflict": "來源衝突",
    "error": "暫時無法生成",
}
# 只有生成相關錯誤標「暫時無法生成」；輸入或引用問題另行說明（回饋bb50b50c）。
ERROR_STATUS_TEXT = {
    "invalid_input": "無法處理此問題",
    "citation_expired": "引用證據已失效",
    "service_error": "服務暫時無法使用",
}
ERROR_TEXT = {
    401: "請先登入。",
    403: "請求驗證失敗，請重新整理頁面後再試。",
    404: "查無此資料，或你沒有權限檢視。",
    400: "輸入格式不符。",
}
TAIPEI = timezone(timedelta(hours=8))
ROLE_NAMES = {"employee": "員工", "manager": "主管", "hr": "人資"}
# 伺服器加在主張前的來源標示，畫面改以標籤呈現。
CLAIM_TAGS = {
    "官方依據": ("official", "官方法規"),
    "虛構公司流程": ("company", "虛構公司流程"),
    "參照補充": ("supp", "參照補充"),
}


def status_label(status, error_code=None):
    # 只有生成相關錯誤標「暫時無法生成」（回饋bb50b50c）；答案頁與紀錄列表共用。
    if status == "error":
        return ERROR_STATUS_TEXT.get(error_code, STATUS_TEXT["error"])
    return STATUS_TEXT[status]


def split_claim(text):
    """拆出開頭的【來源】標示；不認得的【】保留在正文。"""
    tags = []
    while text.startswith("【") and "】" in text:
        name = text[1 : text.index("】")]
        parts = name.split("＋")
        if name == "原文":
            pass
        elif all(part in CLAIM_TAGS for part in parts):
            tags.extend(CLAIM_TAGS[part] for part in parts)
        else:
            break
        text = text[text.index("】") + 1 :]
    return tags, text


# 首頁示範題：取自開發集（不含保留題），每角色兩題；點選只填入問題，送出仍由使用者決定。
PRESETS = {
    "employee": (
        (
            "D01",
            "婚假日數與工資",
            "依目前收錄規定，結婚可請幾日婚假，這段期間是否有工資？",
        ),
        (
            "D05",
            "請假申請要填什麼",
            "在這套虛構公司制度中，填寫請假申請要提供哪些基本項目？"
            "窗口能要求無關資料，或因內部表單未完直接否定法定請假嗎？",
        ),
    ),
    "manager": (
        (
            "D15",
            "主管特殊內部覆核",
            "虛構公司的主管特殊內部覆核使用什麼識別表單，記哪些項目？"
            "未完成這張表就能否定法定請假嗎？",
        ),
        (
            "D07",
            "特休日期由誰決定",
            "主管希望一月就鎖定我整年的特休日期，之後一律不准改。"
            "請結合法律與主管機關解釋，說明誰決定休假日期、公司能做什麼，"
            "以及何時能協商調整。",
        ),
    ),
    "hr": (
        (
            "D16",
            "HR例外案件追蹤",
            "虛構公司HR例外案件使用哪個追蹤識別，登錄什麼，以及如何限制傳遞與真實個資？",
        ),
        (
            "D17",
            "假勤與薪資差異",
            "虛構公司HR發現假勤和薪資有差異時要先比對什麼、怎樣才可結案？"
            "請說明雙人確認與資料限制。",
        ),
    ),
}


def _page(name, status_code=200, **values):
    return HTMLResponse(
        TEMPLATES.get_template(name).render(**values), status_code=status_code
    )


def create_app(
    *,
    auth_store: AuthStore | None = None,
    corpus_store: CorpusStore | None = None,
    answer_service=None,
    traces: TraceStore | None = None,
    feedback_store: FeedbackStore | None = None,
) -> FastAPI:
    auth = auth_store or AuthStore()
    corpus = corpus_store or CorpusStore()
    stores = {"traces": traces, "feedback": feedback_store}
    services = {"answer": answer_service}
    service_lock = threading.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.answer_service = answer_service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def service():
        # 模型載入較慢，首次提問才建立；之後各請求共用但不共用答案快取。
        with service_lock:
            if services["answer"] is None:
                from hr_rag.answering import AnswerService
                from hr_rag.retrieval import Retriever

                services["answer"] = AnswerService(retriever=Retriever(store=corpus))
                app.state.answer_service = services["answer"]
            return services["answer"]

    def store(name):
        # 預設受限儲存首次使用才建立，避免只看引用時也產生檔案。
        with service_lock:
            if stores[name] is None:
                stores[name] = TraceStore() if name == "traces" else FeedbackStore()
            return stores[name]

    @app.middleware("http")
    async def browser_guards(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (
                origin and origin != str(request.base_url).rstrip("/")
            ) or request.headers.get("sec-fetch-site") == "cross-site":
                response = JSONResponse({"detail": "csrf_failed"}, status_code=403)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # no-referrer會讓瀏覽器表單POST送Origin: null；same-origin只對同源送出。
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(HTTPException)
    async def error_page(request, exc):
        if request.url.path.startswith(("/citations/", "/session")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        # 不存在與無權同一頁面，不帶ID、標題或正文。
        return _page(
            "error.html",
            exc.status_code,
            code=exc.status_code,
            message=ERROR_TEXT.get(exc.status_code, "服務暫時無法使用。"),
        )

    def principal(request):
        try:
            return auth.authenticate(request.cookies.get(COOKIE, ""))
        except AuthenticationError:
            raise HTTPException(401, "authentication_required") from None

    def require_csrf(request, supplied):
        if not auth.valid_csrf(request.cookies.get(COOKIE, ""), supplied or ""):
            raise HTTPException(403, "csrf_failed")

    async def read_form(request, allowed, *, max_fields):
        try:
            form = await request.form(
                max_files=0, max_fields=max_fields, max_part_size=8192
            )
        except Exception:
            raise HTTPException(400, "invalid_form") from None
        if any(len(form.getlist(k)) != 1 or not isinstance(form[k], str) for k in form):
            raise HTTPException(400, "invalid_form")
        return {k: form[k] for k in form}, set(form) - allowed

    def snapshot():
        try:
            with corpus.connect() as db:
                row = corpus.active(db)
        except Exception:
            row = None
        if row is None:
            return None
        return {"generation_id": row["id"], "manifest": row["manifest_hash"][:12]}

    def chrome(request, user, *, nav="ask"):
        return {
            "user": user,
            "role_name": ROLE_NAMES[user.role],
            "csrf": request.cookies.get(CSRF_COOKIE, ""),
            "snapshot": snapshot(),
            "presets": PRESETS[user.role],
            "nav": nav,
            "today": _today(),
            "as_of": _today(),
        }

    @app.get("/static/app.css")
    def stylesheet():
        return Response(
            (HERE / "static/app.css").read_text("utf-8"), media_type="text/css"
        )

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        csrf = auth.challenge()
        response = _page("login.html", csrf=csrf)
        response.set_cookie(
            CHALLENGE_COOKIE, csrf, max_age=600, httponly=True, samesite="strict"
        )
        return response

    @app.post("/login")
    async def login(request: Request):
        try:
            form = await request.form(max_files=0, max_fields=3, max_part_size=4096)
        except Exception:
            raise HTTPException(400, "invalid_login_form") from None
        if not auth.consume_challenge(
            request.cookies.get(CHALLENGE_COOKIE, ""), str(form.get("csrf", ""))
        ):
            raise HTTPException(403, "csrf_failed")
        if set(form) != {"username", "password", "csrf"} or any(
            len(form.getlist(k)) != 1 or not isinstance(form[k], str) for k in form
        ):
            raise HTTPException(400, "invalid_login_form")
        try:
            token, csrf = auth.login(form["username"], form["password"])
        except AuthenticationError:
            raise HTTPException(401, "invalid_credentials") from None
        auth.logout(request.cookies.get(COOKIE, ""))
        response = RedirectResponse("/", status_code=303)
        for name, value in ((COOKIE, token), (CSRF_COOKIE, csrf)):
            response.set_cookie(
                name, value, max_age=SESSION_SECONDS, httponly=True, samesite="strict"
            )
        response.delete_cookie(CHALLENGE_COOKIE)
        return response

    @app.get("/session")
    def session(request: Request):
        user = principal(request)
        return {**user.model_dump(), "csrf": request.cookies.get(CSRF_COOKIE, "")}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, preset: str | None = None):
        try:
            user = principal(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
        # 只接受目前角色的示範題；其他角色的ID當作未選擇。
        presets = PRESETS[user.role]
        chosen = next((p for p in presets if p[0] == preset), None)
        return _page(
            "home.html",
            **chrome(request, user),
            question=chosen[2] if chosen else "",
        )

    @app.post("/query")
    async def query(request: Request):
        user = principal(request)
        values, extra = await read_form(
            request, {"question", "as_of", "csrf"}, max_fields=4
        )
        require_csrf(request, values.get("csrf"))
        error = None
        as_of = None
        if extra or "question" not in values:
            error = "只接受問題與查詢日期。"
        elif values.get("as_of"):
            try:
                as_of = date.fromisoformat(values["as_of"])
                if as_of.isoformat() != values["as_of"]:
                    raise ValueError
            except ValueError:
                error = "查詢日期需為 YYYY-MM-DD。"
        if error is None:
            try:
                request_model = QueryRequest(question=values["question"], as_of=as_of)
            except ValidationError:
                error = "請輸入問題（不可空白或過長）。"
        if error:
            return _page(
                "home.html",
                400,
                **(chrome(request, user) | {"as_of": values.get("as_of", "")}),
                error=error,
                question=values.get("question", ""),
            )
        trace_id, _ = traced_answer(
            service(), request_model, user, traces=store("traces")
        )
        return RedirectResponse(f"/queries/{trace_id}", status_code=303)

    def visible_claims(trace, user):
        """依目前角色、撤回狀態與原查詢日期重驗；不能驗證的主張整段隱藏。"""
        as_of = date.fromisoformat(trace["as_of"])
        shown, hidden = [], 0
        for claim in trace["answer"]["claims"]:
            try:
                citations = []
                for cid in claim["citation_ids"]:
                    chunk = read_citation(user, cid, as_of, store=corpus)
                    details = citation_details(user, cid, as_of, store=corpus)
                    citations.append(details | {"text": chunk.text})
                tags, text = split_claim(claim["text"])
                shown.append(
                    {
                        "text": text,
                        "tags": tags,
                        "official": any(kind == "official" for kind, _ in tags),
                        "citations": citations,
                    }
                )
            except CitationNotFound:
                hidden += 1
        return shown, hidden

    @app.get("/queries", response_class=HTMLResponse)
    def my_queries(request: Request):
        user = principal(request)
        items = [
            {
                **item,
                "status_text": status_label(item["status"], item.get("error_code")),
                "created": datetime.fromtimestamp(item["created_at"], TAIPEI).strftime(
                    "%m-%d %H:%M"
                ),
            }
            for item in store("traces").recent(user.user_id)
        ]
        return _page(
            "queries.html", **chrome(request, user, nav="history"), items=items
        )

    @app.get("/queries/{trace_id}", response_class=HTMLResponse)
    def query_record(request: Request, trace_id: str):
        user = principal(request)
        trace = store("traces").owned(trace_id, user.user_id)
        if trace is None:
            raise HTTPException(404, "not_found")
        claims, hidden = visible_claims(trace, user)
        answer = trace["answer"]
        items = [
            {
                **row,
                "reason_label": REASONS.get(row["reason"], ""),
                "status_label": STATUS_LABELS[row["status"]],
            }
            for row in store("feedback").for_trace(trace["trace_id"], trace["user_ref"])
        ]
        return _page(
            "query.html",
            **(chrome(request, user) | {"as_of": _today()}),
            trace_id=trace["trace_id"],
            asked_as_of=trace["as_of"],
            asked_question=trace["question"],
            created=datetime.fromtimestamp(trace["created_at"], TAIPEI).strftime(
                "%Y-%m-%d %H:%M"
            ),
            status=answer["status"],
            status_text=status_label(answer["status"], trace.get("error_code")),
            reason=answer.get("reason"),
            claims=claims,
            hidden=hidden,
            all_hidden=bool(answer["claims"]) and not claims,
            feedback=items,
            reasons=REASONS,
        )

    @app.post("/queries/{trace_id}/feedback")
    async def submit_feedback(request: Request, trace_id: str):
        user = principal(request)
        values, extra = await read_form(
            request, {"csrf", "rating", "reason"}, max_fields=4
        )
        require_csrf(request, values.get("csrf"))
        trace = store("traces").owned(trace_id, user.user_id)
        if trace is None:
            raise HTTPException(404, "not_found")
        if extra:
            raise HTTPException(400, "invalid_form")
        # 「有用」與原因選單同一表單送出；有用時不記原因。
        reason = None if values.get("rating") == "useful" else values.get("reason")
        try:
            store("feedback").submit(
                trace["trace_id"],
                trace["user_ref"],
                values.get("rating"),
                reason or None,
            )
        except ValueError:
            raise HTTPException(400, "invalid_feedback") from None
        return RedirectResponse(f"/queries/{trace['trace_id']}", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        principal(request)
        token = request.cookies.get(COOKIE, "")
        header = request.headers.get("x-csrf-token")
        if header is not None:
            supplied = header
        else:
            values, _ = await read_form(request, {"csrf"}, max_fields=2)
            supplied = values.get("csrf", "")
        if not auth.valid_csrf(token, supplied):
            raise HTTPException(403, "csrf_failed")
        auth.logout(token)
        if header is not None:
            response = JSONResponse({"status": "logged_out"})
        else:
            response = _page("logged_out.html")
            # 清除瀏覽器對本站的快取與儲存，避免返回鍵看到先前答案。
            response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
        for name in (COOKIE, CSRF_COOKIE, CHALLENGE_COOKIE):
            response.delete_cookie(name)
        return response

    @app.get("/citations/{citation_id}")
    def citation(request: Request, citation_id: str, as_of: str | None = None):
        user = principal(request)
        try:
            selected = date.fromisoformat(as_of or "")
            if selected.isoformat() != as_of:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "invalid_date") from None
        try:
            return read_citation(user, citation_id, selected, store=corpus)
        except CitationNotFound:
            raise HTTPException(404, "citation_not_found") from None

    return app


def _today():
    return datetime.now(TAIPEI).date().isoformat()


def main():
    import uvicorn

    uvicorn.run(
        create_app(), host="127.0.0.1", port=8000, proxy_headers=False, access_log=False
    )


if __name__ == "__main__":
    main()
