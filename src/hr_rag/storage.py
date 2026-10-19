"""SQLite世代與不可變NumPy快照；讀者只取已commit的active資料。"""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from hr_rag.contracts import Chunk
from hr_rag.settings import PROJECT_ROOT


@dataclass(frozen=True)
class Snapshot:
    generation_id: str
    chunks: tuple[Chunk, ...]
    parents: dict[str, Chunk]
    vectors: np.ndarray
    locations: dict[str, dict]
    documents: tuple[dict, ...]
    metadata: dict


class CorpusStore:
    def __init__(self, root: Path = PROJECT_ROOT / ".runtime/corpus"):
        self.root = Path(root).resolve()
        (self.root / "snapshots").mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL,
                    config_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL, rows INTEGER NOT NULL,
                    dimensions INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    generation_id TEXT NOT NULL REFERENCES generations(id)
                );
                CREATE TABLE IF NOT EXISTS documents (
                    generation_id TEXT NOT NULL REFERENCES generations(id),
                    document_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    record_json TEXT NOT NULL, raw_content BLOB NOT NULL,
                    normalized_content TEXT NOT NULL,
                    PRIMARY KEY(generation_id,document_id,version_id)
                );
                CREATE TABLE IF NOT EXISTS units (
                    generation_id TEXT NOT NULL REFERENCES generations(id),
                    id TEXT NOT NULL, parent INTEGER NOT NULL,
                    chunk_json TEXT NOT NULL, row_index INTEGER,
                    location_json TEXT NOT NULL,
                    PRIMARY KEY(generation_id,id)
                );
                CREATE TABLE IF NOT EXISTS vector_cache (
                    key TEXT PRIMARY KEY, dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL, sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS withdrawals (
                    document_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    PRIMARY KEY(document_id,version_id)
                );
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY, code TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "corpus.sqlite3", timeout=180)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def active(self, db):
        return db.execute(
            "SELECT g.* FROM generations g JOIN active a ON a.generation_id=g.id"
        ).fetchone()

    def write_snapshot(self, generation_id, vectors):
        target = self.root / "snapshots" / (generation_id + ".npy")
        staging = target.with_suffix(".staging")
        try:
            with staging.open("xb") as file:
                np.save(file, vectors, allow_pickle=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(staging, target)
            return hashlib.sha256(target.read_bytes()).hexdigest()
        finally:
            staging.unlink(missing_ok=True)

    def record_failure(self, code):
        with self.connect() as db:
            db.execute("INSERT INTO failures(code) VALUES (?)", (code,))

    def failures(self):
        with self.connect() as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM failures ORDER BY id")
            ]

    def withdraw(self, document_id, version_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO withdrawals VALUES (?,?)",
                (document_id, version_id),
            )

    def snapshot(self, *, role=None, as_of: date | None = None):
        """受信任的本機讀取；role須由未來的伺服器Principal提供。"""
        if role is not None and role not in {"employee", "manager", "hr"}:
            raise ValueError("invalid_role")
        if as_of is not None and type(as_of) is not date:
            raise ValueError("invalid_date")
        with self.connect() as db:
            db.execute("BEGIN")
            active = self.active(db)
            if active is None:
                return None
            generation_id = active["id"]
            path = self.root / "snapshots" / (generation_id + ".npy")
            try:
                if (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    != active["snapshot_hash"]
                ):
                    raise ValueError
                vectors = np.load(path, allow_pickle=False)
                if (
                    vectors.shape != (active["rows"], active["dimensions"])
                    or not np.isfinite(vectors).all()
                ):
                    raise ValueError
            except (OSError, ValueError):
                raise ValueError("snapshot_integrity") from None
            withdrawn = {tuple(row) for row in db.execute("SELECT * FROM withdrawals")}

            def eligible(chunk):
                return (
                    (chunk.document_id, chunk.version_id) not in withdrawn
                    and (role is None or role in chunk.allowed_roles)
                    and (
                        as_of is None
                        or (
                            chunk.effective_from is not None
                            and chunk.effective_from <= as_of
                            and (
                                chunk.effective_to is None or as_of < chunk.effective_to
                            )
                        )
                    )
                )

            children, parents, indices, locations = [], {}, [], {}
            for row in db.execute(
                "SELECT * FROM units WHERE generation_id=? ORDER BY row_index,id",
                (generation_id,),
            ):
                try:
                    chunk = Chunk.model_validate_json(row["chunk_json"])
                except ValidationError:
                    if role is not None:
                        continue
                    raise ValueError("invalid_chunk_metadata") from None
                if not eligible(chunk):
                    continue
                if row["parent"]:
                    parents[chunk.id] = chunk
                else:
                    children.append(chunk)
                    indices.append(row["row_index"])
                    locations[chunk.id] = json.loads(row["location_json"])
            documents = tuple(
                json.loads(row[0])
                for row in db.execute(
                    "SELECT record_json FROM documents WHERE generation_id=? "
                    "ORDER BY document_id,version_id",
                    (generation_id,),
                )
                if eligible_document(json.loads(row[0]), withdrawn, role, as_of)
            )
            return Snapshot(
                generation_id,
                tuple(children),
                parents,
                vectors[indices],
                locations,
                documents,
                json.loads(active["metadata_json"]),
            )


def eligible_document(document, withdrawn, role, as_of):
    return (
        (document["document_id"], document["version_id"]) not in withdrawn
        and (role is None or role in document["allowed_roles"])
        and (
            as_of is None
            or (
                document["effective_from"] is not None
                and date.fromisoformat(document["effective_from"]) <= as_of
                and (
                    document["effective_to"] is None
                    or as_of < date.fromisoformat(document["effective_to"])
                )
            )
        )
    )
