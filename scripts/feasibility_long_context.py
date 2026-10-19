"""階段0.7真實長度可行性實測。

5題是可調整的可行性樣本，不是30題評估集或保留題；證據取自公開法規單條頁與
勞動部問答頁的快照，不是階段1的正式語料。檢索只用來量測延遲，送入生成的上下文
固定為 BUNDLE，以免把檢索品質混進生成可行性。

用法（專案根目錄）：
    python -I scripts/feasibility_long_context.py extract
    python -I scripts/feasibility_long_context.py run --strategy resident
    python -I scripts/feasibility_long_context.py run --strategy sequential
"""

import argparse
import hashlib
import html
import json
import math
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / ".cache/feasibility-0.7/raw"
EVIDENCE_PATH = ROOT / "reports/feasibility-long-context-evidence.json"
REPORT_PATH = ROOT / "reports/feasibility-long-context.json"
LAW_URL = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={ref}"
QA_URL = "https://www.mol.gov.tw/1607/28690/2282/2284/2292/{ref}/post"
PCODES = {"O01": "N0030001", "O02": "N0030002", "O03": "N0030006"}
FETCHED_AT = "2026-10-18"
CHILD_TOKEN_LIMIT = 400
CANDIDATES = 20

# (unit_id, document_id, 條號或問答頁編號)；其餘條文只當檢索候選池的雜訊。
SOURCES = [
    ("O01-36", "O01", "36"),
    ("O01-37", "O01", "37"),
    ("O01-38", "O01", "38"),
    ("O01-39", "O01", "39"),
    ("O01-40", "O01", "40"),
    ("O01-41", "O01", "41"),
    ("O02-05", "O02", "5"),
    ("O02-24", "O02", "24"),
    ("O02-24-1", "O02", "24-1"),
    ("O03-02", "O03", "2"),
    ("O03-03", "O03", "3"),
    ("O03-04", "O03", "4"),
    ("O03-05", "O03", "5"),
    ("O03-06", "O03", "6"),
    ("O03-07", "O03", "7"),
    ("O03-08", "O03", "8"),
    ("O03-09", "O03", "9"),
    ("O03-10", "O03", "10"),
    ("O05", "O05", "81186"),
    ("O06", "O06", "81173"),
]

# 送入生成的固定上下文：4個相關父段＋1個病假雜訊段；每題至少另有3段無關。
BUNDLE = ["O01-38", "O02-24-1", "O03-04", "O05", "O06"]

# facts：每組任一正規式需出現在主張文字；citations：每組至少引用其中一個ID。
QUESTIONS = [
    {
        "id": "F1",
        "type": "直接查詢",
        "question": "我在同一家公司已經連續工作滿4年，依法每年有幾天特休？",
        "expected_status": "answered",
        "facts": [["十四", "14"]],
        "citations": [["O01-38"]],
        "expected": "三年以上五年未滿者，每年十四日（勞基法第38條第1項第4款）",
    },
    {
        "id": "F2",
        "type": "改寫",
        "question": "我已經請好的病假，公司可以自己把它改成特休嗎？",
        "expected_status": "answered",
        # 「不得」須指向更改，避免誤配「不得超過三十日」這類無關條文。
        "facts": [
            [r"不得.{0,12}(更改|改為|改成|變更)", r"不(可以?|能|允許).{0,6}(改|更)"],
            [r"病.{0,2}假"],
        ],
        "citations": [["O05"]],
        "expected": "不可以；雇主不得將勞工已請的事（病）假擅自更改為特別休假"
        "（勞動部問答）",
    },
    {
        "id": "F3",
        "type": "多重主張",
        "question": "公司特休採曆年制，如果我年中離職時還有特休沒休完，"
        "天數要用什麼方式計算？沒休的部分公司要怎麼處理？",
        "expected_status": "answered",
        "facts": [["到職日", "週年制"], ["工資"]],
        "citations": [["O06"]],
        "expected": "契約終止時依到職日（週年制）計算特休日數；"
        "契約終止未休日數雇主應發給工資",
    },
    {
        "id": "F4",
        "type": "計算規則",
        "question": "月薪制員工到年度終結還有特休沒休完，公司發給的一日工資要怎麼算？",
        "expected_status": "answered",
        "facts": [["三十", "30"], ["一個月", "1個月"]],
        "citations": [["O02-24-1"]],
        "expected": "年度終結前最近一個月正常工作時間所得之工資除以三十；"
        "按未休日數乘以一日工資（施行細則第24-1條）",
    },
    {
        "id": "F5",
        "type": "資料不足",
        "question": "我今年還剩下幾天特休沒有休？",
        "expected_status": "insufficient",
        "facts": [],
        "citations": [],
        "expected": "資料不足：證據沒有個人假勤紀錄，不得捏造天數",
    },
]

