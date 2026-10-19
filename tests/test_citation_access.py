from datetime import date

import pytest
from fastapi.testclient import TestClient
from test_auth import login

from hr_rag.citations import CitationNotFound, read_citation
from hr_rag.contracts import Principal
from hr_rag.corpus.ingest import ingest
from hr_rag.policy import eligible_chunks
from hr_rag.storage import CorpusStore
from hr_rag.web import create_app


def test_missing_forbidden_and_withdrawn_identical(policy_store, auth):
    app = create_app(auth_store=auth, corpus_store=policy_store)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/citations/id-3?as_of=2026-10-01").status_code == 401
        login(client)
        missing = client.get("/citations/missing?as_of=2026-10-01")
        forbidden = client.get("/citations/id-3?as_of=2026-10-01")
        assert missing.status_code == forbidden.status_code == 404
        assert missing.json() == forbidden.json() == {"detail": "citation_not_found"}
        assert "C04" not in forbidden.text and "合成" not in forbidden.text
        assert client.get("/citations/id-1?as_of=2026-10-01").status_code == 200
        policy_store.withdraw("C01", "v1")
        assert client.get("/citations/id-1?as_of=2026-10-01").json() == missing.json()


def test_parent_and_http_role_change_recheck(policy_store, auth):
    app = create_app(auth_store=auth, corpus_store=policy_store)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client, "hr")
        assert client.get("/citations/parent-3?as_of=2026-10-01").status_code == 200
        auth.set_role("hr", "employee")
        assert client.get("/citations/parent-3?as_of=2026-10-01").status_code == 404
        assert client.get("/session").json()["role"] == "employee"
        assert client.get("/citations/id-1?as_of=2026-09-30").status_code == 404


def test_auth_checked_before_date_errors(policy_store, auth):
    with TestClient(
        create_app(auth_store=auth, corpus_store=policy_store),
        base_url="http://127.0.0.1",
    ) as client:
        assert client.get("/citations/id-1").status_code == 401
        login(client)
        assert client.get("/citations/id-1").status_code == 400
        assert client.get("/citations/id-1?as_of=20261001").status_code == 400


def test_parallel_http_sessions_keep_separate_context(policy_store, auth):
    from concurrent.futures import ThreadPoolExecutor

    app = create_app(auth_store=auth, corpus_store=policy_store)

    def fetch(role):
        with TestClient(app, base_url="http://127.0.0.1") as client:
            login(client, role)
            return client.get("/citations/id-3?as_of=2026-10-01").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(fetch, ["hr", "employee"] * 3)) == [200, 404] * 3


def test_metadata_publication_changes_existing_session_and_citations(corpus, auth):
    store = CorpusStore(corpus.root / "index")
    ingest(corpus.manifest, store=store, embedder=corpus.embedder)
    token, _ = auth.login("employee", "synthetic-password-employee")
    as_of = date(2026, 10, 18)
    principal = auth.authenticate(token)
    chunks = eligible_chunks(principal, as_of, store=store)
    target = next(c for c in chunks if c.document_id == "C02")
    assert read_citation(principal, target.id, as_of, store=store) == target
    corpus.embedder.calls.clear()
    corpus.change("C02", edit_document=lambda d: d.update(allowed_roles=["hr"]))
    ingest(corpus.manifest, store=store, embedder=corpus.embedder)
    assert corpus.embedder.calls == []
    assert target.id not in {
        c.id for c in eligible_chunks(auth.authenticate(token), as_of, store=store)
    }
    with pytest.raises(CitationNotFound):
        read_citation(auth.authenticate(token), target.id, as_of, store=store)
    hr = Principal(user_id="hr", role="hr")
    assert read_citation(hr, target.id, as_of, store=store).id == target.id

    def change_date(document):
        document["effective_from"] = "2026-11-01"
        for section in document["indexed_sections"]:
            section["effective_from"] = "2026-11-01"

    corpus.change("C02", edit_document=change_date)
    ingest(corpus.manifest, store=store, embedder=corpus.embedder)
    assert corpus.embedder.calls == []
    assert target.id not in {c.id for c in eligible_chunks(hr, as_of, store=store)}
    with pytest.raises(CitationNotFound):
        read_citation(hr, target.id, as_of, store=store)
    assert read_citation(hr, target.id, date(2026, 11, 1), store=store).id == target.id
