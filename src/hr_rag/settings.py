"""本機模型與上下文預算，不保存任何 API 金鑰。"""

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from hr_rag.contracts import CalendarDate, Contract

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini-2025-04-14"
GENERATION_ENV_NAMES = ("OPENAI_API_KEY", "HR_RAG_COST_LIMIT_USD")


def load_generation_environment() -> dict[str, str]:
    """專案根目錄.env補足缺少的設定；不修改環境、不記錄或快取憑證。"""
    values = {
        name: os.environ[name] for name in GENERATION_ENV_NAMES if name in os.environ
    }
    missing = set(GENERATION_ENV_NAMES) - values.keys()
    if not missing:
        return values
    try:
        text = PROJECT_ENV_PATH.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return values
    except (OSError, UnicodeError):
        raise ValueError("invalid_environment_file") from None
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, value = line.partition("=")
            name = name.strip()
            if name not in missing:
                continue
            if not separator:
                raise ValueError
            value = value.strip()
            if value.startswith(("'", '"')):
                match = re.fullmatch(r"""(['"])(.*?)\1\s*(?:#.*)?""", value)
                if match is None:
                    raise ValueError
                value = match.group(2)
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            values[name] = value
    except ValueError:
        raise ValueError("invalid_environment_file") from None
    return values


class RuntimeSettings(Contract):
    context_limit: int = Field(default=4096, gt=0, strict=True)
    evidence_budget: int = Field(default=2048, gt=0, strict=True)
    output_reserve: int = Field(default=512, gt=0, strict=True)
    safety_margin: int = Field(default=128, ge=0, strict=True)
    timeout_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    p95_alert_seconds: float = Field(default=180, gt=0, allow_inf_nan=False)
    base_url: str = "http://127.0.0.1:8765"
    threads: int = Field(default=2, gt=0, strict=True)

    @field_validator("base_url")
    @classmethod
    def local_only(cls, value):
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
            or url.port is None
        ):
            raise ValueError("階段0只允許明確port的127.0.0.1本機推論端點")
        return value.rstrip("/")

    @model_validator(mode="after")
    def usable_budget(self):
        if (
            self.evidence_budget + self.output_reserve + self.safety_margin
            >= self.context_limit
        ):
            raise ValueError("上下文預算沒有保留提示與問題空間")
        return self

    def check_request_tokens(self, input_tokens: int, *, evidence_tokens: int):
        if input_tokens < 0 or evidence_tokens < 0:
            raise ValueError("token數不可為負")
        if evidence_tokens > self.evidence_budget:
            raise ValueError("證據超過預算")
        if input_tokens + self.output_reserve + self.safety_margin > self.context_limit:
            raise ValueError("完整輸入加輸出保留額度超過模型上限")


class OpenAISettings(RuntimeSettings):
    """0.9依真實長度實測凍結；金鑰與累計上限仍由使用者提供。"""

    provider: Literal["openai"] = "openai"
    base_url: str = "https://api.openai.com/v1"
    model: str | None = Field(
        default=DEFAULT_OPENAI_MODEL, min_length=1, pattern=r"^[a-zA-Z0-9._-]+$"
    )
    input_usd_per_million: Decimal | None = Field(default=Decimal("0.40"), gt=0)
    output_usd_per_million: Decimal | None = Field(default=Decimal("1.60"), gt=0)
    pricing_checked_on: CalendarDate | None = date(2026, 10, 18)
    cost_ledger_path: Path = PROJECT_ROOT / ".runtime/openai-cost.sqlite3"
    encoder_strategy: Literal["resident"] = "resident"
    timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    p95_alert_seconds: float = Field(default=45, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=2, ge=0, le=2, strict=True)
    supports_temperature: bool = True
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None

    @model_validator(mode="before")
    @classmethod
    def changed_model_requires_prices(cls, values):
        if isinstance(values, dict) and values.get(
            "model", DEFAULT_OPENAI_MODEL
        ) not in (
            None,
            DEFAULT_OPENAI_MODEL,
        ):
            required = {
                "input_usd_per_million",
                "output_usd_per_million",
                "pricing_checked_on",
            }
            if not required.issubset(values):
                raise ValueError("更換模型須明確提供已查證價格及日期，不可沿用mini單價")
        return values

    @field_validator("base_url")
    @classmethod
    def local_only(cls, value):
        # 覆蓋本機設定的同名驗證器；禁止redirect、query與認證資訊。
        if value != "https://api.openai.com/v1":
            raise ValueError("只允許官方OpenAI端點")
        return value

    @model_validator(mode="after")
    def reasoning_configuration(self):
        if self.p95_alert_seconds >= self.timeout_seconds:
            raise ValueError("P95告警門檻須低於單次逾時")
        if not self.supports_temperature and self.reasoning_effort is None:
            raise ValueError("不支援temperature的模型須明確設定推理強度")
        return self
