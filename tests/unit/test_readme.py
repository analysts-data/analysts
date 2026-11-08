"""README и .env.example: запуск, стоимость, Dynamics 365, «Посмотреть без ключа» (release-and-runbook)."""

import re
from pathlib import Path

from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def section(title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", README, re.S | re.M)
    assert match, f"в README нет раздела «{title}»"
    return match.group(1)


def test_readme_has_launch_steps_and_dataset_loading() -> None:
    for step in ("uv sync", "cp .env.example .env", "make run", "http://127.0.0.1:8000", "group_id"):
        assert step in README, step


def test_model_and_cost_names_dollars_and_calls() -> None:
    cost = section("Модель и стоимость")
    assert "$" in cost
    assert re.search(r"\d+ вызов", cost)


def test_dynamics_section_names_the_data_parameter() -> None:
    assert "`data`" in section("Встраивание в Dynamics 365")


def test_no_key_demo_is_the_first_section() -> None:
    # перед ним может идти короткий раздел «Преимущества» (решение команды 08.11); дальше — сразу демо без ключа
    heads = re.findall(r"^## (.+)$", README, re.M)
    assert "Посмотреть без ключа" in heads[:2]
    assert "make demo" in section("Посмотреть без ключа")
    assert re.search(r"^demo:", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)


def test_every_settings_variable_is_in_env_example() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    present = set(re.findall(r"^(CQA_[A-Z0-9_]+)=", example, re.M))
    for field in Settings.model_fields:
        name = f"CQA_{field.upper()}"
        assert name in present, f"{name} нет в .env.example"


def test_jury_lan_access_section_names_share_token_link_and_revoke() -> None:
    jury = section("Доступ для жюри по сети")
    for word in ("make share", "/login?token=", "CQA_ACCESS_TOKEN"):
        assert word in jury, word
    assert re.search(r"^share:", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)
