"""下載固定revision的公開模型；不讀取登入token，不執行模型遠端程式碼。"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import snapshot_download  # noqa: E402

lock = json.loads((ROOT / "config/models.lock.json").read_text(encoding="utf-8"))
for role in ("embedding", "reranker", "generator"):
    entry = lock[role]
    patterns = (
        [entry["filename"]]
        if role == "generator"
        else ["*.json", "*.txt", "*.safetensors", "*.model", "1_Pooling/*"]
    )
    print(f"下載 {role}: {entry['repository']}@{entry['revision']}", flush=True)
    snapshot_download(
        repo_id=entry["repository"],
        revision=entry["revision"],
        local_dir=ROOT / ".cache/models" / role,
        cache_dir=ROOT / ".cache/huggingface",
        allow_patterns=patterns,
        token=False,
        max_workers=2,
    )
    print(f"完成 {role}", flush=True)
