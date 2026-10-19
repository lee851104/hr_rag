"""白名單語料匯入；不讀eval/env，不呼叫生成API。"""

import argparse
import hashlib
import json
import uuid
from pathlib import Path

import numpy as np

from hr_rag.corpus.chunking import (
    CHUNKING_VERSION,
    ChunkingError,
    digest,
    load_tokenizer,
    plan_with_tokenizers,
    unbounded_tokenizer,
)
from hr_rag.corpus.manifest import ManifestRecord, validate_manifest
from hr_rag.local_models import LocalEncoder
from hr_rag.settings import PROJECT_ROOT, RuntimeSettings
from hr_rag.storage import CorpusStore


class IngestionError(ValueError):
    """固定錯誤碼；原始正文與第三方例外不寫入一般日誌。"""


def _read_sources(manifest_path):
    raw_manifest = manifest_path.read_bytes()
    if validate_manifest(manifest_path, allow_acl_restrictions=True):
        raise IngestionError("manifest_invalid")
    records = json.loads(raw_manifest)["documents"]
    root = manifest_path.parent.parent
    sources = []
    for record in records:
        contents = []
        for field, expected in [
            ("raw_path", "raw_sha256"),
            ("normalized_path", "content_sha256"),
        ]:
            kind = "raw" if field == "raw_path" else "normalized"
            path = (root / record[field]).resolve()
            if not path.is_relative_to(root / "data" / kind):
                raise IngestionError("manifest_invalid")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != record[expected]:
                raise IngestionError("source_changed")
            contents.append(content)
        sources.append((record, contents[0], contents[1].decode("utf-8")))
    if manifest_path.read_bytes() != raw_manifest:
        raise IngestionError("source_changed")
    return hashlib.sha256(raw_manifest).hexdigest(), sources


def _embedding_config(embedding_revision, max_tokens, tokenizer, reranker_tokenizer):
    locked = json.loads((PROJECT_ROOT / "config/models.lock.json").read_text("utf-8"))[
        "embedding"
    ]
    return {
        "model": {
            "repository": locked["repository"],
            "revision": embedding_revision or locked["revision"],
        },
        "chunking": {
            "version": CHUNKING_VERSION,
            "max_tokens": max_tokens,
            "tokenizer_sha256": hashlib.sha256(tokenizer.to_str().encode()).hexdigest(),
            "reranker_tokenizer_sha256": hashlib.sha256(
                reranker_tokenizer.to_str().encode()
            ).hexdigest(),
        },
    }


def _vectors(db, children, config, embedder, batch_size):
    keys = [digest([item.chunk.text, config]) for item in children]
    texts = {key: item.chunk.text for key, item in zip(keys, children)}
    vectors, missing, dimension = {}, [], None
    for key in texts:
        row = db.execute("SELECT * FROM vector_cache WHERE key=?", (key,)).fetchone()
        if row is None:
            missing.append(key)
            continue
        blob = row["vector"]
        vector = np.frombuffer(blob, dtype="<f4")
        if (
            hashlib.sha256(blob).hexdigest() != row["sha256"]
            or vector.shape != (row["dimensions"],)
            or not np.isfinite(vector).all()
        ):
            raise IngestionError("cache_integrity")
        if dimension is not None and len(vector) != dimension:
            raise IngestionError("invalid_vectors")
        dimension = len(vector)
        vectors[key] = vector
    owned = None
    embedded_count = 0
    try:
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset : offset + batch_size]
            if embedder is None:
                owned = LocalEncoder(
                    "embedding",
                    PROJECT_ROOT / ".cache/models/embedding",
                    RuntimeSettings(),
                )
                embedder = owned
            try:
                result = np.asarray(
                    embedder.embed([texts[key] for key in batch]), dtype="<f4"
                )
            except Exception:
                raise IngestionError("embedding_failed") from None
            if (
                result.ndim != 2
                or len(result) != len(batch)
                or result.shape[1] < 1
                or not np.isfinite(result).all()
                or (dimension is not None and result.shape[1] != dimension)
            ):
                raise IngestionError("invalid_vectors")
            dimension = result.shape[1]
            for key, vector in zip(batch, result):
                blob = vector.tobytes()
                db.execute(
                    "INSERT INTO vector_cache VALUES (?,?,?,?)",
                    (key, dimension, blob, hashlib.sha256(blob).hexdigest()),
                )
                vectors[key] = vector
            embedded_count += len(batch)
    finally:
        if owned is not None:
            owned.close()
    return np.stack([vectors[key] for key in keys]), embedded_count


