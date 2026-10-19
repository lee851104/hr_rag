"""階段0的10筆虛構煙霧測試；不是階段1語料或30題品質評估。"""

import hashlib
import json
import math
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import psutil

from hr_rag.contracts import Chunk, ContextBundle
from hr_rag.local_models import LocalEncoder
from hr_rag.providers import CheckedProviders, LlamaGenerator
from hr_rag.settings import RuntimeSettings

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [
    ("請假申請應送去哪個窗口？", "請假申請應送至藍色櫃台。", "藍色櫃台"),
    ("補件表單的代碼是什麼？", "補件表單代碼為F017。", "F017"),
    ("假勤問題應聯繫哪個窗口？", "假勤問題請聯繫綠色窗口。", "綠色窗口"),
    ("內部審核安排在星期幾？", "內部審核安排在每週二。", "週二"),
    ("請假手冊存放在哪裡？", "請假手冊存放在紫色資料夾。", "紫色資料夾"),
    ("申請後要保留哪個編號？", "申請完成後請保留案件編號A203。", "A203"),
    ("附件檔案採用哪種格式？", "附件檔案採用PDF格式。", "PDF"),
    ("代理人的資料填在哪一欄？", "代理人資料填在表單第三欄。", "第三欄"),
    ("撤回申請使用哪張表？", "撤回申請請使用R009表。", "R009"),
    ("申請紀錄存放在哪個資料夾？", "申請紀錄存放在橘色資料夾。", "橘色資料夾"),
]


def bundle(index, text):
    unit = Chunk(
        id=f"smoke-{index}",
        document_id="runtime-fixture",
        version_id="v1",
        section_id=str(index),
        parent_id=f"smoke-{index}",
        text="以下是虛構測試制度：" + text,
        allowed_roles=["employee"],
        effective_from="2026-01-01",
    )
    return ContextBundle(
        units=[unit],
        citation_map={unit.id: [f"runtime-fixture/v1/{index}"]},
        token_count=0,
        dropped_reasons=[],
        config_hash="stage-0-smoke",
    )


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def percentiles(rows):
    seconds = sorted(row["seconds"] for row in rows)
    return {
        "p50_seconds": seconds[math.ceil(len(seconds) * 0.5) - 1],
        "p95_seconds": seconds[math.ceil(len(seconds) * 0.95) - 1],
    }


def main():
    settings = RuntimeSettings()
    result = {
        "sample_count": len(SAMPLES),
        "scope": "階段0虛構煙霧測試，非RAG品質驗收",
        "hardware": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total,
            "available_ram_bytes_at_start": psutil.virtual_memory().available,
        },
        "settings": settings.model_dump(),
        "components": {},
        "artifacts": {},
    }
    report = ROOT / "reports/runtime-smoke.json"

    def save():
        report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 依序釋放encoder，不能同時佔用本機有限RAM。
    for role in ("embedding", "reranker"):
        started = time.perf_counter()
        worker = LocalEncoder(role, ROOT / ".cache/models" / role, settings)
        loaded = time.perf_counter() - started
        provider = CheckedProviders(embedding=worker.embed, ranking=worker.rerank)
        rows = []
        try:
            for index, (question, evidence, _) in enumerate(SAMPLES):
                start = time.perf_counter()
                try:
                    if role == "embedding":
                        vector = provider.embed([question, evidence])
                        passed = vector.shape == (2, 512) and np.allclose(
                            np.linalg.norm(vector, axis=1), 1, atol=1e-5
                        )
                        output = {
                            "shape": list(vector.shape),
                            "finite": bool(np.isfinite(vector).all()),
                        }
                    else:
                        scores = provider.rerank(
                            question, [evidence, "天文館今日播放星球影片。"]
                        )
                        passed = scores[0] > scores[1]
                        output = {"scores": scores}
                    row = {"index": index, "passed": bool(passed), "output": output}
                except Exception as error:
                    row = {
                        "index": index,
                        "passed": False,
                        "error": type(error).__name__,
                    }
                row["seconds"] = round(time.perf_counter() - start, 4)
                rows.append(row)
                print(role, index, row["passed"], row["seconds"], flush=True)
        finally:
            worker.close()
        result["components"][role] = {
            "load_seconds": round(loaded, 4),
            "rows": rows,
            **percentiles(rows),
        }
        save()

    # 不接管既有服務；只啟動並停止此腳本擁有的本機程序。
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8765))
    lock = json.loads((ROOT / "config/models.lock.json").read_text(encoding="utf-8"))
    model_path = ROOT / ".cache/models/generator" / lock["generator"]["filename"]
    runtime = ROOT / ".runtime/llama/llama-server.exe"
    command = [
        str(runtime),
        "-m",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "-c",
        str(settings.context_limit),
        "-t",
        "2",
        "-ngl",
        "0",
        "--parallel",
        "1",
        "--no-webui",
    ]
    rows = []
    exchanges = []
    generator = LlamaGenerator(settings, on_exchange=exchanges.append)
    started = time.perf_counter()
    with (ROOT / "reports/llama-server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW
        )
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + settings.timeout_seconds
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("本機生成服務啟動失敗，查看llama-server.log")
                    try:
                        if client.get(settings.base_url + "/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError("本機生成服務啟動逾時")
                    time.sleep(0.5)
            loaded = time.perf_counter() - started
            provider = CheckedProviders(generation=generator)
            for index, (question, evidence, expected) in enumerate(SAMPLES):
                start = time.perf_counter()
                context = bundle(index, evidence)
                try:
                    answer = provider.generate(question, context)
                    passed = (
                        answer.status == "answered"
                        and expected in " ".join(claim.text for claim in answer.claims)
                        and set(answer.citations) == {f"smoke-{index}"}
                    )
                    row = {
                        "index": index,
                        "passed": passed,
                        "answer": answer.model_dump(mode="json"),
                    }
                except Exception as error:
                    row = {
                        "index": index,
                        "passed": False,
                        "error": type(error).__name__,
                        "code": str(error)
                        if type(error).__name__ == "ProviderError"
                        else None,
                    }
                row["seconds"] = round(time.perf_counter() - start, 4)
                rows.append(row)
                result["components"]["generator"] = {
                    "load_seconds": round(loaded, 4),
                    "rows": rows,
                    **percentiles(rows),
                }
                save()
                print("generator", index, row["passed"], row["seconds"], flush=True)
        finally:
            generator.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    (ROOT / "reports/runtime-exchanges.json").write_text(
        json.dumps(exchanges, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for path in (
        ROOT / "config/models.lock.json",
        ROOT / "requirements.lock",
        model_path,
        ROOT / ".cache/models/embedding/model.safetensors",
        ROOT / ".cache/models/reranker/model.safetensors",
        runtime,
    ):
        result["artifacts"][str(path.relative_to(ROOT))] = sha256(path)
    result["all_passed"] = all(
        len(part["rows"]) == 10 and all(row["passed"] for row in part["rows"])
        for part in result["components"].values()
    )
    save()
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
