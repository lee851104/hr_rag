"""0.8 明確命令才執行的API比較；固定證據、累計上限、逐題保存。"""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from hr_rag.contracts import Chunk, ContextBundle
from hr_rag.providers import OpenAIGenerator, ProviderError
from hr_rag.settings import (
    OpenAISettings,
    RuntimeSettings,
    load_generation_environment,
)

# 2026-10-18查證官方模型頁；0.9才凍結正式設定。皆無推理tokens。
MODELS = {
    "gpt-4.1-mini-2025-04-14": ("0.40", "1.60"),
    "gpt-4.1-2025-04-14": ("2.00", "8.00"),
}
PRICING_CHECKED_ON = "2026-10-18"


def model_settings(model, root):
    if model not in MODELS:
        raise ValueError("model_not_in_priced_candidates")
    input_price, output_price = MODELS[model]
    return OpenAISettings(
        model=model,
        input_usd_per_million=input_price,
        output_usd_per_million=output_price,
        pricing_checked_on=PRICING_CHECKED_ON,
        cost_ledger_path=root / ".runtime/openai-cost.sqlite3",
    )


@contextmanager
def capped_environment():
    """使用既有憑證；只暫時覆寫非機密成本上限，絕不提高.env的上限。"""
    try:
        values = load_generation_environment()
        limit = Decimal(values.get("HR_RAG_COST_LIMIT_USD", ""))
        if not values.get("OPENAI_API_KEY", "").strip():
            raise ValueError
        if not limit.is_finite() or limit <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        raise ProviderError("not_configured") from None
    limit = min(limit, Decimal("1"))
    previous = os.environ.get("HR_RAG_COST_LIMIT_USD")
    os.environ["HR_RAG_COST_LIMIT_USD"] = str(limit)
    try:
        yield limit
    finally:
        if previous is None:
            os.environ.pop("HR_RAG_COST_LIMIT_USD", None)
        else:
            os.environ["HR_RAG_COST_LIMIT_USD"] = previous


def ledger_totals(path):
    settled, reserved, count = Decimal(0), Decimal(0), 0
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            for amount, done in db.execute("SELECT amount, settled FROM costs"):
                if done:
                    settled += Decimal(amount)
                else:
                    reserved += Decimal(amount)
                count += 1
    return {
        "settled_usd": str(settled),
        "reserved_usd": str(reserved),
        "total_usd": str(settled + reserved),
        "requests": count,
    }