def ingest(
    manifest_path: Path,
    *,
    store=None,
    embedder=None,
    tokenizer=None,
    reranker_tokenizer=None,
    max_tokens=400,
    embedding_revision=None,
    batch_size=8,
) -> str:
    store = store or CorpusStore()
    manifest_path = Path(manifest_path).resolve()
    if type(batch_size) is not int or batch_size < 1:
        raise IngestionError("invalid_batch_size")
    if type(max_tokens) is not int or not 3 <= max_tokens <= 400:
        raise IngestionError("invalid_chunk_limit")
    if embedding_revision is not None and embedder is None:
        raise IngestionError("revision_requires_explicit_embedder")
    generation_id = uuid.uuid4().hex
    published = False
    try:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            manifest_hash, sources = _read_sources(manifest_path)
            tokenizer = (
                unbounded_tokenizer(tokenizer)
                if tokenizer is not None
                else load_tokenizer()
            )
            reranker_tokenizer = (
                unbounded_tokenizer(reranker_tokenizer)
                if reranker_tokenizer is not None
                else load_tokenizer("reranker")
            )
            config = _embedding_config(
                embedding_revision, max_tokens, tokenizer, reranker_tokenizer
            )
            previous = store.active(db)
            if (
                previous
                and previous["manifest_hash"] == manifest_hash
                and json.loads(previous["config_json"]) == config
            ):
                # 相同內容仍驗證active快照；不掩蓋磁碟損毀。
                store.snapshot()
                return previous["id"]
            parents, children = [], []
            for record, _, normalized in sources:
                plan = plan_with_tokenizers(
                    ManifestRecord.model_validate(record),
                    normalized,
                    (tokenizer, reranker_tokenizer),
                    max_tokens=max_tokens,
                )
                parents.extend(plan.parents)
                children.extend(plan.children)
            children.sort(key=lambda item: item.chunk.id)
            if len({c.chunk.id for c in children}) != len(children):
                raise IngestionError("duplicate_chunk")
            reason = "initial"
            if previous:
                old = json.loads(previous["config_json"])
                reason = "incremental"
                if old["model"] != config["model"]:
                    reason = "embedding_model_changed"
                elif old["chunking"] != config["chunking"]:
                    reason = "chunking_config_changed"
            vectors, embedded_count = _vectors(
                db, children, config, embedder, batch_size
            )
            metadata = {
                "rebuild_reason": reason,
                "embedded_count": embedded_count,
                "reused_count": len(children) - embedded_count,
                "config": config,
            }
            snapshot_hash = store.write_snapshot(generation_id, vectors)
            db.execute(
                "INSERT INTO generations VALUES (?,?,?,?,?,?,?)",
                (
                    generation_id,
                    manifest_hash,
                    json.dumps(config),
                    json.dumps(metadata),
                    snapshot_hash,
                    len(vectors),
                    vectors.shape[1],
                ),
            )
            for record, raw, normalized in sources:
                db.execute(
                    "INSERT INTO documents VALUES (?,?,?,?,?,?)",
                    (
                        generation_id,
                        record["document_id"],
                        record["version_id"],
                        json.dumps(record, ensure_ascii=False),
                        raw,
                        normalized,
                    ),
                )
            for parent in parents:
                db.execute(
                    "INSERT INTO units VALUES (?,?,?,?,?,?)",
                    (
                        generation_id,
                        parent.id,
                        1,
                        parent.model_dump_json(),
                        None,
                        "{}",
                    ),
                )
            for row_index, item in enumerate(children):
                location = {
                    "start": item.start,
                    "end": item.end,
                    "token_count": item.token_count,
                }
                db.execute(
                    "INSERT INTO units VALUES (?,?,?,?,?,?)",
                    (
                        generation_id,
                        item.chunk.id,
                        0,
                        item.chunk.model_dump_json(),
                        row_index,
                        json.dumps(location),
                    ),
                )
            db.execute(
                "INSERT INTO active VALUES (1,?) ON CONFLICT(singleton) "
                "DO UPDATE SET generation_id=excluded.generation_id",
                (generation_id,),
            )
        published = True
        return generation_id
    except (IngestionError, ChunkingError) as exc:
        code = str(exc)
        store.record_failure(code)
        raise IngestionError(code) from None
    except Exception:
        store.record_failure("ingestion_failed")
        raise IngestionError("ingestion_failed") from None
    finally:
        if not published:
            (store.root / "snapshots" / (generation_id + ".npy")).unlink(
                missing_ok=True
            )


def withdraw(document_id: str, version_id: str, *, store=None) -> None:
    (store or CorpusStore()).withdraw(document_id, version_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / "data/manifest.json"
    )
    args = parser.parse_args()
    try:
        generation = ingest(args.manifest)
    except IngestionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, "generation_id": generation}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