# cp950以外的漢字多為簡體；這幾個簡體字在cp950內，另外列出。
SIMPLIFIED_IN_CP950 = set("与么于后机构")


def clean(fragment):
    text = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_law(page):
    title = clean(re.search(r'id="hlLawName"[^>]*>(.*?)</a>', page, re.S).group(1))
    number = clean(re.search(r'<div class="col-no">(.*?)</div>', page, re.S).group(1))
    block = re.search(r'<div class="law-article">(.*?)</div></div>', page, re.S)
    lines = re.findall(
        r'<div class="line-\d+[^"]*">(.*?)</div>', block.group(1) + "</div>"
    )
    return {"header": f"{title} {number}", "lines": [clean(line) for line in lines]}


def parse_qa(page):
    question = clean(
        re.search(r"<th[^>]*>問題</th>\s*<td>(.*?)</td", page, re.S).group(1)
    )
    answer = re.search(r"<th>答案</th>\s*<td>(.*?)</td>\s*</tr>", page, re.S).group(1)
    paragraphs = [clean(p) for p in re.findall(r"<p>(.*?)</p>", answer, re.S)]
    published = re.search(r"發布日期:(\d{4}-\d{2}-\d{2})", page).group(1)
    updated = re.search(r"更新日期:(\d{4}-\d{2}-\d{2})", page).group(1)
    answer_lines = [p for p in paragraphs if p]
    answer_lines[0] = "答：" + answer_lines[0]
    return {
        "header": f"勞動部問答（發布日期 {published}）",
        "lines": ["問：" + question, *answer_lines],
        "published_at": published,
        "item_updated_at": updated,
    }


def split_children(unit, tokenizers):
    """依項或段落合併成不超過上限的子片段；單行超限就失敗，不截斷。"""

    def count(text):
        return max(len(t.encode(text).ids) for t in tokenizers.values())

    pieces = []
    for line in unit["lines"]:
        # 問答常把「一、」「二、」寫在同一段：先依款次拆，仍超限再依句號拆。
        for part in re.split(r"(?<=。)(?=[二三四五六七八九十]、)", line):
            if count(unit["header"] + "\n" + part) <= CHILD_TOKEN_LIMIT:
                pieces.append(part)
            else:
                pieces.extend(s for s in re.split(r"(?<=。)", part) if s)

    children, current = [], []
    for line in pieces:
        candidate = "\n".join([unit["header"], *current, line])
        if current and count(candidate) > CHILD_TOKEN_LIMIT:
            children.append(current)
            current = [line]
        else:
            current.append(line)
    children.append(current)
    result = []
    for index, lines in enumerate(children):
        text = "\n".join([unit["header"], *lines])
        tokens = {name: len(t.encode(text).ids) for name, t in tokenizers.items()}
        if max(tokens.values()) > CHILD_TOKEN_LIMIT:
            raise ValueError(f"{unit['id']} 單一項超過子片段上限，需人工處理")
        result.append({"id": f"{unit['id']}#{index}", "text": text, "tokens": tokens})
    return result


