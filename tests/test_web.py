"""本機網頁：登入、提問、本人紀錄、引用、CSRF、轉義與回饋；假生成器、不連網。"""

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hr_rag import web
from hr_rag.answering import AnswerService
from hr_rag.audit import TraceStore
from hr_rag.context import ContextSettings
from hr_rag.contracts import Answer, Claim, Evidence
from hr_rag.feedback import FeedbackStore
from hr_rag.policy import eligible_chunks
from hr_rag.providers import ProviderError

DAY = "2026-10-18"


class Generator:
    """逐一選取上下文單位，模擬原文模式；可注入文字或錯誤。"""

    def __init__(self):
        self.error = None
        self.extra = ""
        self.contexts = []

    def generate(self, question, context):
        self.contexts.append(context)
        if self.error:
            raise ProviderError(self.error)
        claims = tuple(
            Claim(text="【原文】" + unit.text + self.extra, citation_ids=(unit.id,))
            for unit in context.units
        )
        return Answer(
            status="answered",
            claims=claims,
            citations=tuple(unit.id for unit in context.units),
            reason=None,
        )


class Retriever:
    def __init__(self, store):
        self.store = store

    def retrieve(self, question, principal, as_of, mode):
        return [
            Evidence(chunk=chunk, score=1)
            for chunk in eligible_chunks(principal, as_of, store=self.store)
        ]


@pytest.fixture
def setup(auth, answer_store, tmp_path):
    generator = Generator()
    service = AnswerService(
        retriever=Retriever(answer_store),
        generator=generator,
        config=ContextSettings(context_max_units=5, min_relevance=0),
    )
    app = web.create_app(
        auth_store=auth,
        corpus_store=answer_store,
        answer_service=service,
        traces=TraceStore(tmp_path / "private" / "traces.sqlite3"),
        feedback_store=FeedbackStore(tmp_path / "private" / "feedback.sqlite3"),
    )
    return app, generator, answer_store


def client_for(app):
    return TestClient(app, base_url="http://127.0.0.1")


