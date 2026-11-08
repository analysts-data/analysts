#!/usr/bin/env python3
"""Защита (eval-and-delivery, решение 16): подбор диалогов, проверка за 15 минут, показ без ключа.

    scripts/demo.py pick  [--base URL]                > pick.json
    scripts/demo.py check [--base URL] --pick pick.json [--run ID ...] [--call ID] [--draft FILE]
    scripts/demo.py serve                             # make demo: replay, data/demo.db, набор защиты
    scripts/demo.py showcase [--port N]               # make showcase: replay, data/showcase.db, + витрина

pick берёт только поля GET /api/state и снимок DEV (CQA_EVAL_DATASET), итог не считает: он только в scoring.js.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from cqa.adapters.store import Store, connect
from cqa.domain.ingest import ingest_records
from cqa.domain.models import Criterion
from cqa.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "tests" / "cassettes" / "llm"
DEMO_SET = ROOT / "tests" / "e2e" / "fixtures" / "defence_set.json"
DEMO_EMPLOYEES = ROOT / "tests" / "e2e" / "fixtures" / "employees.csv"  # вымышленные сотрудники
SHOWCASE_SET = ROOT / "tests" / "fixtures" / "showcase_set.json"  # 40 синтетических диалогов, 5 операторов
BASE = "http://127.0.0.1:8000"

# Таблица «Защита»: диалог DEV на случай, если в контрольном наборе нет подходящего.
FALLBACK = {
    "gross": ("p1-ru-022", "В контрольном наборе нет грубой ошибки с основанием, показываем диалог из DEV"),
    "na": ("p1-ru-025", "В контрольном наборе нет N/A с условием, показываем диалог из DEV"),
    "appeal": (
        "p1-ru-003",
        "В контрольном наборе нет сниженной шкалы с основанием, показываем диалог из DEV",
    ),
    "call": ("p4-ru-002", "В контрольном наборе звонков нет, показываем звонок из DEV"),
    "slide10": (
        "p1-ru-010",
        "В контрольном наборе нет передачи специалистам без срока, показываем диалог из DEV",
    ),
}
MANUAL = [
    "роль переключается: Специалист КК → Оператор → Проверяющий",
    "плашка режима данных в шапке: место обработки, обезличивание, модель",
    "черновик заменяющего критерия открыт во второй вкладке",
]

Dialog = dict[str, Any]
Checklist = dict[str, Any]
Rule = Callable[[Dialog, Checklist, list[dict[str, Any]]], str | None]


def _lines(d: Dialog) -> list[dict[str, Any]]:
    return [x for x in d.get("lines") or [] if "n" in x]


def _gross(d: Dialog, cl: Checklist, ap: list[dict[str, Any]]) -> str | None:
    for c in cl["criteria"]:
        r = d["res"].get(c["id"])
        if c["type"] == "flag" and r and r.get("ev") and any((r.get("a") or {}).values()):
            return str(c["id"])
    return None


def _na(d: Dialog, cl: Checklist, ap: list[dict[str, Any]]) -> str | None:
    res = d["res"]
    scored = [c for c in cl["criteria"] if c["type"] != "flag"]
    if not any(c["w"] > 0 and c["id"] in res and res[c["id"]]["a"] != "na" for c in scored):
        return None
    return next((c["id"] for c in scored if c.get("naCond") and res.get(c["id"], {}).get("a") == "na"), None)


def _appeal(d: Dialog, cl: Checklist, ap: list[dict[str, Any]]) -> str | None:
    taken = {(a["dlg"], a["cid"]) for a in ap if a.get("kind") == "appeal"}
    for c in cl["criteria"]:
        r = d["res"].get(c["id"])
        if c["type"] != "scale" or not r or not r.get("ev") or (d["id"], c["id"]) in taken:
            continue
        if isinstance(r["a"], int) and r["a"] < max(c["steps"]):
            return str(c["id"])
    return None


def _call(d: Dialog, cl: Checklist, ap: list[dict[str, Any]]) -> str | None:
    if d.get("ch") != "call":
        return None
    start = {x["n"]: x.get("s") for x in _lines(d)}
    with_ev = [(cid, r["ev"]) for cid, r in d["res"].items() if r.get("ev")]
    if with_ev and all(start.get(n) is not None for _, ev in with_ev for n in ev):
        return str(with_ev[0][0])
    return None


HANDOFF = re.compile(r"переда|специалист", re.IGNORECASE)
DEADLINE = re.compile(r"срок", re.IGNORECASE)


def _slide10(d: Dialog, cl: Checklist, ap: list[dict[str, Any]]) -> str | None:
    """Пример слайда 10: чат, оператор передаёт вопрос специалистам, решение запроса снижено за срок."""
    if d.get("ch") == "call" or not any(
        x.get("who") == "operator" and HANDOFF.search(x.get("text") or "") for x in _lines(d)
    ):
        return None
    for c in cl["criteria"]:
        r = d["res"].get(c["id"])
        if c.get("signal") != "resolution" or not r or not DEADLINE.search(f"{r.get('why')} {r.get('tag')}"):
            continue
        a = r["a"]
        if a == "no" or (isinstance(a, int) and c["type"] == "scale" and a < max(c["steps"])):
            return str(c["id"])
    return None


RULES: dict[str, Rule] = {"gross": _gross, "na": _na, "appeal": _appeal, "call": _call, "slide10": _slide10}


def pick(state: dict[str, Any], dev_ids: set[str]) -> dict[str, dict[str, Any]]:
    """По диалогу на шаг: контрольный с меньшим числом реплик, иначе диалог DEV с фразой."""
    out: dict[str, dict[str, Any]] = {}
    for step, rule in RULES.items():
        hits = [
            (len(_lines(d)), d["id"], cid)
            for d in state["dialogs"]
            if d["id"] not in dev_ids and (cid := rule(d, state["checklist"], state["appeals"]))
        ]
        if hits:
            _, id_, cid = min(hits, key=lambda h: h[0])
            out[step] = {"id": id_, "cid": cid, "fallback": False}
        else:
            id_, say = FALLBACK[step]
            out[step] = {"id": id_, "fallback": True, "say": say}
    return out


def dev_snapshot(path: Path) -> set[str]:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"нет снимка DEV {path}: все диалоги считаются контрольными", file=sys.stderr)
        return set()
    return {str(r["conversation_id"]) for r in envelope["data"]["records"]}


def _audio(api: httpx.Client, call: str) -> tuple[bool, str]:
    """302 на запись и 200/206 по ссылке; подписанную ссылку не печатаем."""
    fail = (False, f"запись {call} недоступна")
    r = api.get(f"/api/dialogs/{call}/audio", follow_redirects=False)
    if r.status_code != 302:
        return fail
    try:
        with httpx.stream("GET", r.headers["location"], headers={"Range": "bytes=0-0"}, timeout=15) as rec:
            code = rec.status_code
    except httpx.HTTPError:
        return fail
    return (True, f"запись {call}: 302, затем {code}") if code in (200, 206) else fail


def check(
    api: httpx.Client,
    picked: dict[str, dict[str, Any]],
    runs: list[str],
    call: str | None,
    model: str,
    where: str,
    draft: Path | None,
) -> list[tuple[bool, str]]:
    state = api.get("/api/state").raise_for_status().json()
    cids = [c["id"] for c in state["checklist"]["criteria"]]
    dialogs = {d["id"]: d for d in state["dialogs"]}
    items: list[tuple[bool, str]] = []
    for step, p in picked.items():
        d = dialogs.get(p["id"])
        if d is None:
            items.append((False, f"{step}: диалога {p['id']} нет в наборе"))
            continue
        missing = [c for c in cids if c not in d["res"]]
        text = f"{step}: {p['id']} ждёт оценки по критериям {', '.join(missing)}" if missing else ""
        items.append((not missing, text or f"{step}: {p['id']} оценён по всем критериям"))
    for rid in runs:
        r = api.get(f"/api/runs/{rid}").raise_for_status().json()
        ok = r["status"] == "done" and r["done"] == r["total"] and not r["errors"]
        items.append(
            (ok, f"запуск {rid}: {r['done']}/{r['total']}, ошибок {len(r['errors'])}, {r['status']}")
        )
    if call:
        items.append(_audio(api, call))
    mode = state["mode"]
    ok = mode["model"] == model and mode["where"] == where
    items.append((ok, f"режим: модель {mode['model']}, обработка {mode['where']} (ждём {model}, {where})"))
    if draft:
        try:
            Criterion.model_validate_json(draft.read_text(encoding="utf-8"))
            items.append((True, f"черновик {draft.name} — корректный критерий"))
        except (OSError, ValidationError) as e:
            items.append((False, f"черновик {draft.name} не проходит Criterion: {e}"))
    return items


def missing_cassettes(path: Path = CASSETTES) -> str | None:
    if any(path.glob("*.json")):
        return None
    return f"Нет записанных ответов модели в {path}: запустите make record с ключом модели в .env, затем make demo."


def serve(port: int = 8000) -> int:
    """make demo: сервер на записанных ответах, своя база, набор защиты загружен и оценён."""
    if message := missing_cassettes():
        print(message, file=sys.stderr)
        return 1
    (ROOT / "data").mkdir(exist_ok=True)
    env = {**os.environ, "CQA_LLM_MODE": "replay", "CQA_DB_PATH": str(ROOT / "data" / "demo.db")}
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "cqa.http.app:create_app",
        "--factory",
        "--app-dir",
        str(ROOT / "src"),
    ]
    proc = subprocess.Popen([*cmd, "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=30) as api:
            _wait_health(api, proc)
            raw = DEMO_SET.read_bytes()
            added = api.post(
                "/api/datasets/upload", content=raw, headers={"Content-Type": "application/json"}
            )
            print(f"набор защиты: {added.raise_for_status().json()}")
            staff = api.post("/api/employees/import", content=DEMO_EMPLOYEES.read_bytes())
            print(f"сотрудники: {staff.raise_for_status().json()}")
            run_id = (
                api.post("/api/runs", json={"dialogs": None, "criteria": None})
                .raise_for_status()
                .json()["run_id"]
            )
            while (run := api.get(f"/api/runs/{run_id}").raise_for_status().json())["status"] == "running":
                time.sleep(0.5)
            if run["errors"]:
                print(f"ошибок оценки {len(run['errors'])}, первая: {run['errors'][0]}", file=sys.stderr)
                print("не хватает записанных ответов модели: make record", file=sys.stderr)
        print(f"Готово: {base}/#/queue  (Ctrl+C — остановить)")
        return proc.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        proc.wait(10)


def preload_showcase(db: Path) -> list[str]:
    """Витрина в базу до старта сервера; у чата `at` — время загрузки, поэтому `now` — `started_at` записи."""
    settings = Settings()
    records = json.loads(SHOWCASE_SET.read_text(encoding="utf-8"))["data"]["records"]
    conn = connect(str(db))
    try:
        store = Store(conn)
        for r in records:
            result, _ = ingest_records(
                [r],
                group_id="SHOWCASE",
                now=datetime.fromisoformat(r["started_at"]),
                shift_s=settings.audio_shift_s,
                shift_paused_s=settings.audio_shift_paused_s,
            )
            store.add_dialogs(result.dialogs, result.audio)
    finally:
        conn.close()
    return sorted({r["operator"] for r in records})


def showcase(port: int = 8000) -> int:
    """make showcase: свежая data/showcase.db, набор защиты и витрина за 5 дней, оценка в replay."""
    if message := missing_cassettes():
        print(message, file=sys.stderr)
        return 1
    db = ROOT / "data" / "showcase.db"
    for p in (db, db.with_name("showcase.db-wal"), db.with_name("showcase.db-shm")):
        p.unlink(missing_ok=True)
    operators = preload_showcase(db)
    # replay не ходит в сеть: лимит запросов в минуту только растянул бы оценку 480 вызовов
    env = {**os.environ, "CQA_LLM_MODE": "replay", "CQA_DB_PATH": str(db), "CQA_LLM_RPM": "0"}
    cmd = [sys.executable, "-m", "uvicorn", "cqa.http.app:create_app", "--factory"]
    cmd += ["--app-dir", str(ROOT / "src"), "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=30) as api:
            _wait_health(api, proc)
            json_body = {"Content-Type": "application/json"}
            added = api.post("/api/datasets/upload", content=DEMO_SET.read_bytes(), headers=json_body)
            print(f"набор защиты: {added.raise_for_status().json()}, витрина: операторы {', '.join(operators)}")
            staff = DEMO_EMPLOYEES.read_text(encoding="utf-8").rstrip("\n").splitlines()
            staff += [f"sc-op-{i};{name};operator;Линия 3" for i, name in enumerate(operators, 1)]
            api.post("/api/employees/import", content="\n".join(staff).encode()).raise_for_status()
            started = api.post("/api/runs", json={"dialogs": None, "criteria": None}).raise_for_status()
            url = f"/api/runs/{started.json()['run_id']}"
            while (run := api.get(url).raise_for_status().json())["status"] == "running":
                time.sleep(0.5)
            print(f"оценено {run['done']}/{run['total']}, ошибок {len(run['errors'])}")
            if run["errors"]:
                print(f"первая ошибка: {run['errors'][0]}; не хватает записей: make record", file=sys.stderr)
            alerts = api.post("/api/alerts/evaluate")  # оповещения, если они уже есть в сборке
            if alerts.status_code == 200:
                print(f"оповещения: {alerts.json()}")
        print(f"Готово: {base}/#/analytics  (Ctrl+C — остановить)")
        return proc.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        proc.wait(10)


def _wait_health(api: httpx.Client, proc: subprocess.Popen[bytes], limit_s: float = 30) -> None:
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"сервер не поднялся, код {proc.returncode}")
        try:
            if api.get("/api/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise SystemExit(f"сервер не ответил на /api/health за {limit_s:.0f} с")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pick = sub.add_parser("pick", help="подобрать диалоги для шагов защиты")
    p_check = sub.add_parser("check", help="проверка готовности за 15 минут")
    sub.add_parser("serve", help="make demo")
    p_show = sub.add_parser("showcase", help="make showcase: витрина для экранов аналитики")
    p_show.add_argument("--port", type=int, default=8000)
    for p in (p_pick, p_check):
        p.add_argument("--base", default=BASE)
    p_check.add_argument("--pick", type=Path, required=True)
    p_check.add_argument("--run", action="append", default=[])
    p_check.add_argument("--call")
    p_check.add_argument(
        "--draft", type=Path, default=ROOT / "tests" / "e2e" / "fixtures" / "replacement_criterion.json"
    )
    p_check.add_argument("--model")
    p_check.add_argument("--where")
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        return serve()
    if args.cmd == "showcase":
        return showcase(args.port)
    settings = Settings()
    with httpx.Client(base_url=args.base, timeout=30) as api:
        if args.cmd == "pick":
            state = api.get("/api/state").raise_for_status().json()
            print(json.dumps(pick(state, dev_snapshot(settings.eval_dataset)), ensure_ascii=False, indent=2))
            return 0
        picked = json.loads(args.pick.read_text(encoding="utf-8"))
        model, where = args.model or settings.llm_model, args.where or settings.data_where
        items = check(api, picked, args.run, args.call, model, where, args.draft)
    for ok, text in items:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print("Вручную:")
    for text in MANUAL:
        print(f"  [ ] {text}")
    return 0 if all(ok for ok, _ in items) else 1


if __name__ == "__main__":
    sys.exit(main())
