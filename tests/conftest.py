"""隔離的資料匯入 fixture；不複製或讀取 env／評估資料。"""

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hr_rag.auth import AuthStore
from hr_rag.contracts import Chunk
from hr_rag.storage import CorpusStore


class CountingEmbedder:
    def __init__(self):
        self.calls = []
        self.fail_on = None

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail_on == len(self.calls):
            raise RuntimeError("synthetic failure")
        return np.array(
            [[len(t), sum(t.encode("utf-8")) % 97, 1] for t in texts], dtype=np.float32
        )


@pytest.fixture
def corpus(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "data", tmp_path / "data")
    manifest = tmp_path / "data/manifest.json"

    def change(document_id, edit_document=None, edit_sections=None, version_id=None):
        data = json.loads(manifest.read_text("utf-8"))
        for document in data["documents"]:
            if document["document_id"] != document_id or (
                version_id and document["version_id"] != version_id
            ):
                continue
            if edit_document:
                edit_document(document)
            if edit_sections:
                p = tmp_path / document["normalized_path"]
                norm = json.loads(p.read_text("utf-8"))
                edit_sections(norm["sections"])
                p.write_text(
                    json.dumps(norm, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                document["content_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
                ids = {s["section_id"] for s in norm["sections"]}
                document["indexed_sections"] = [
                    s for s in document["indexed_sections"] if s["section_id"] in ids
                ]
                # 合成公司fixture的raw與normalized一起更新，不冒充原正式資料。
                raw = tmp_path / document["raw_path"]
                raw.write_text(
                    "虛構測試資料\n" + "\n".join(s["text"] for s in norm["sections"]),
                    encoding="utf-8",
                )
                document["raw_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
        manifest.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return SimpleNamespace(
        root=tmp_path, manifest=manifest, change=change, embedder=CountingEmbedder()
    )


@pytest.fixture
def auth(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    for user in ("employee", "manager", "hr"):
        store.set_password(user, "synthetic-password-" + user)
    return store


@pytest.fixture
def policy_store(tmp_path):
    store = CorpusStore(tmp_path / "synthetic-policy")
    vectors = np.ones((5, 3), dtype=np.float32)
    sha = store.write_snapshot("synthetic", vectors)
    with store.connect() as db:
        db.execute(
            "INSERT INTO generations VALUES (?,?,?,?,?,?,?)",
            ("synthetic", "test", "{}", "{}", sha, 5, 3),
        )
        db.execute("INSERT INTO active VALUES (1,'synthetic')")
        for index, (doc, roles, start, end) in enumerate(
            [
                ("C01", ["employee", "manager", "hr"], "2026-01-01", "2026-10-01"),
                ("C01", ["employee", "manager", "hr"], "2026-10-01", None),
                ("C03", ["manager", "hr"], "2026-01-01", None),
                ("C04", ["hr"], "2026-01-01", None),
                ("unknown", ["hr"], None, None),
            ]
        ):
            chunk = Chunk(
                id=f"id-{index}",
                document_id=doc,
                version_id=f"v{index}",
                section_id="section",
                parent_id=f"parent-{index}",
                text=f"合成限閱正文-{doc}",
                allowed_roles=roles,
                effective_from=start,
                effective_to=end,
            )
            db.execute(
                "INSERT INTO units VALUES (?,?,?,?,?,?)",
                ("synthetic", chunk.id, 0, chunk.model_dump_json(), index, "{}"),
            )
            parent = chunk.model_copy(update={"id": chunk.parent_id})
            db.execute(
                "INSERT INTO units VALUES (?,?,?,?,?,?)",
                ("synthetic", parent.id, 1, parent.model_dump_json(), None, "{}"),
            )
    return store


# 原於test_answering；網頁與追溯測試共用同一合成文件資料。
@pytest.fixture
def answer_store(policy_store, monkeypatch, tmp_path):
    monkeypatch.setenv("HR_RAG_EVENT_PATH", str(tmp_path / "events.jsonl"))
    with policy_store.connect() as db:
        for doc, version, roles in [
            ("C01", "v1", ["employee", "manager", "hr"]),
            ("C03", "v2", ["manager", "hr"]),
            ("C04", "v3", ["hr"]),
        ]:
            record = dict(
                document_id=doc,
                version_id=version,
                title="合成來源" + doc,
                source_type="official" if doc == "C03" else "company",
                is_synthetic=doc != "C03",
                source_url=None,
                effective_from="2026-10-01",
                effective_to=None,
                allowed_roles=roles,
            )
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?)",
                (
                    "synthetic",
                    doc,
                    version,
                    json.dumps(record),
                    b"",
                    "{}",
                ),
            )
    return policy_store
