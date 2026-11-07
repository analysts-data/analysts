#!/usr/bin/env python3
"""Файлы результатов для организаторов (формат JSON 1.0): results/<набор>/results.json.

    make results SET=dev                    # DEV: id из снимка CQA_EVAL_DATASET (data/dev.json)
    make results SET=prod GROUP=<group_id>  # контроль: id из снимка <CQA_RAW_DIR>/<group_id>.json
    scripts/results.py prod --source FILE   # любой конверт организаторов, например загруженный файлом
    make results SET=prod GROUP=<group_id> ARGS=--evaluate   # набор, оценка и файл одной командой

Набор — ровно conversation_id записей конверта организаторов, в его порядке: снимок
<CQA_RAW_DIR>/<group_id>.json сервер пишет сам при «Получить набор». Ответы и решения
берутся из базы CQA_DB_PATH так же, как GET /api/state, итог — с учётом последнего решения.
Диалог, которого нет в базе или у которого нет оценки по всем критериям карты
results/criteria_map.json, остаётся в файле со status "error" и причиной.

С --evaluate сначала набор загружается в базу, как в интерфейсе: GROUP — «Получить набор» (тот же
источник и снимок), --source и DEV-файл — «Загрузить JSON». Затем модель из .env и режима интерфейса
оценивает пары набора без ответа текущего чек-листа, по CQA_LLM_MAX_PARALLEL сразу, ход — каждые
5 секунд. Реальный звонок уходит модели только с CQA_ALLOW_REAL_DATA=1. Сервер можно не
останавливать (SQLite в WAL), но не нажимайте «Оценить» в интерфейсе одновременно.

Проверка: нет повторов conversation_id, у ok каждый код карты ровно один раз, в prod ровно
10 записей. Файл пишется всегда; при провале проверки код выхода 1 и список проблем в stderr.
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

from cqa.adapters.jev import _JEV_MODEL
from cqa.adapters.store import Store, connect
from cqa.compose import build_evaluator, build_source
from cqa.domain.ingest import PayloadError, parse_payload
from cqa.domain.models import Dialog
from cqa.domain.results import check_results, to_results
from cqa.services.answers import MANUAL
from cqa.services.datasets import load_group, load_upload
from cqa.services.errors import Invalid, Upstream
from cqa.services.llm_config import effective
from cqa.services.ports import DialogSource, Evaluator
from cqa.services.runs import Runner, plan_run
from cqa.services.state import current_state
from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
CODES = ROOT / "results" / "criteria_map.json"
PROD_RECORDS = 10  # «В prod — ровно 10 записей, включая ошибки»
TEAM = "analysts"
PROGRESS_S = 5.0


def model_names(dialogs: Iterable[Dialog]) -> str:
    """Модели из поля model ответов в порядке появления; второе мнение, если есть alt. Ручной ответ — не модель."""
    rs = [r for d in dialogs for r in d.res.values()]
    names = list(dict.fromkeys(r.model for r in rs if r.model and r.model != MANUAL))
    if any(r.alt is not None for r in rs):
        names.append(_JEV_MODEL)
    return ", ".join(names)


async def load_set(store: Store, source: DialogSource, groups: list[str], files: list[Path]) -> None:
    """Как «Получить набор» (снимок <CQA_RAW_DIR>/<group_id>.json) и «Загрузить JSON»."""
    for g in groups:
        print(f"набор {g}: {await load_group(store, source, g)}", flush=True)
    for f in files:
        print(f"набор {f}: {load_upload(store, source, f.read_bytes())}", flush=True)


def progress_line(p: dict[str, Any]) -> str:
    return f"оценка {p['done']}/{p['total']}, ошибок {len(p['errors'])}, ${p['cost']:.4f}"


async def evaluate(store: Store, evaluator: Evaluator, ids: list[str], parallel: int) -> None:
    """Пары `ids` без ответа текущего чек-листа, как «Оценить» с этими диалогами; ход — каждые PROGRESS_S."""
    checklist = store.current_checklist()
    assert checklist is not None, "чек-лист сеет сервер при первом запуске"
    plan = plan_run(store, checklist, ids, None)
    run_id = store.add_run(sum(len(cs) for _, cs in plan), time.time())
    runner = Runner(store, evaluator, parallel=parallel)

    async def report() -> None:
        while True:
            await asyncio.sleep(PROGRESS_S)
            print(progress_line(runner.progress(run_id)), flush=True)

    reporter = asyncio.create_task(report())
    try:
        await runner.execute(run_id, checklist, plan)
    finally:
        reporter.cancel()
    p = runner.progress(run_id)
    print(progress_line(p), flush=True)
    for e in p["errors"]:
        print(f"  {e}")


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
    parser.add_argument(
        "--evaluate", action="store_true", help="сначала загрузить набор в базу и оценить, чего нет"
    )
    args = parser.parse_args(argv)

    settings = Settings()
    files = args.source
    if not files and not args.group:
        if args.set == "prod":
            parser.error("для prod укажите GROUP=<group_id> (make) или --group/--source")
        files = [settings.eval_dataset]
    sources = [*files, *(settings.raw_dir / f"{g}.json" for g in args.group)]
    if not Path(settings.db_path).is_file():
        print(f"нет базы {settings.db_path} (CQA_DB_PATH)", file=sys.stderr)
        return 2
    with closing(connect(settings.db_path)) as conn:
        store = Store(conn)
        settings = effective(settings, store.overrides())  # режим из интерфейса поверх .env, как у сервера
        return export(args, store, settings, sources, files)


def export(
    args: argparse.Namespace, store: Store, settings: Settings, sources: list[Path], files: list[Path]
) -> int:
    if args.evaluate:
        try:
            asyncio.run(load_set(store, build_source(settings), args.group, files))
        except (Invalid, Upstream, OSError) as e:
            print(f"загрузка набора: {e}", file=sys.stderr)
            return 2
    ids: list[str] = []
    for source in sources:
        try:
            ids += [str(r["conversation_id"]) for r in parse_payload(source.read_bytes()).records]
        except (OSError, PayloadError, KeyError, TypeError) as e:
            print(f"снимок набора {source}: {e!r}", file=sys.stderr)
            return 2
    ids = list(dict.fromkeys(ids))  # повтор id в источнике — одна запись, как при загрузке
    if args.evaluate:
        asyncio.run(evaluate(store, build_evaluator(settings), ids, settings.llm_max_parallel))

    checklist, listed, appeals = current_state(store)
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
