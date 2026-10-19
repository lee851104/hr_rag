"""正式生成器：只採用models.lock.json指向且經人工驗收的設定。"""

import hashlib
import json
from pathlib import Path

from hr_rag.settings import PROJECT_ROOT, OpenAISettings
from hr_rag.verbatim import SourceSelection, VerbatimGenerator

LOCK_PATH = PROJECT_ROOT / "config/models.lock.json"
SELECTED_MODE = "verbatim-reference-closure-v3"


def load_selected_generation(*, config_path: Path | None = None):
    """設定、提示、schema或實作與驗收時不同即拒絕，不退回摘要生成器。"""
    selected = json.loads(LOCK_PATH.read_text("utf-8"))["selected_generation"]
    path = config_path or PROJECT_ROOT / selected["config"]
    raw = path.read_bytes()
    config = json.loads(raw)
    implementation = hashlib.sha256(
        (PROJECT_ROOT / "src/hr_rag/verbatim.py").read_bytes()
    ).hexdigest()
    if (
        hashlib.sha256(raw).hexdigest() != selected["sha256"]
        or config.get("status") != "selected"
        or config.get("mode") != SELECTED_MODE
        or config.get("system") != VerbatimGenerator.SYSTEM
        or config.get("schema") != SourceSelection.model_json_schema()
        or config.get("implementation_sha256") != implementation
    ):
        raise ValueError("generation_selection_changed")
    return config, OpenAISettings(**config["settings"])


def selected_generator(**kwargs) -> VerbatimGenerator:
    _, settings = load_selected_generation()
    return VerbatimGenerator(settings, **kwargs)