def extract():
    from tokenizers import Tokenizer

    tokenizers = {
        role: Tokenizer.from_file(str(ROOT / ".cache/models" / role / "tokenizer.json"))
        for role in ("embedding", "reranker")
    }
    units = []
    for unit_id, document_id, ref in SOURCES:
        raw = (RAW / f"{unit_id}.html").read_bytes()
        page = raw.decode("utf-8")
        if document_id in PCODES:
            parsed = parse_law(page)
            url = LAW_URL.format(pcode=PCODES[document_id], ref=ref)
            kind = "law_article"
        else:
            parsed = parse_qa(page)
            url = QA_URL.format(ref=ref)
            kind = "interpretive_qa"
        if not parsed["lines"]:
            raise ValueError(f"{unit_id} 沒有解析出正文")
        unit = {
            "id": unit_id,
            "document_id": document_id,
            "kind": kind,
            "source_url": url,
            "fetched_at": FETCHED_AT,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            **parsed,
            "text": "\n".join([parsed["header"], *parsed["lines"]]),
        }
        unit["children"] = split_children(unit, tokenizers)
        units.append(unit)
    payload = {
        "scope": "階段0.7可行性樣本證據；公開來源單條快照，不是階段1正式語料",
        "child_token_limit": CHILD_TOKEN_LIMIT,
        "units": units,
    }
    EVIDENCE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for unit in units:
        sizes = [max(child["tokens"].values()) for child in unit["children"]]
        print(unit["id"], len(unit["text"]), "字", "子片段tokens", sizes)


def simplified_chars(text):
    found = set()
    for char in text:
        if "一" <= char <= "鿿":
            try:
                char.encode("cp950")
            except UnicodeEncodeError:
                found.add(char)
                continue
            if char in SIMPLIFIED_IN_CP950:
                found.add(char)
    return sorted(found)


def check_answer(spec, answer, allowed_ids):
    claims_text = " ".join(claim.text for claim in answer.claims)
    cited = set(answer.citations)
    facts = [any(re.search(p, claims_text) for p in group) for group in spec["facts"]]
    citation_groups = [bool(cited & set(group)) for group in spec["citations"]]
    simplified = simplified_chars(claims_text + (answer.reason or ""))
    checks = {
        "status": answer.status == spec["expected_status"],
        "facts": facts,
        "citation_groups": citation_groups,
        "citations_in_context": cited <= allowed_ids,
        "traditional": not simplified,
        "simplified_chars": simplified,
    }
    if spec["expected_status"] != "answered":
        checks["no_claims"] = not answer.claims
    checks["auto_pass"] = (
        checks["status"]
        and all(facts)
        and all(citation_groups)
        and checks["citations_in_context"]
        and checks["traditional"]
        and checks.get("no_claims", True)
    )
    return checks


def nearest_rank(values, q):
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * q) - 1]


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class MemoryWatch:
    """每0.2秒取樣本程序與模型子程序的RSS總和及系統可用記憶體。"""

    def __init__(self, psutil):
        self.psutil = psutil
        self.processes = {os.getpid(): psutil.Process()}
        self.lock = threading.Lock()
        self.reset()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def reset(self):
        with self.lock:
            self.peak_rss = 0
            self.min_available = self.psutil.virtual_memory().available

    def track(self, pid):
        with self.lock:
            self.processes[pid] = self.psutil.Process(pid)

    def untrack(self, pid):
        with self.lock:
            self.processes.pop(pid, None)

    def rss(self):
        values = {}
        with self.lock:
            for pid, process in list(self.processes.items()):
                try:
                    values[pid] = process.memory_info().rss
                except self.psutil.Error:
                    pass
        return values

    def _loop(self):
        while not self.stopped.wait(0.2):
            total = sum(self.rss().values())
            available = self.psutil.virtual_memory().available
            with self.lock:
                self.peak_rss = max(self.peak_rss, total)
                self.min_available = min(self.min_available, available)

    def peak(self):
        with self.lock:
            return {
                "peak_rss_bytes": self.peak_rss,
                "min_available_bytes": self.min_available,
            }

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)