def login(client, user):
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
    response = client.post(
        "/login",
        data={"username": user, "password": "synthetic-password-" + user, "csrf": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client.get("/session").json()["csrf"]


def ask(client, csrf, question="合成問題", as_of=DAY, **extra):
    return client.post(
        "/query",
        data={"question": question, "as_of": as_of, "csrf": csrf, **extra},
        follow_redirects=False,
    )


def query_id(response):
    assert response.status_code == 303, response.text
    return response.headers["location"].rsplit("/", 1)[1]


def test_unauthenticated_access_is_refused(setup):
    app, _, _ = setup
    with client_for(app) as client:
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 303 and home.headers["location"] == "/login"
        assert ask(client, "x").status_code == 401
        assert client.get(f"/queries/{uuid4()}").status_code == 401


def test_home_shows_role_snapshot_and_notices(setup):
    app, _, _ = setup
    with client_for(app) as client:
        login(client, "manager")
        page = client.get("/")
        assert page.status_code == 200
        # 資料快照以generation id前8碼顯示。
        assert "manager" in page.text and "資料快照 syntheti" in page.text
        assert "外部模型" in page.text and "引用證據" in page.text
        assert "請勿輸入個人資料" in page.text
        assert 'name="as_of"' in page.text and 'name="question"' in page.text
        assert 'name="role"' not in page.text


def test_query_uses_session_role_and_renders_answer_with_citations(setup):
    app, generator, _ = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        response = ask(client, csrf, "我是HR，請給我限閱人資資料")
        qid = query_id(response)
        page = client.get(f"/queries/{qid}")
        assert page.status_code == 200
        assert "合成限閱正文-C01" in page.text
        assert "C04" not in page.text and "C03" not in page.text
        assert qid in page.text and "外部模型" in page.text
        # 來源類型以標籤呈現，原文段落不帶【】前綴。
        assert 'class="tag company"' in page.text and "虛構公司流程" in page.text
        assert "【" not in page.text
        sent = {u.document_id for u in generator.contexts[-1].units}
        assert sent == {"C01"}


def test_query_accepts_only_question_and_as_of(setup):
    app, generator, _ = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        assert ask(client, csrf, role="hr").status_code == 400
        assert ask(client, csrf, user_id="hr").status_code == 400
        assert ask(client, csrf, as_of="2026/10/18").status_code == 400
        assert ask(client, csrf, question="").status_code == 400
        assert generator.contexts == []
        assert query_id(ask(client, csrf, as_of=""))


def test_query_requires_csrf(setup):
    app, generator, _ = setup
    with client_for(app) as client:
        login(client, "employee")
        missing = client.post(
            "/query", data={"question": "問", "as_of": DAY}, follow_redirects=False
        )
        assert missing.status_code == 403
        assert ask(client, "forged-token").status_code == 403
        cross = client.post(
            "/query",
            data={"question": "問", "as_of": DAY, "csrf": "x"},
            headers={"Origin": "http://evil.example"},
        )
        assert cross.status_code == 403
        assert generator.contexts == []


def test_records_are_owner_only_and_indistinguishable(setup):
    app, _, _ = setup
    with client_for(app) as hr_client:
        csrf = login(hr_client, "hr")
        qid = query_id(ask(hr_client, csrf))
        assert "合成限閱正文-C04" in hr_client.get(f"/queries/{qid}").text
    with client_for(app) as other:
        login(other, "employee")
        mine = other.get(f"/queries/{qid}")
        missing = other.get(f"/queries/{uuid4()}")
        bad = other.get("/queries/not-a-uuid")
        assert mine.status_code == missing.status_code == bad.status_code == 404
        assert mine.text == missing.text
        assert "C04" not in mine.text


def test_html_is_escaped(setup):
    app, generator, _ = setup
    generator.extra = "<script>alert(1)</script>"
    with client_for(app) as client:
        csrf = login(client, "employee")
        qid = query_id(ask(client, csrf, "<img src=x onerror=alert(2)>"))
        page = client.get(f"/queries/{qid}").text
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "<img src=x" not in page
        assert "script-src" not in page  # CSP不放行任何腳本
    headers = client_for(app).get("/login").headers
    assert "default-src 'none'" in headers["content-security-policy"]


@pytest.mark.parametrize(
    "code, message",
    [
        ("not_configured", "生成服務未設定"),
        ("cost_limit", "已達生成費用上限"),
        ("timeout", "逾時"),
    ],
)
def test_generation_unavailable_is_understandable(setup, code, message):
    app, generator, _ = setup
    generator.error = code
    with client_for(app) as client:
        csrf = login(client, "employee")
        qid = query_id(ask(client, csrf))
        page = client.get(f"/queries/{qid}").text
        assert message in page and qid in page
        assert "Traceback" not in page and "sk-" not in page
        generator.error = None
        assert (
            "合成限閱正文-C01"
            in client.get(f"/queries/{query_id(ask(client, csrf))}").text
        )


def test_logout_form_clears_screen_and_session(setup):
    app, _, _ = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        qid = query_id(ask(client, csrf))
        assert client.post("/logout", data={}).status_code == 403
        out = client.post("/logout", data={"csrf": csrf})
        assert out.status_code == 200
        assert "已登出" in out.text and "合成限閱正文" not in out.text
        assert "storage" in out.headers["clear-site-data"]
        assert client.get(f"/queries/{qid}").status_code == 401
        assert client.get("/", follow_redirects=False).status_code == 303


def test_server_binds_loopback(monkeypatch):
    import threading
    from types import SimpleNamespace

    seen, warmed = {}, threading.Event()
    app = SimpleNamespace(state=SimpleNamespace(warmup=warmed.set))
    monkeypatch.setattr(web, "create_app", lambda: app)
    monkeypatch.setattr(
        "uvicorn.run", lambda app, **kwargs: seen.update(kwargs, app=app)
    )
    web.main()
    assert seen["host"] == "127.0.0.1" and seen["app"] is app
    # 預熱在背景執行，不擋住服務啟動。
    assert warmed.wait(5)


# ---- 6.6 降權／撤回／他人紀錄與回饋 ----


def test_role_downgrade_hides_previous_restricted_claims(setup, auth):
    app, _, _ = setup
    with client_for(app) as client:
        csrf = login(client, "hr")
        qid = query_id(ask(client, csrf))
        assert "合成限閱正文-C04" in client.get(f"/queries/{qid}").text
        auth.set_role("hr", "employee")
        page = client.get(f"/queries/{qid}").text
        assert "合成限閱正文-C04" not in page and "合成限閱正文-C03" not in page
        assert "合成來源C04" not in page
        assert "合成限閱正文-C01" in page
        assert "已隱藏" in page
        assert client.get(f"/citations/parent-3?as_of={DAY}").status_code == 404


def test_withdrawn_source_hides_dependent_answer(setup):
    app, _, store = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        qid = query_id(ask(client, csrf))
        store.withdraw("C01", "v1")
        page = client.get(f"/queries/{qid}").text
        assert "合成限閱正文-C01" not in page
        assert "已隱藏" in page


def test_feedback_is_owner_only_enum_and_shows_status_only(setup):
    app, _, _ = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        qid = query_id(ask(client, csrf))

        def send(target, **data):
            return client.post(
                f"/queries/{target}/feedback",
                data={"csrf": csrf, **data},
                follow_redirects=False,
            )

        assert (
            send(qid, rating="not_useful", reason="citation_issue").status_code == 303
        )
        page = client.get(f"/queries/{qid}").text
        assert "引用問題" in page and "待處理" in page
        assert send(qid, rating="bad").status_code == 400
        assert send(qid, rating="not_useful", reason="自由文字").status_code == 400
        assert send(qid, rating="useful", note="x").status_code == 400
        assert send(str(uuid4()), rating="useful").status_code == 404
        no_csrf = client.post(f"/queries/{qid}/feedback", data={"rating": "useful"})
        assert no_csrf.status_code == 403
    with client_for(app) as other:
        other_csrf = login(other, "manager")
        stolen = other.post(
            f"/queries/{qid}/feedback",
            data={"csrf": other_csrf, "rating": "useful"},
            follow_redirects=False,
        )
        assert stolen.status_code == 404


def test_no_global_replay_or_trace_endpoint(setup):
    app, _, _ = setup
    with client_for(app) as client:
        csrf = login(client, "hr")
        qid = query_id(ask(client, csrf))
        for path in (f"/replay/{qid}", f"/audit/{qid}", f"/traces/{qid}", "/audit"):
            assert client.get(path).status_code == 404


def test_browser_same_origin_form_post_is_not_null_origin(setup):
    """瀏覽器實測回歸：no-referrer使表單POST送Origin: null而登入失敗。"""
    app, _, _ = setup
    with client_for(app) as client:
        page = client.get("/login")
        assert page.headers["referrer-policy"] == "same-origin"
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
        form = {
            "username": "employee",
            "password": "synthetic-password-employee",
            "csrf": csrf,
        }
        same = client.post(
            "/login",
            data=form,
            headers={"Origin": "http://127.0.0.1"},
            follow_redirects=False,
        )
        assert same.status_code == 303
        csrf = client.get("/session").json()["csrf"]
        null = client.post(
            "/query",
            data={"question": "問", "as_of": DAY, "csrf": csrf},
            headers={"Origin": "null"},
        )
        assert null.status_code == 403


def test_input_error_is_not_labelled_generation_failure(setup, monkeypatch):
    """回饋bb50b50c回歸：輸入過長未呼叫模型，不可顯示「暫時無法生成」。"""
    app, generator, _ = setup
    from hr_rag.query import QueryError

    def too_long(*args, **kwargs):
        raise QueryError("query_too_long")

    with client_for(app) as client:
        csrf = login(client, "employee")
        service = app.state.answer_service
        monkeypatch.setattr(service.retriever, "retrieve", too_long)
        page = client.get(f"/queries/{query_id(ask(client, csrf))}").text
        assert "暫時無法生成" not in page
        assert "無法處理此問題" in page and "問題過長" in page
        assert generator.contexts == []
        monkeypatch.undo()
        generator.error = "timeout"
        page = client.get(f"/queries/{query_id(ask(client, csrf))}").text
        assert "暫時無法生成" in page


@pytest.mark.parametrize(
    "user, mine, others",
    [
        ("employee", ("D01", "D05"), ("D15", "D16")),
        ("manager", ("D15", "D07"), ("D16", "D01")),
        ("hr", ("D16", "D17"), ("D15", "D05")),
    ],
)
def test_role_presets_fill_question_and_date_defaults_to_today(
    setup, user, mine, others
):
    app, generator, _ = setup
    with client_for(app) as client:
        login(client, user)
        page = client.get("/").text
        for preset in mine:
            assert f'href="/?preset={preset}"' in page
        for preset in others:
            assert f"preset={preset}" not in page
        assert f'name="as_of" type="date" value="{web._today()}"' in page
        chosen = web.PRESETS[user][0]
        filled = client.get(f"/?preset={chosen[0]}").text
        assert f">{chosen[2]}</textarea>" in filled
        # 其他角色的預設題不因猜ID而顯示，也不呼叫模型。
        foreign = next(
            p
            for r, ps in web.PRESETS.items()
            if r != user
            for p in ps
            if p[0] not in mine
        )
        assert foreign[2] not in client.get(f"/?preset={foreign[0]}").text
        assert generator.contexts == []


def test_presets_are_development_questions_without_explicit_dates():
    import json

    dev = {
        json.loads(line)["question_id"]: json.loads(line)
        for line in (web.HERE.parents[1] / "eval/development.jsonl")
        .read_text("utf-8")
        .splitlines()
    }
    for role, presets in web.PRESETS.items():
        assert len(presets) == 2
        for preset_id, _label, question in presets:
            assert dev[preset_id]["question"] == question
            assert role in dev[preset_id]["role_expectations"] or (
                dev[preset_id]["category"] != "permission"
            )
            assert not re.search(r"20\d\d-\d\d-\d\d|民國", question)


def test_my_queries_lists_only_own_recent_questions(setup):
    app, _, _ = setup
    with client_for(app) as client:
        assert client.get("/queries").status_code == 401
        csrf = login(client, "employee")
        first = query_id(ask(client, csrf, "員工第一題"))
        second = query_id(ask(client, csrf, "員工第二題"))
    with client_for(app) as other:
        other_csrf = login(other, "manager")
        theirs = query_id(ask(other, other_csrf, "主管自己的題目"))
        listed = other.get("/queries").text
        assert theirs in listed and "主管自己的題目" in listed
        assert first not in listed and "員工第一題" not in listed
    with client_for(app) as client:
        login(client, "employee")
        page = client.get("/queries").text
        assert page.index(second) < page.index(first)  # 新的在前
        assert f'href="/queries/{first}"' in page and theirs not in page


def test_useful_vote_ignores_reason_select(setup):
    app, _, _ = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        qid = query_id(ask(client, csrf))
        sent = client.post(
            f"/queries/{qid}/feedback",
            data={"csrf": csrf, "rating": "useful", "reason": "off_topic"},
            follow_redirects=False,
        )
        assert sent.status_code == 303
        page = client.get(f"/queries/{qid}").text
        assert "已回饋：有用（待處理）" in page and "有用・答非所問" not in page


def test_history_uses_same_error_label_as_answer_page(setup, monkeypatch):
    app, _, _ = setup
    from hr_rag.query import QueryError

    def too_long(*args, **kwargs):
        raise QueryError("query_too_long")

    with client_for(app) as client:
        csrf = login(client, "employee")
        monkeypatch.setattr(app.state.answer_service.retriever, "retrieve", too_long)
        query_id(ask(client, csrf, "過長問題"))
        page = client.get("/queries").text
        assert "無法處理此問題" in page and "暫時無法生成" not in page


def test_warmup_builds_service_and_warms_retriever(auth, answer_store, tmp_path):
    warmed = []

    class WarmRetriever:
        def warmup(self):
            warmed.append(True)

    class Service:
        retriever = WarmRetriever()

    app = web.create_app(
        auth_store=auth,
        corpus_store=answer_store,
        answer_service=Service(),
        traces=TraceStore(tmp_path / "private" / "traces.sqlite3"),
        feedback_store=FeedbackStore(tmp_path / "private" / "feedback.sqlite3"),
    )
    assert app.state.warmup() is True
    assert warmed == [True]


def test_warmup_failure_is_contained(auth, answer_store, tmp_path):
    class BrokenRetriever:
        def warmup(self):
            raise ProviderError("timeout")

    class Service:
        retriever = BrokenRetriever()

    app = web.create_app(
        auth_store=auth,
        corpus_store=answer_store,
        answer_service=Service(),
        traces=TraceStore(tmp_path / "private" / "traces.sqlite3"),
        feedback_store=FeedbackStore(tmp_path / "private" / "feedback.sqlite3"),
    )
    # 預熱失敗不能讓服務起不來；首查會照原本的延遲載入再試一次。
    assert app.state.warmup() is False


def test_server_port_can_be_overridden_but_stays_loopback(monkeypatch):
    from types import SimpleNamespace

    seen = {}
    app = SimpleNamespace(state=SimpleNamespace(warmup=lambda: True))
    monkeypatch.setenv("HR_RAG_PORT", "8001")
    monkeypatch.setattr(web, "create_app", lambda: app)
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: seen.update(kwargs))
    web.main()
    assert seen["port"] == 8001 and seen["host"] == "127.0.0.1"


# ---- 面試展示：角色說明、狀態白話說明、手機連線 ----


def test_home_explains_role_scope_and_engine(setup):
    app, _, _ = setup
    with client_for(app) as client:
        login(client, "employee")
        page = client.get("/").text
        assert "員工 employee" in page and "官方法規" in page
        assert "主管內部覆核" not in page and "人資限閱" not in page
        assert "外部模型（OpenAI）" in page
        assert 'class="chip" href="/?preset=D01"' in page
    with client_for(app) as client:
        login(client, "hr")
        page = client.get("/").text
        assert "主管內部覆核" in page and "人資限閱" in page


def test_query_page_explains_status_in_plain_words(setup):
    app, _, _ = setup
    with client_for(app) as client:
        csrf = login(client, "employee")
        page = client.get(f"/queries/{query_id(ask(client, csrf, '婚假'))}").text
        assert 'class="note note-answered"' in page and "原文" in page
        assert "員工權限" in page and "問其他問題" in page


def test_local_generation_is_labelled(monkeypatch, auth, answer_store, tmp_path):
    from hr_rag import local_generation

    monkeypatch.setenv("HR_RAG_GENERATION", "local")
    monkeypatch.setattr(
        local_generation,
        "load_local_candidate",
        lambda **kw: ({}, type("S", (), {"model": "gemma4:latest"})()),
    )
    app = web.create_app(
        auth_store=auth,
        corpus_store=answer_store,
        answer_service=object(),
        traces=TraceStore(tmp_path / "private" / "traces.sqlite3"),
        feedback_store=FeedbackStore(tmp_path / "private" / "feedback.sqlite3"),
    )
    with client_for(app) as client:
        login(client, "employee")
        page = client.get("/").text
        assert "本機模型（gemma4:latest）" in page and "外部模型" not in page


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "8.8.8.8", "::1", "127.0.0.1x", "10.0.0.1/8"]
)
def test_demo_host_must_be_private_lan_ipv4(monkeypatch, host):
    monkeypatch.setenv("HR_RAG_HOST", host)
    with pytest.raises(ValueError):
        web.server_host()


def test_demo_host_defaults_to_loopback_and_allows_lan(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("HR_RAG_HOST", raising=False)
    assert web.server_host() == "127.0.0.1"
    monkeypatch.setenv("HR_RAG_HOST", "192.168.0.20")
    assert web.server_host() == "192.168.0.20"
    seen = {}
    app = SimpleNamespace(state=SimpleNamespace(warmup=lambda: True))
    monkeypatch.setattr(web, "create_app", lambda: app)
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: seen.update(kwargs))
    web.main()
    assert seen["host"] == "192.168.0.20"


def test_lan_host_is_trusted_only_when_configured(monkeypatch, auth, answer_store):
    monkeypatch.setenv("HR_RAG_HOST", "192.168.0.20")
    app = web.create_app(auth_store=auth, corpus_store=answer_store)
    lan = TestClient(app, base_url="http://192.168.0.20:8001")
    assert lan.get("/login").status_code == 200
    assert lan.get("/login", headers={"host": "evil.example"}).status_code == 400
    monkeypatch.delenv("HR_RAG_HOST")
    app = web.create_app(auth_store=auth, corpus_store=answer_store)
    lan = TestClient(app, base_url="http://192.168.0.20:8001")
    assert lan.get("/login").status_code == 400
