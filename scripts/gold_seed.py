"""Посев eval/gold/labels.jsonl из eval/gold/seed_team.txt — разметки команды как есть.

Строка посева: `<dlg> <8 токенов> [team|family]`. Токены по критериям чек-листа по порядку:
`y` → "yes", `n` → "no", `a` → "na", число → ступень, `5|10` — несколько допустимых,
`?` → спорно (`ok: null`), `-` — не размечено, строки нет. Для критерия типа `flag`:
`n` — все подвопросы false, `y:<k>[,<k>]` — названные true, ключи из чек-листа.
Запуск: uv run python scripts/gold_seed.py [--seed PATH] [--checklist PATH] > eval/gold/labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "eval" / "gold" / "seed_team.txt"
DEFAULT_CHECKLIST = ROOT / "tests" / "fixtures" / "checklist_v3.json"

BY_TOKENS = ("team", "family")
SKIP = "-"
UNSURE = "?"
BY_DEFAULT = "team"


def seed_rows(seed_text: str, criteria: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for line in seed_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.extend(seed_line(line, criteria))
    return rows


def seed_line(line: str, criteria: list[dict]) -> list[dict]:
    parts = line.split()
    dlg, tokens = parts[0], parts[1:]
    by = BY_DEFAULT
    if tokens and tokens[-1] in BY_TOKENS:
        by = tokens.pop()
    if len(tokens) != len(criteria):
        raise ValueError(f"{dlg}: {len(tokens)} токенов, а критериев {len(criteria)}")

    rows: list[dict] = []
    for criterion, token in zip(criteria, tokens, strict=True):
        if token == SKIP:
            continue
        ok = None if token == UNSURE else _answers(token, criterion, dlg)
        rows.append({"dlg": dlg, "cid": criterion["id"], "ok": ok, "by": by, "note": ""})
    return rows


def _answers(token: str, criterion: dict, dlg: str) -> list:
    if criterion["type"] == "flag":
        return [_flag(token, criterion, dlg)]
    answers = [_single(part, criterion, dlg) for part in token.split("|")]
    return answers


def _single(part: str, criterion: dict, dlg: str) -> str | int:
    if part == "y":
        return "yes"
    if part == "n":
        return "no"
    if part == "a":
        return "na"
    if part.isdigit():
        return int(part)
    raise ValueError(f"{dlg}, критерий {criterion['id']}: неизвестный токен {part}")


def _flag(token: str, criterion: dict, dlg: str) -> dict[str, bool]:
    keys = [q["k"] for q in criterion["questions"]]
    if token == "n":
        return {k: False for k in keys}
    if token.startswith("y:"):
        named = token[2:].split(",")
        unknown = [k for k in named if k not in keys]
        if unknown:
            raise ValueError(f"{dlg}, критерий {criterion['id']}: неизвестный подвопрос {unknown[0]}")
        return {k: k in named for k in keys}
    raise ValueError(f"{dlg}, критерий {criterion['id']}: для флага укажите подвопрос, y:<k>")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    args = parser.parse_args(argv)

    checklist = json.loads(args.checklist.read_text(encoding="utf-8"))
    rows = seed_rows(args.seed.read_text(encoding="utf-8"), checklist["criteria"])
    out = sys.stdout
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