def save_run(path, result, secret):
    report = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"runs": []}
    )
    sanitized = OpenAIGenerator._redact(result, secret)
    for index, previous in enumerate(report["runs"]):
        if previous["id"] == result["id"]:
            report["runs"][index] = sanitized
            break
    else:
        report["runs"].append(sanitized)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_context(fixture, evidence):
    units = {unit["id"]: unit for unit in evidence["units"]}
    chunks = tuple(
        Chunk(
            id=uid,
            document_id=units[uid]["document_id"],
            version_id=f"snapshot-{fixture.FETCHED_AT}",
            section_id=uid,
            parent_id=uid,
            text=units[uid]["text"],
            allowed_roles=("employee", "manager", "hr"),
            effective_from=units[uid].get("published_at"),
        )
        for uid in fixture.BUNDLE
    )
    digest = hashlib.sha256(
        json.dumps(
            [unit.model_dump(mode="json") for unit in chunks],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return ContextBundle(
        units=chunks,
        citation_map={uid: (units[uid]["source_url"],) for uid in fixture.BUNDLE},
        token_count=0,
        dropped_reasons=(),
        config_hash=digest,
    )


def summarize(rows, timeout):
    totals = sorted(row["total_seconds"] for row in rows)
    passed = sum(row["checks"]["auto_pass"] for row in rows)
    traditional = bool(rows) and all(
        row["checks"].get("traditional", False) for row in rows
    )
    below_timeout = bool(rows) and max(totals) < timeout
    cost = sum(
        (
            Decimal(str(exchange["cost"]))
            for row in rows
            for exchange in row.get("exchanges", [])
            if exchange.get("cost") is not None
        ),
        Decimal(0),
    )
    reserved = sum(
        (Decimal(row.get("reserved_cost_usd", "0")) for row in rows), Decimal(0)
    )
    unknown = any(
        exchange.get("cost") is None
        for row in rows
        for exchange in row.get("exchanges", [])
    )
    complete_cost = not unknown and reserved == 0
    return {
        "count": len(rows),
        "auto_pass": passed,
        "all_traditional": traditional,
        "all_below_timeout": below_timeout,
        "p50_total_seconds": totals[(len(totals) - 1) // 2] if totals else None,
        "p95_total_seconds": totals[-1] if totals else None,
        "known_cost_usd": str(cost),
        "cost_usd": str(cost) if complete_cost else None,
        "reserved_cost_usd": str(reserved),
        "accounted_cost_usd": str(cost + reserved),
        "cost_complete": complete_cost,
        "mean_cost_usd": str(cost / len(rows)) if rows and complete_cost else None,
        "automatic_gate_pass": len(rows) == 5
        and passed >= 4
        and traditional
        and below_timeout
        and complete_cost,
        "manual_review": "pending",
    }


def run(models, fixture):
    """只比較指定候選；每個候選固定完整F1–F5，不自動換模型或重跑失敗題。"""
    import numpy as np
    import psutil

    from hr_rag.local_models import LocalEncoder

    if not models or len(set(models)) != len(models):
        raise ValueError("unique_models_required")
    configurations = [model_settings(model, fixture.ROOT) for model in models]
    report_path = fixture.ROOT / "reports/feasibility-long-context-openai.json"
    with capped_environment() as limit, ExitStack() as stack:
        secret = load_generation_environment()["OPENAI_API_KEY"].strip()
        ledger = configurations[0].cost_ledger_path
        baseline = ledger_totals(ledger)
        if Decimal(baseline["total_usd"]) >= limit:
            raise ProviderError("cost_limit")
        evidence = json.loads(fixture.EVIDENCE_PATH.read_text(encoding="utf-8"))
        context = build_context(fixture, evidence)
        children = [child for unit in evidence["units"] for child in unit["children"]]
        generators = []
        for settings in configurations:
            generator = OpenAIGenerator(settings)
            stack.callback(generator.close)
            # 全部請求先做離線token預檢；超額不啟動encoder或發送API。
            for spec in fixture.QUESTIONS:
                generator._payload(spec["question"], context)
            generators.append(generator)
        watch = fixture.MemoryWatch(psutil)
        stack.callback(watch.close)
        result = {
            "id": str(uuid4()),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "strategy": "resident",
            "cost_limit_usd": str(limit),
            "ledger_before": baseline,
            "evidence_sha256": fixture.sha256_file(fixture.EVIDENCE_PATH),
            "original_local_report_sha256": fixture.sha256_file(fixture.REPORT_PATH),
            "models_lock_sha256": fixture.sha256_file(
                fixture.ROOT / "config/models.lock.json"
            ),
            "evidence_units": len(evidence["units"]),
            "context_ids": fixture.BUNDLE,
            "context_hash": context.config_hash,
            "loads": {},
            "models": [],
            "status": "running",
            "manual_review": "pending",
        }

        def save():
            result["ledger_after"] = ledger_totals(ledger)
            save_run(report_path, result, secret)

        save()
        encoders = []
        try:
            for role in ("embedding", "reranker"):
                started = time.perf_counter()
                encoder = LocalEncoder(
                    role, fixture.ROOT / ".cache/models" / role, RuntimeSettings()
                )
                stack.callback(encoder.close)
                watch.track(encoder.process.pid)
                encoders.append(encoder)
                result["loads"][role] = round(time.perf_counter() - started, 4)
                print(f"{role}: ready", flush=True)
            embedder, reranker = encoders
            started = time.perf_counter()
            index = np.asarray(embedder.embed([child["text"] for child in children]))
            result["index_seconds"] = round(time.perf_counter() - started, 4)
            result["resident_rss_bytes"] = {
                str(pid): rss for pid, rss in watch.rss().items()
            }
            result["encoder_pids"] = {
                role: worker.process.pid
                for role, worker in zip(("embedding", "reranker"), encoders)
            }
            for settings, generator in zip(configurations, generators):
                model_result = {
                    "model": settings.model,
                    "settings": settings.model_dump(mode="json"),
                    "rows": [],
                }
                result["models"].append(model_result)
                for spec in fixture.QUESTIONS:
                    started = time.perf_counter()
                    row = {
                        "id": spec["id"],
                        "question": spec["question"],
                        "exchanges": [],
                        "ledger_before": ledger_totals(ledger),
                    }
                    generator.on_exchange = row["exchanges"].append
                    try:
                        vector = embedder.embed([spec["question"]])[0]
                        order = np.argsort(-(index @ vector), kind="stable")[
                            : fixture.CANDIDATES
                        ]
                        row["embed_query_seconds"] = round(
                            time.perf_counter() - started, 4
                        )
                        candidates = [children[i] for i in order]
                        rerank_started = time.perf_counter()
                        scores = reranker.rerank(
                            spec["question"], [child["text"] for child in candidates]
                        )
                        row["rerank_seconds"] = round(
                            time.perf_counter() - rerank_started, 4
                        )
                        ranked = sorted(
                            zip(scores, (child["id"] for child in candidates)),
                            reverse=True,
                        )
                        row["rerank_top5"] = [cid for _, cid in ranked[:5]]
                        api_started = time.perf_counter()
                        try:
                            answer = generator.generate(spec["question"], context)
                            row["answer"] = answer.model_dump(mode="json")
                            row["checks"] = fixture.check_answer(
                                spec, answer, set(fixture.BUNDLE)
                            )
                        finally:
                            row["api_seconds"] = round(
                                time.perf_counter() - api_started, 4
                            )
                    except ProviderError as error:
                        row["error"] = str(error)
                        row["checks"] = {"auto_pass": False}
                    row["total_seconds"] = round(time.perf_counter() - started, 4)
                    row["ledger_after"] = ledger_totals(ledger)
                    row["reserved_cost_usd"] = str(
                        Decimal(row["ledger_after"]["reserved_usd"])
                        - Decimal(row["ledger_before"]["reserved_usd"])
                    )
                    model_result["rows"].append(row)
                    model_result["summary"] = summarize(
                        model_result["rows"], settings.timeout_seconds
                    )
                    result["memory"] = watch.peak()
                    save()
                    print(
                        settings.model,
                        spec["id"],
                        row["checks"]["auto_pass"],
                        row.get("error", "ok"),
                        flush=True,
                    )
                    if row.get("error") in {
                        "cost_limit",
                        "not_configured",
                        "audit_failure",
                        "unavailable",
                        "rate_limited",
                        "timeout",
                    }:
                        raise ProviderError(row["error"])
            result["status"] = "completed"
        except ProviderError as error:
            result["status"] = "stopped"
            result["error"] = str(error)
            return 1
        except Exception:
            # 不輸出SDK／環境例外正文；逐題已保存的結果仍保留。
            result["status"] = "stopped"
            result["error"] = "unavailable"
            return 1
        finally:
            result["memory"] = watch.peak()
            result["finished_at"] = datetime.now(timezone.utc).isoformat()
            save()
    return 0
