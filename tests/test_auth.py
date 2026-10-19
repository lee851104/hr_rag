"""合成帳密與隔離SQLite；不讀實際憑證。"""

import re

import pytest
from fastapi.testclient import TestClient

from hr_rag.auth import AuthenticationError, AuthStore
from hr_rag.storage import CorpusStore
from hr_rag.web import create_app


@pytest.fixture
def client(auth, tmp_path):
    with TestClient(
        create_app(auth_store=auth, corpus_store=CorpusStore(tmp_path / "corpus")),
        base_url="http://127.0.0.1",
    ) as client:
        yield client


def login(client, username="employee", **extras):
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
    return client.post(
        "/login",
        data={
            "username": username,
            "password": "synthetic-password-" + username,
            "csrf": csrf,
            **extras,
        },
        follow_redirects=False,
    )


def test_three_server_accounts_hashes_only(auth):
    with auth.connect() as db:
        rows = db.execute("SELECT * FROM users ORDER BY user_id").fetchall()
    assert {row["user_id"]: row["role"] for row in rows} == {
        "employee": "employee",
        "manager": "manager",
        "hr": "hr",
    }
    assert all("synthetic-password" not in row["password_hash"] for row in rows)
    with pytest.raises(AuthenticationError):
        auth.login("hr", "incorrect")
    with pytest.raises(AuthenticationError):
        auth.login("nonexistent", "incorrect")


def test_login_logout_invalidates_old_session(client, auth):
    assert client.get("/session").status_code == 401
    response = login(client)
    assert response.status_code == 303
    cookies = response.headers.get_list("set-cookie")
    assert any("HttpOnly" in c and "SameSite=strict" in c for c in cookies)
    token = client.cookies.get("hr_session")
    identity = client.get("/session").json()
    assert identity["role"] == "employee"
    assert client.post("/logout").status_code == 403
    assert (
        client.post("/logout", headers={"X-CSRF-Token": identity["csrf"]}).status_code
        == 200
    )
    with pytest.raises(AuthenticationError):
        auth.authenticate(token)
    assert client.get("/session").status_code == 401


def test_frontend_role_never_escalates(client):
    assert login(client, role="hr").status_code == 400
    assert client.get("/session").status_code == 401
    assert login(client).status_code == 303
    assert (
        client.get("/session?role=hr", headers={"X-Role": "hr"}).json()["role"]
        == "employee"
    )


def test_csrf_origin_host_and_secret_errors(client):
    secret = "synthetic-password-hr"
    denied = client.post("/login", data={"username": "hr", "password": secret})
    assert denied.status_code == 403 and secret not in denied.text
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
    denied = client.post(
        "/login",
        data={"username": "hr", "password": secret, "csrf": csrf},
        headers={"Origin": "https://attacker.example"},
    )
    assert denied.status_code == 403 and secret not in denied.text
    assert client.get("/login", headers={"Host": "attacker.example"}).status_code == 400
    assert login(client, password="invalid").status_code == 401
    assert client.get("/session").headers["cache-control"] == "no-store"


def test_role_change_and_password_reset_use_current_server_state(auth):
    token, _ = auth.login("hr", "synthetic-password-hr")
    assert auth.authenticate(token).role == "hr"
    auth.set_role("hr", "employee")
    assert auth.authenticate(token).role == "employee"
    auth.set_password("hr", "another-synthetic-password")
    with pytest.raises(AuthenticationError):
        auth.authenticate(token)


def test_session_expiry_and_tokens_not_stored_in_clear(auth):
    token, csrf = auth.login("hr", "synthetic-password-hr")
    with auth.connect() as db:
        row = dict(db.execute("SELECT * FROM sessions").fetchone())
        assert token not in row.values() and csrf not in row.values()
        db.execute("UPDATE sessions SET expires_at=0")
    with pytest.raises(AuthenticationError):
        auth.authenticate(token)


def test_unicode_csrf_returns_controlled_denial(client):
    client.get("/login")
    response = client.post(
        "/login", data={"username": "hr", "password": "invalid", "csrf": "錯誤值"}
    )
    assert response.status_code == 403


def test_challenge_replay_and_other_session_csrf_denied(auth):
    challenge = auth.challenge()
    assert auth.consume_challenge(challenge, challenge)
    assert not auth.consume_challenge(challenge, challenge)
    first, first_csrf = auth.login("employee", "synthetic-password-employee")
    second, second_csrf = auth.login("hr", "synthetic-password-hr")
    assert auth.valid_csrf(first, first_csrf)
    assert not auth.valid_csrf(first, second_csrf)
    assert not auth.valid_csrf(second, first_csrf)


def test_account_switch_revokes_previous_session(client, auth):
    login(client, "hr")
    previous = client.cookies.get("hr_session")
    login(client, "employee")
    assert client.get("/session").json()["role"] == "employee"
    with pytest.raises(AuthenticationError):
        auth.authenticate(previous)


def test_unconfigured_accounts_disabled_and_no_default_password(tmp_path):
    store = AuthStore(tmp_path / "unconfigured.sqlite3")
    with store.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM users WHERE enabled=0").fetchone()[0] == 3
        )
    for user in ("employee", "manager", "hr"):
        with pytest.raises(AuthenticationError):
            store.login(user, user)


def test_server_start_binds_loopback_without_access_logging(monkeypatch):
    import uvicorn

    from hr_rag import web

    captured = {}
    sentinel = object()
    monkeypatch.setattr(web, "create_app", lambda: sentinel)
    monkeypatch.setattr(
        uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs)
    )
    web.main()
    assert captured == {
        "app": sentinel,
        "host": "127.0.0.1",
        "port": 8000,
        "proxy_headers": False,
        "access_log": False,
    }


def test_auth_path_can_be_redirected_for_isolated_demo(tmp_path, monkeypatch):
    target = tmp_path / "demo-auth.sqlite3"
    monkeypatch.setenv("HR_RAG_AUTH_PATH", str(target))
    assert AuthStore().path == target and target.exists()