def run(strategy, only):
    import httpx
    import numpy as np
    import psutil

    from hr_rag.contracts import Chunk, ContextBundle
    from hr_rag.local_models import LocalEncoder
    from hr_rag.providers import CheckedProviders, LlamaGenerator, ProviderError
    from hr_rag.settings import RuntimeSettings

    settings = RuntimeSettings()
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    units = {unit["id"]: unit for unit in evidence["units"]}
    children = [child for unit in evidence["units"] for child in unit["children"]]
    lock = json.loads((ROOT / "config/models.lock.json").read_text(encoding="utf-8"))
    model_path = ROOT / ".cache/models/generator" / lock["generator"]["filename"]
    runtime = ROOT / ".runtime/llama/llama-server.exe"
    port = urlsplit(settings.base_url).port
    questions = [q for q in QUESTIONS if not only or q["id"] in only]

    chunk_units = []
    for unit_id in BUNDLE:
        unit = units[unit_id]
        chunk_units.append(
            Chunk(
                id=unit_id,
                document_id=unit["document_id"],
                version_id=f"snapshot-{FETCHED_AT}",
                section_id=unit_id,
                parent_id=unit_id,
                text=unit["text"],
                allowed_roles=("employee", "manager", "hr"),
                # 0.7不核對法規施行日；問答依design採發布日期。
                effective_from=unit.get("published_at"),
            )
        )
    config_hash = hashlib.sha256(
        json.dumps(
            [u.model_dump(mode="json") for u in chunk_units], ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    context = ContextBundle(
        units=tuple(chunk_units),
        citation_map={u.id: (units[u.id]["source_url"],) for u in chunk_units},
        token_count=0,
        dropped_reasons=(),
        config_hash=config_hash,
    )
    allowed_ids = set(BUNDLE)

    watch = MemoryWatch(psutil)
    result = {
        "strategy": strategy,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "loads": {},
        "rows": [],
    }

    def load_encoder(role):
        started = time.perf_counter()
        worker = LocalEncoder(role, ROOT / ".cache/models" / role, settings)
        seconds = time.perf_counter() - started
        watch.track(worker.process.pid)
        return worker, seconds

    def close_encoder(worker):
        watch.untrack(worker.process.pid)
        worker.close()

    def start_server(log_name):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
        command = [
            str(runtime), "-m", str(model_path), "--host", "127.0.0.1",
            "--port", str(port), "-c", str(settings.context_limit),
            "-t", str(settings.threads), "-ngl", "0", "--parallel", "1",
            "--no-webui",
        ]  # fmt: skip
        started = time.perf_counter()
        log = (ROOT / "reports" / log_name).open("w", encoding="utf-8")
        process = subprocess.Popen(
            command, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW
        )
        watch.track(process.pid)
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + settings.timeout_seconds
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("本機生成服務啟動失敗")
                    try:
                        if client.get(settings.base_url + "/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError("本機生成服務啟動逾時")
                    time.sleep(0.25)
        except BaseException:
            stop_server(process, log)
            raise
        return process, log, time.perf_counter() - started

    def stop_server(process, log):
        watch.untrack(process.pid)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()

    def retrieve(embedder, reranker, question, index):
        started = time.perf_counter()
        vector = embedder.embed([question])[0]
        order = np.argsort(-(index @ vector), kind="stable")[:CANDIDATES]
        embed_seconds = time.perf_counter() - started
        candidates = [children[i] for i in order]
        started = time.perf_counter()
        scores = reranker.rerank(question, [c["text"] for c in candidates])
        rerank_seconds = time.perf_counter() - started
        ranked = sorted(zip(scores, (c["id"] for c in candidates)), reverse=True)
        return {
            "embed_query_seconds": round(embed_seconds, 4),
            "rerank_seconds": round(rerank_seconds, 4),
            "rerank_candidates": len(candidates),
            "rerank_top5": [cid for _, cid in ranked[:5]],
        }

    def generate(generator, spec):
        exchanges = []
        generator.on_exchange = exchanges.append
        provider = CheckedProviders(generation=generator)
        started = time.perf_counter()
        row = {"id": spec["id"], "type": spec["type"], "question": spec["question"]}
        try:
            answer = provider.generate(spec["question"], context)
            row["answer"] = answer.model_dump(mode="json")
            row["checks"] = check_answer(spec, answer, allowed_ids)
        except ProviderError as error:
            row["error"] = str(error)
            row["checks"] = {"auto_pass": False}
        row["generate_seconds"] = round(time.perf_counter() - started, 4)
        if exchanges:
            exchange = exchanges[-1]
            timings = exchange["response"].get("timings", {})
            row["tokens"] = {
                "input": exchange["input_tokens"],
                "evidence": exchange["evidence_tokens"],
                "prompt_n": timings.get("prompt_n"),
                "predicted_n": timings.get("predicted_n"),
            }
            row["llama_ms"] = {
                "prompt": timings.get("prompt_ms"),
                "predicted": timings.get("predicted_ms"),
                "prompt_per_second": timings.get("prompt_per_second"),
                "predicted_per_second": timings.get("predicted_per_second"),
            }
            row["raw_output"] = exchange["response"].get("content")
            row["output_sha256"] = hashlib.sha256(
                (row["raw_output"] or "").encode("utf-8")
            ).hexdigest()
            row["prompt"] = exchange["request"]["prompt"]
        return row

    def save():
        report = (
            json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            if REPORT_PATH.exists()
            else {}
        )
        report.update(
            {
                "scope": "階段0.7真實長度可行性實測；"
                "5題為可調整樣本，不是評估集或保留題",
                "hardware": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "cpu": platform.processor(),
                    "logical_cpus": os.cpu_count(),
                    "ram_bytes": psutil.virtual_memory().total,
                },
                "settings": settings.model_dump(),
                "bundle": BUNDLE,
                "bundle_config_hash": config_hash,
                "questions": QUESTIONS,
                "artifacts": {
                    "config/models.lock.json": sha256_file(
                        ROOT / "config/models.lock.json"
                    ),
                    "reports/feasibility-long-context-evidence.json": sha256_file(
                        EVIDENCE_PATH
                    ),
                    "scripts/feasibility_long_context.py": sha256_file(Path(__file__)),
                },
            }
        )
        report.setdefault("strategies", {})[strategy] = result
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    result["available_ram_bytes_at_start"] = psutil.virtual_memory().available
    generator = LlamaGenerator(settings)
    try:
        # 子片段向量屬於離線索引，不計入每題延遲。
        embedder, seconds = load_encoder("embedding")
        started = time.perf_counter()
        index = np.asarray(embedder.embed([c["text"] for c in children]))
        result["index"] = {
            "children": len(children),
            "load_seconds": round(seconds, 4),
            "embed_seconds": round(time.perf_counter() - started, 4),
        }
        if strategy == "resident":
            result["loads"]["embedding"] = {
                "seconds": round(seconds, 4),
                "rss_bytes": watch.rss().get(embedder.process.pid),
            }
            reranker, seconds = load_encoder("reranker")
            result["loads"]["reranker"] = {
                "seconds": round(seconds, 4),
                "rss_bytes": watch.rss().get(reranker.process.pid),
            }
            server, log, seconds = start_server("feasibility-llama-resident.log")
            result["loads"]["generator"] = {"seconds": round(seconds, 4)}
            try:
                watch.reset()
                for spec in questions:
                    started = time.perf_counter()
                    row = retrieve(embedder, reranker, spec["question"], index)
                    row.update(generate(generator, spec))
                    row["total_seconds"] = round(time.perf_counter() - started, 4)
                    result["rows"].append(row)
                    result["loads"]["generator"]["rss_bytes"] = watch.rss().get(
                        server.pid
                    )
                    save()
                    print(
                        spec["id"],
                        row["checks"]["auto_pass"],
                        row["total_seconds"],
                        flush=True,
                    )
                result["memory"] = watch.peak()
            finally:
                stop_server(server, log)
                close_encoder(reranker)
                close_encoder(embedder)
        else:
            close_encoder(embedder)
            watch.reset()
            for spec in questions:
                started = time.perf_counter()
                embedder, embed_load = load_encoder("embedding")
                reranker = None
                try:
                    # 依序模式：每個模型用完即釋放，再載入下一個。
                    vector_started = time.perf_counter()
                    vector = embedder.embed([spec["question"]])[0]
                    embed_seconds = time.perf_counter() - vector_started
                    close_encoder(embedder)
                    embedder = None
                    reranker, rerank_load = load_encoder("reranker")
                    order = np.argsort(-(index @ vector), kind="stable")[:CANDIDATES]
                    candidates = [children[i] for i in order]
                    rerank_started = time.perf_counter()
                    scores = reranker.rerank(
                        spec["question"], [c["text"] for c in candidates]
                    )
                    rerank_seconds = time.perf_counter() - rerank_started
                    close_encoder(reranker)
                    reranker = None
                finally:
                    if embedder:
                        close_encoder(embedder)
                    if reranker:
                        close_encoder(reranker)
                ranked = sorted(
                    zip(scores, (c["id"] for c in candidates)), reverse=True
                )
                server, log, gen_load = start_server("feasibility-llama-sequential.log")
                try:
                    row = {
                        "embed_query_seconds": round(embed_seconds, 4),
                        "rerank_seconds": round(rerank_seconds, 4),
                        "rerank_candidates": len(candidates),
                        "rerank_top5": [cid for _, cid in ranked[:5]],
                        "load_seconds": {
                            "embedding": round(embed_load, 4),
                            "reranker": round(rerank_load, 4),
                            "generator": round(gen_load, 4),
                        },
                    }
                    row.update(generate(generator, spec))
                finally:
                    stop_server(server, log)
                row["total_seconds"] = round(time.perf_counter() - started, 4)
                result["rows"].append(row)
                save()
                print(
                    spec["id"],
                    row["checks"]["auto_pass"],
                    row["total_seconds"],
                    flush=True,
                )
            result["memory"] = watch.peak()
    finally:
        generator.close()
        watch.close()

    totals = [row["total_seconds"] for row in result["rows"]]
    result["summary"] = {
        "auto_pass": sum(row["checks"]["auto_pass"] for row in result["rows"]),
        "count": len(result["rows"]),
        "all_traditional": all(
            row["checks"].get("traditional", False) for row in result["rows"]
        ),
        "p50_total_seconds": nearest_rank(totals, 0.5),
        "p95_total_seconds": nearest_rank(totals, 0.95),
        "max_total_seconds": max(totals),
        "all_below_timeout": max(totals) < settings.timeout_seconds,
    }
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("extract")
    runner = commands.add_parser("run")
    runner.add_argument("--strategy", choices=("resident", "sequential"), required=True)
    runner.add_argument("--only", nargs="*", default=None)
    runner.add_argument("--provider", choices=("local", "openai"), default="local")
    runner.add_argument("--model", action="append")
    args = parser.parse_args()
    if args.command == "extract":
        extract()
        return 0
    if args.provider == "openai":
        if args.strategy != "resident" or args.only is not None or not args.model:
            parser.error("OpenAI比較須指定--model，使用resident策略及完整F1–F5")
        from hr_rag.feasibility_openai import run as run_openai
        from hr_rag.providers import ProviderError

        try:
            return run_openai(args.model, SimpleNamespace(**globals()))
        except (ProviderError, ValueError) as error:
            # 只允許固定錯誤代碼，避免輸出憑證或傳輸例外。
            print(
                str(error)
                if isinstance(error, ProviderError)
                else "invalid_configuration"
            )
            return 1
    if args.model:
        parser.error("--model僅供OpenAI比較使用")
    return run(args.strategy, args.only)


if __name__ == "__main__":
    sys.exit(main())
