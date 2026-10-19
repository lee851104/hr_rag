"""7.1最終凍結：設定、程式、評估資料與語料的hash；保留題執行前必須完全相符。"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from hr_rag.settings import PROJECT_ROOT

FREEZE_PATH = PROJECT_ROOT / "eval/final.freeze.json"
PATTERNS = [
    "pyproject.toml",
    "requirements.lock",
    "config/*.json",
    "config/history/*.json",
    "data/manifest.json",
    "eval/*.jsonl",
    "eval/*.json",
    "src/hr_rag/**/*.py",
    "src/hr_rag/templates/*.html",
    "src/hr_rag/static/*.css",
    # 合併30題時使用的開發集證據，看過保留題結果後不得替換。
    "reports/stage5-human-review-*.json",
    "reports/retrieval-stage5-verbatim-v3.json",
]
EXCLUDED = {"eval/final.freeze.json"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root: Path, patterns) -> dict:
    root = Path(root)
    files = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            name = path.relative_to(root).as_posix()
            if path.is_file() and name not in EXCLUDED:
                files[name] = _digest(path)
    return dict(sorted(files.items()))


def configuration_summary() -> dict:
    """凍結時的關鍵值，方便報告閱讀；權威仍是files內的hash。"""
    from hr_rag.generation import load_selected_generation
    from hr_rag.query import synonyms_hash
    from hr_rag.verbatim import VerbatimGenerator

    config, settings = load_selected_generation()
    lock = json.loads((PROJECT_ROOT / "config/models.lock.json").read_text("utf-8"))
    retrieval = json.loads(
        (PROJECT_ROOT / "config/retrieval.selected.json").read_text("utf-8")
    )
    monitoring = json.loads(
        (PROJECT_ROOT / "config/monitoring.json").read_text("utf-8")
    )
    return {
        "generation": {
            "mode": config["mode"],
            "model": settings.model,
            "prompt_sha256": hashlib.sha256(
                VerbatimGenerator.SYSTEM.encode("utf-8")
            ).hexdigest(),
            "context_limit": settings.context_limit,
            "evidence_budget": settings.evidence_budget,
            "output_reserve": settings.output_reserve,
            "safety_margin": settings.safety_margin,
            "timeout": settings.timeout_seconds,
            "max_retries": settings.max_retries,
        },
        "encoders": {
            name: {k: lock[name][k] for k in ("repository", "revision")}
            for name in ("embedding", "reranker")
        },
        "retrieval": retrieval["context_settings"],
        "synonyms_sha256": synonyms_hash(),
        "monitoring": {
            k: monitoring[k]
            for k in (
                "window",
                "error_rate",
                "consecutive_model_failures",
                "p95_seconds",
            )
        },
        "cost_cap_usd": "1",
    }


def write_freeze(target: Path, *, root=PROJECT_ROOT, patterns=PATTERNS, extra=None):
    target = Path(target)
    if target.exists():
        # 重新凍結必須另行決定並保留舊檔，不在此覆寫。
        raise ValueError("freeze_exists")
    record = {
        "status": "frozen",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "patterns": list(patterns),
        **(extra or {}),
        "files": collect(root, patterns),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record


def verify_final_freeze(path: Path = FREEZE_PATH, *, root=PROJECT_ROOT) -> dict:
    record = json.loads(Path(path).read_text("utf-8"))
    current = collect(root, record["patterns"])
    changed = sorted(
        name
        for name in set(current) | set(record["files"])
        if current.get(name) != record["files"].get(name)
    )
    if record.get("status") != "frozen" or changed:
        raise ValueError("final_freeze_changed:" + ",".join(changed))
    return record["files"]


def main():
    parser = argparse.ArgumentParser(description="7.1最終凍結")
    parser.add_argument("command", choices=["write", "verify"])
    args = parser.parse_args()
    if args.command == "write":
        from hr_rag.evaluation import execution_fingerprint
        from hr_rag.storage import CorpusStore

        store = CorpusStore()
        with store.connect() as db:
            active = store.active(db)
        record = write_freeze(
            FREEZE_PATH,
            extra={
                "configuration": configuration_summary(),
                "corpus": {
                    "generation_id": active["id"],
                    "manifest_sha256": active["manifest_hash"],
                    "execution_fingerprint": execution_fingerprint(store),
                },
            },
        )
        print(json.dumps({"files": len(record["files"])}, ensure_ascii=False))
    else:
        print(json.dumps({"verified_files": len(verify_final_freeze())}))


if __name__ == "__main__":
    main()
