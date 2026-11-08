"""All configuration: CQA_* environment variables and .env (table "Settings" in design/ports.md)."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Where = Literal["kz", "local", "external"]


class Provider(BaseModel):
    """OpenAI-compatible model with its own key (PUT /api/providers/{id}); `env` is built from llm_*."""

    label: str
    base_url: str | None
    model: str
    profile: str
    where: Where
    key: SecretStr | None = None


class Settings(BaseSettings):
    # empty values (as in .env.example) fall back to defaults; CQA_NOW and other keys are ignored
    model_config = SettingsConfigDict(
        env_prefix="CQA_", env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    llm_mode: Literal["replay", "record", "live"] = "replay"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "qwen3-6"
    llm_profile: str = "plain"
    llm_reasoning: Literal["on", "off"] = "on"
    llm_max_parallel: int = 4
    llm_rpm: int = 120  # 0: no limit
    llm_timeout_s: float = 180
    llm_price_in: float = 0.0  # USD per 1M tokens
    llm_price_out: float = 0.0
    llm_provider: str = "env"  # main model: id in providers
    providers: dict[str, Provider] = {}  # JSON {id: Provider}; effective adds "env", "openrouter-jev"
    openrouter_api_key: SecretStr | None = None  # key of the built-in "openrouter-jev" provider
    verifier: str | None = None  # "jev" or id in providers
    evaluator: Literal["llm", "jev"] = "llm"  # jev: all criteria by Jev alone, no rationale
    routing: list[dict[str, Any]] | None = None  # JSON rules (GET /api/routing); None — demo rules, off
    jev_api_key: SecretStr | None = None
    anonymize: bool = True
    data_where: Where = "kz"
    allow_real_data: bool = False  # set only by a human
    org_api_url: SecretStr | None = None
    raw_dir: Path = Path("data/raw")
    audio_shift_s: float = 0.25
    audio_shift_paused_s: float = 4.5
    db_path: str = "data/cqa.db"
    eval_dataset: Path = Path("data/dev.json")
    holdout_dir: Path | None = None
    webhook_url: str | None = None  # события alert.created; пусто — не отправляются
    webhook_secret: SecretStr | None = None  # ключ подписи X-CQA-Signature
    telemetry: Literal["on", "off"] = "on"  # метрики использования (README «Метрики использования»)
    telemetry_retention_days: int = 30
    eval_reports_dir: Path = Path("eval/reports")  # отчёты make eval для GET /api/quality
    results_dir: Path = Path("results")  # файлы организаторов <set>/results.json
    access_token: SecretStr | None = None  # show over the LAN: cookie from /login?token=, empty — open
