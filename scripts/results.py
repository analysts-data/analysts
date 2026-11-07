#!/usr/bin/env python3
"""Файлы результатов для организаторов (формат JSON 1.0): results/<набор>/results.json.

    make results SET=dev                    # DEV: id из снимка CQA_EVAL_DATASET (data/dev.json)
    make results SET=prod GROUP=<group_id>  # контроль: id из снимка <CQA_RAW_DIR>/<group_id>.json
    scripts/results.py prod --source FILE   # любой конверт организаторов, например загруженный файлом

Набор — ровно conversation_id записей конверта организаторов, в его порядке: снимок
<CQA_RAW_DIR>/<group_id>.json сервер пишет сам при «Получить набор». Ответы и решения
берутся из базы CQA_DB_PATH так же, как GET /api/state, итог — с учётом последнего решения.
Диалог, которого нет в базе или у которого нет оценки по всем критериям карты
results/criteria_map.json, остаётся в файле со status "error" и причиной.

Проверка: нет повторов conversation_id, у ok каждый код карты ровно один раз, в prod ровно
10 записей. Файл пишется всегда; при провале проверки код выхода 1 и список проблем в stderr.
"""

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from cqa.adapters.jev import _JEV_MODEL
from cqa.adapters.store import Store, connect
from cqa.domain.ingest import PayloadError, parse_payload
from cqa.domain.models import Dialog
from cqa.domain.results import check_results, to_results
from cqa.services.state import current_state
from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
CODES = ROOT / "results" / "criteria_map.json"
PROD_RECORDS = 10  # «В prod — ровно 10 записей, включая ошибки»
TEAM = "analysts"


def model_names(dialogs: Iterable[Dialog]) -> str:
    """Модели из поля model ответов в порядке появления; второе мнение, если есть alt."""
    rs = [r for d in dialogs for r in d.res.values()]
    names = list(dict.fromkeys(r.model for r in rs if r.model))
    if any(r.alt is not None for r in rs):
        names.append(_JEV_MODEL)
    return ", ".join(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("set", choices=["dev", "prod"])
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="group_id: снимок <CQA_RAW_DIR>/<group_id>.json; можно несколько",
    )
    parser.add_argument("--source", action="append", default=[], type=Path, help="конверт организаторов JSON")
    parser.add_argument("--team", default=TEAM, help=f"team_name (по умолчанию {TEAM})")
    parser.add_argument("--mode", choices=["external_api", "local", "hybrid"], help="model.mode")
    parser.add_argument("--model-name", help="model.name; по умолчанию модели из ответов в базе")
    parser.add_argument("--out", type=Path, help="по умолчанию results/<set>/results.json")
    args = parser.parse_args(argv)

    settings = Settings()
    sources = [*args.source, *(settings.raw_dir / f"{g}.json" for g in args.group)]
    if not sources:
        if args.set == "prod":
            parser.error("для prod укажите GROUP=<group_id> (make) или --group/--source")
        sources = [settings.eval_dataset]
    if not Path(settings.db_path).is_file():
        print(f"нет базы {settings.db_path} (CQA_DB_PATH)", file=sys.stderr)
        return 2
    ids: list[str] = []
    for source in sources:
        try:
            ids += [str(r["conversation_id"]) for r in parse_payload(source.read_bytes()).records]
        except (OSError, PayloadError, KeyError, TypeError) as e:
            print(f"снимок набора {source}: {e!r}", file=sys.stderr)
            return 2
    ids = list(dict.fromkeys(ids))  # повтор id в источнике — одна запись, как при загрузке

    conn = connect(settings.db_path)
    try:
        checklist, listed, appeals = current_state(Store(conn))
    finally:
        conn.close()
    dialogs = {d.id: d for d in listed}
    codes: dict[str, str] = json.loads(CODES.read_text(encoding="utf-8"))
    model = {
        "mode": args.mode or ("local" if settings.data_where == "local" else "external_api"),
        "name": args.model_name or model_names(dialogs[i] for i in ids if i in dialogs),
    }
    doc = to_results(ids, dialogs, checklist, appeals, codes, team=args.team, model=model)

    out = args.out or ROOT / "results" / args.set / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors = [r for r in doc["results"] if r["status"] == "error"]
    print(
        f"{out}: записей {len(doc['results'])}, ok {len(doc['results']) - len(errors)}, error {len(errors)}"
    )
    print(f"team_name {doc['team_name']!r}, model {model}")
    for r in errors:
        print(f"  error {r['conversation_id']}: {r['error']}")
    problems = check_results(doc, codes.values(), PROD_RECORDS if args.set == "prod" else None)
    if not model["name"]:
        problems.append("model.name пуст: укажите --model-name")
    for p in problems:
        print(f"FAIL {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
