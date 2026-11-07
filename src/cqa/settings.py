"""All configuration: CQA_* environment variables and .env (table "Settings" in design/ports.md)."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    verifier: Literal["jev"] | None = None
    jev_api_key: SecretStr | None = None
    anonymize: bool = True
    data_where: Literal["kz", "local", "external"] = "kz"
    allow_real_data: bool = False  # set only by a human
    org_api_url: SecretStr | None = None
    raw_dir: Path = Path("data/raw")
    audio_shift_s: float = 0.25
    audio_shift_paused_s: float = 4.5
    db_path: str = "data/cqa.db"
    eval_dataset: Path = Path("data/dev.json")
    holdout_dir: Path | None = None
