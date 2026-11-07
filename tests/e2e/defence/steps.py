"""Шаги сценария защиты на публичном API и интерфейсе (design, решения 10 и 11).

Локаторы — таблица «Интерфейс» `design/ports.md`. Ожидаемые ответы не зашиты: шаги читают
`GET /api/state` (то, что записано в кассетах) и сверяют экран с ним и с `web/js/scoring.js`.
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Locator, Page, Route, expect

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUN_TIMEOUT_S = 60
CALC_JS = """async id => {
  const {calc} = await import('/js/scoring.js');
  const s = await (await fetch('/api/state')).json();
  return calc(s.dialogs.find(d => d.id === id), s.checklist, s.appeals).total;
}"""

CARD = "p1-ru-022"
NA = "p1-ru-025"
CALL = "call-024"
HOLD = "Удержание и разговор с коллегой"
APPEAL_DLG, APPEAL_CID = "p1-ru-003", "04"
DECISION = "Срок ответа назван в реплике 8"
FLAG_DECISION = "Оператор направил клиента в приложение, платной услуги нет"
WHERE = {"kz": "Казахстан", "local": "локально", "external": "внешний провайдер"}  # плашка cqa-web-ui


@dataclass
class Defence:
    page: Page
    api: httpx.Client
    console_errors: list[str] = field(default_factory=list)
    # апелляция на заменяемый критерий: подаёт mode_and_roles, закрывает replace
    open_appeal: dict[str, Any] | None = None

    def go(self, route: str) -> None:
        self.page.goto(f"{self.api.base_url}{route}")

    def state(self) -> dict[str, Any]:
        return self.api.get("/api/state").raise_for_status().json()

    @property
    def body(self) -> Locator:
        return self.page.locator("body")

    def total(self, dialog_id: str) -> float | None:
        """`calc(...).total` из `web/js/scoring.js` на `GET /api/state`, в странице сервера."""
        return self.page.evaluate(CALC_JS, dialog_id)


def mode_and_roles(d: Defence) -> None:
    """Перед шагами: плашка режима из `state.mode`, решение у проверяющего, «Оспорить» у оператора.

    Подаёт апелляцию на критерий из `replacement_criterion.json`: её закрывает шаг замены.
    """
    s = d.state()
    d.go("#/queue")
    expect(d.body).to_contain_text(s["mode"]["model"])
    expect(d.body).to_contain_text(WHERE[s["mode"]["where"]])
    c = criterion(s["checklist"], load_fixture("replacement_criterion.json")["id"])
    current = dialog(s, CARD)["res"][c["id"]]["a"]
    ask = next(v for v in allowed(c) if v != current)
    filed = {"dlg": CARD, "cid": c["id"], "ask": ask, "ev": [], "comment": "Итог подведён.", "by": "Оператор"}
    d.open_appeal = d.api.post("/api/appeals", json=filed).raise_for_status().json()
    d.page.reload()
    role(d.page, "reviewer")
    d.go("#/appeals")
    expect(d.page.locator('[data-act="decide"]')).to_be_visible()
    role(d.page, "operator")
    d.go(f"#/d/{APPEAL_DLG}")
    expect(open_criterion(d.page, APPEAL_CID).locator('[data-act="appeal"]')).to_be_visible()


def queue(d: Defence) -> None:
    """Список (60 с): грубые ошибки наверху, причина в аналитике ведёт к диалогу, строка — к карточке."""
    s = d.state()
    ids = [x["id"] for x in s["dialogs"]]
    gross = {x["id"] for x in s["dialogs"] if flags_of(x, s["checklist"])}
    # какие нарушения модель нашла, меряет make eval; сюжету защиты нужна грубая ошибка карточки
    assert CARD in gross, f"грубые ошибки в ответах модели: {sorted(gross)}"
    d.go("#/queue")
    rows = d.page.locator('[data-act="open"][data-id]')
    expect(rows).to_have_count(len(ids))
    order = rows.evaluate_all("rows => rows.map(r => r.dataset.id)")
    first_clean = min(i for i, x in enumerate(order) if x not in gross)
    assert all(order.index(x) < first_clean for x in gross), order

    d.go("#/analytics")
    reason = d.page.locator('[data-view="analytics"] a[href^="#/d/"]').first
    href = reason.get_attribute("href") or ""
    assert href.removeprefix("#/d/") in ids, href
    reason.click()
    expect(d.page).to_have_url(re.compile(re.escape(href) + "$"))

    d.go("#/queue")
    d.page.locator(f'[data-act="open"][data-id="{CARD}"]').click()
    expect(d.page).to_have_url(re.compile(f"#/d/{CARD}$"))


def card(d: Defence) -> None:
    """Карточка (60 с): балл, вес и обоснование, переход к реплике, грубая ошибка не обнуляет итог."""
    s = d.state()
    cl, dlg = s["checklist"], dialog(s, CARD)
    d.go(f"#/d/{CARD}")
    for c in scored(cl):
        r = dlg["res"][c["id"]]
        assert r["why"], f"{CARD} {c['id']}: нет обоснования"
        box = open_criterion(d.page, c["id"])
        expect(box).to_contain_text(points_text(c, r["a"]))
        expect(box).to_contain_text(r["why"])
    cid, n = next((c["id"], dlg["res"][c["id"]]["ev"][0]) for c in scored(cl) if dlg["res"][c["id"]]["ev"])
    open_criterion(d.page, cid).locator(f'[data-act="ev"][data-n="{n}"]').click()
    expect(line(d.page, n)).to_be_in_viewport()
    flags = flags_of(dlg, cl)
    assert flags, f"у {CARD} нет грубой ошибки"
    for label in flags:
        expect(d.body).to_contain_text(label)
    total = d.total(CARD)
    assert total, f"итог {CARD}: {total}"
    expect(d.body).to_contain_text(f2(total))


def na_and_call(d: Defence) -> None:
    """N/A и звонок (60 с): условие N/A и итог; переход к фрагменту записи, удержание свёрнуто."""
    s = d.state()
    cl, dlg = s["checklist"], dialog(s, NA)
    nas = [c for c in scored(cl) if dlg["res"][c["id"]]["a"] == "na"]
    assert nas, f"у {NA} нет N/A"
    d.go(f"#/d/{NA}")
    for c in nas:
        expect(open_criterion(d.page, c["id"])).to_contain_text(c["naCond"])
    total = d.total(NA)
    assert total is not None, f"итог {NA} не рассчитан"
    expect(d.body).to_contain_text(f2(total))

    call = dialog(s, CALL)
    lines = {x["n"]: x for x in call["lines"] if not x.get("fold")}
    hold = next(x for x in call["lines"] if x.get("fold") and x["label"] == HOLD)
    inside = set(range(hold["from"], hold["to"] + 1))
    assert inside <= lines.keys(), "реплики удержания пропали из lines"
    evidence = {n for r in call["res"].values() for n in r["ev"]}
    assert not evidence & inside, f"основания внутри удержания: {sorted(evidence & inside)}"
    cid, n = next(
        (c["id"], n) for c in scored(cl) for n in call["res"][c["id"]]["ev"] if lines[n]["s"] is not None
    )
    d.go(f"#/d/{CALL}")
    open_criterion(d.page, cid).locator(f'[data-act="seek"][data-n="{n}"]').first.click()
    d.page.wait_for_function(
        "s => Math.abs((document.querySelector('audio')?.currentTime ?? -1) - s) <= 0.5", arg=lines[n]["s"]
    )
    expect(line(d.page, n)).to_contain_text(mmss(lines[n]["t"]))
    fold = line(d.page, hold["from"] - 1).locator(f"xpath=following-sibling::*[contains(., '{HOLD}')][1]")
    expect(fold).to_contain_text("не оценивается")
    expect(line(d.page, hold["from"])).to_be_hidden()
    fold.get_by_role("button").first.click()
    expect(line(d.page, hold["from"])).to_be_visible()


def appeal(d: Defence) -> None:
    """Апелляция (60 с): оператор просит ступень выше, решение без причины невозможно, итоги рядом."""
    s = d.state()
    c, res = criterion(s["checklist"], APPEAL_CID), dialog(s, APPEAL_DLG)["res"][APPEAL_CID]
    ask = min((x for x in c["steps"] if isinstance(res["a"], int) and x > res["a"]), default=None)
    assert ask is not None, f"{APPEAL_DLG} {APPEAL_CID}: нет ступени выше {res['a']!r}"
    d.go(f"#/d/{APPEAL_DLG}")
    before = d.total(APPEAL_DLG)
    role(d.page, "operator")
    open_criterion(d.page, APPEAL_CID).locator('[data-act="appeal"]').click()
    form = d.page.get_by_role("dialog")
    form.get_by_label("Какой ответ вы считаете верным").select_option(str(ask))
    form.get_by_label("Комментарий").fill("Срок вывода назван в реплике 8, это существенная часть ответа.")
    with d.page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/api/appeals")
    ) as filed:
        form.get_by_role("button", name="Отправить апелляцию").click()
    a = filed.value.json()
    assert (a["kind"], a["status"], a["ask"]) == ("appeal", "pending", ask), a

    role(d.page, "reviewer")
    d.go(f"#/appeals/{a['id']}")
    decide = d.page.locator('[data-act="decide"]')
    expect(decide).to_be_disabled()
    d.page.locator('[data-view="appeals"] textarea').fill(DECISION)
    with d.page.expect_response(lambda r: r.url.endswith(f"/api/appeals/{a['id']}/decision")) as decided:
        decide.click()
    assert decided.value.json()["status"] == "changed"

    s = d.state()
    a = next(x for x in s["appeals"] if x["id"] == a["id"])
    assert (a["status"], a["to"], a["reason"]) == ("changed", ask, DECISION), a
    assert dialog(s, APPEAL_DLG)["res"][APPEAL_CID] == res, "исходный res изменился"
    after = d.total(APPEAL_DLG)
    assert after != before, f"итог не изменился: {before}"
    d.go(f"#/d/{APPEAL_DLG}")
    open_criterion(d.page, APPEAL_CID)
    for text in (answer_text(c, res["a"]), f2(before), f2(after)):
        expect(d.body).to_contain_text(text)


def flag_appeal(d: Defence) -> None:
    """Грубая ошибка оспорена: оператор снимает нарушения, проверяющий решает с причиной; флаг уходит
    из группы «Грубые ошибки», исходный `res` и итог прежние."""
    s = d.state()
    fc = next(c for c in s["checklist"]["criteria"] if c["type"] == "flag")
    res, flags = dialog(s, CARD)["res"][fc["id"]], flags_of(dialog(s, CARD), s["checklist"])
    assert flags, f"у {CARD} нет грубой ошибки"
    before = d.total(CARD)
    d.go(f"#/d/{CARD}")
    role(d.page, "operator")
    open_criterion(d.page, fc["id"]).locator('[data-act="appeal"]').click()
    form = d.page.get_by_role("dialog")
    for label in flags:
        form.get_by_label(label).uncheck()
    form.get_by_label("Комментарий").fill("Нарушения не было: клиенту предложили путь через приложение.")
    with d.page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/api/appeals")
    ) as filed:
        form.get_by_role("button", name="Отправить апелляцию").click()
    a = filed.value.json()
    clear = {q["k"]: False for q in fc["questions"]}
    assert (a["status"], a["from"], a["ask"]) == ("pending", res["a"], clear), a

    role(d.page, "reviewer")
    d.go(f"#/appeals/{a['id']}")
    d.page.locator('[data-view="appeals"] textarea').fill(FLAG_DECISION)
    with d.page.expect_response(lambda r: r.url.endswith(f"/api/appeals/{a['id']}/decision")) as decided:
        d.page.locator('[data-act="decide"]').click()
    assert (decided.value.json()["status"], decided.value.json()["to"]) == ("changed", clear)

    s = d.state()
    assert dialog(s, CARD)["res"][fc["id"]] == res, "исходный res изменился"
    assert d.total(CARD) == before, "флаг изменил итог"
    d.go("#/queue?grp=risk")
    expect(d.page.locator(f'[data-act="open"][data-id="{CARD}"]')).to_have_count(0)


def replace(d: Defence) -> None:
    """Замена критерия (30 с): версия +1, «Ждёт оценки», апелляция закрыта, оценка набора с прогрессом."""
    new = load_fixture("replacement_criterion.json")
    cid = new["id"]
    s = d.state()
    old = criterion(s["checklist"], cid)
    assert all(old.get(k) == v for k, v in new.items() if k != "text"), (
        "черновик отличается не только текстом"
    )
    assert d.open_appeal and d.open_appeal["cid"] == cid, (
        "апелляцию на заменяемый критерий подаёт mode_and_roles"
    )
    role(d.page, "qa")
    d.go("#/checklist")
    d.page.locator(f'[data-view="checklist"] [data-cid="{cid}"]').first.click()
    d.page.get_by_label("Что проверяем").fill(new["text"])
    with d.page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith("/api/checklist")
    ) as put:
        d.page.locator('[data-act="csave"]').click()
    saved = put.value.json()
    assert saved["version"] == s["checklist"]["version"] + 1 and cid in saved["pending"], saved

    s = d.state()
    assert s["checklist"]["version"] == saved["version"]
    assert criterion(s["checklist"], cid)["text"] == new["text"]
    assert not [x["id"] for x in s["dialogs"] if cid in x["res"]], "заменённый критерий не ждёт оценки"
    closed = next(a for a in s["appeals"] if a["id"] == d.open_appeal["id"])
    assert closed["status"] == "closed", closed
    d.go(f"#/d/{closed['dlg']}")
    expect(criterion_box(d.page, cid)).to_contain_text(re.compile("ждёт оценки", re.IGNORECASE))

    d.go("#/checklist")
    with d.page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/runs")) as post:
        d.page.locator('[data-act="crun"]').click()
    run = wait_run(d.api, post.value.json()["run_id"])
    assert (run["status"], run["errors"], run["done"]) == ("done", [], run["total"]), run
    # в replay запуск короче секунды опроса: прогресс и цена GET /api/runs/{id} — на панели очереди
    d.go("#/queue")
    expect(d.body).to_contain_text(
        re.compile(rf"оценено {run['done']} из {run['total']} ответов", re.IGNORECASE)
    )
    expect(d.body).to_contain_text(f"{run['calls']} вызовов, ${num(run['cost'])}")
    s = d.state()
    assert all(cid in x["res"] for x in s["dialogs"]), "не у всех диалогов есть ответ на новый критерий"
    calls = dialog(s, CARD)["cost"]["calls"]
    d.go(f"#/d/{CARD}")
    d.page.reload()  # стоимость последней оценки, а не снимок до опроса запуска
    expect(d.body).to_contain_text(re.compile(rf"\b{calls}\b\D*вызов"))
    expect(d.body).to_contain_text("$")


def no_total(d: Defence) -> None:
    """Репетиция «Итог не рассчитывается»: у NA все критерии с весом — N/A, итог «—», консоль чиста."""

    def all_na(route: Route) -> None:
        resp = route.fetch()
        state = resp.json()
        res = dialog(state, NA)["res"]
        for c in scored(state["checklist"]):
            if c["w"]:
                res[c["id"]] = {**res[c["id"]], "a": "na", "alt": None}
        route.fulfill(response=resp, json=state)

    d.page.route("**/api/state", all_na)
    d.go(f"#/d/{NA}")
    d.page.reload()
    assert d.total(NA) is None
    expect(d.page.get_by_text("Итог", exact=True).first.locator("xpath=..")).to_contain_text("—")
    d.go("#/queue")
    expect(d.page.locator(f'[data-act="open"][data-id="{NA}"]')).to_contain_text("—")
    assert d.console_errors == [], d.console_errors


def wait_run(api: httpx.Client, run_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while (run := api.get(f"/api/runs/{run_id}").raise_for_status().json())["status"] == "running":
        assert time.monotonic() < deadline, f"запуск {run_id} идёт дольше {RUN_TIMEOUT_S} с: {run}"
        time.sleep(0.2)
    return run


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def dialog(state: dict[str, Any], dialog_id: str) -> dict[str, Any]:
    return next(x for x in state["dialogs"] if x["id"] == dialog_id)


def criterion(checklist: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(c for c in checklist["criteria"] if c["id"] == cid)


def scored(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in checklist["criteria"] if c["type"] != "flag"]


def flags_of(dlg: dict[str, Any], checklist: dict[str, Any]) -> list[str]:
    """Подписи найденных нарушений, как `flagsOf` в `web/js/scoring.js`."""
    flags = [c for c in checklist["criteria"] if c["type"] == "flag" and c["id"] in dlg["res"]]
    return [q["label"] for c in flags for q in c["questions"] if dlg["res"][c["id"]]["a"].get(q["k"])]


def num(x: float) -> str:
    """Число как `toLocaleString('ru-RU', {maximumFractionDigits: 2})` для значений до 1000."""
    return f"{round(x, 2):g}".replace(".", ",")


def f2(total: float | None) -> str:
    """Итог на экране: два знака с запятой или «—»."""
    return "—" if total is None else f"{total:.2f}".replace(".", ",")


def mmss(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def allowed(c: dict[str, Any]) -> list[Any]:
    """Допустимые ответы критерия, как в окне апелляции."""
    return (["yes", "no"] if c["type"] == "bool" else list(c["steps"])) + (["na"] if c["na"] else [])


def answer_text(c: dict[str, Any], a: Any) -> str:
    """Ответ на экране: «Да», «Нет», «N/A» или «15 из 20»."""
    if c["type"] == "scale" and a != "na":
        return f"{a} из {max(c['steps'])}"
    return {"yes": "Да", "no": "Нет", "na": "N/A"}[a]


def points_text(c: dict[str, Any], a: Any) -> str:
    """Балл и вес критерия: «7,5 / 15», у N/A — «—»."""
    if a == "na":
        return "—"
    share = a / max(c["steps"]) if c["type"] == "scale" else float(a == "yes")
    return f"{num(c['w'] * share)} / {num(c['w'])}"


def criterion_box(page: Page, cid: str) -> Locator:
    return page.locator(f'[data-cid="{cid}"]:not([data-act])').first


def open_criterion(page: Page, cid: str) -> Locator:
    """Раскрывает критерий в карточке, если он свёрнут."""
    box = criterion_box(page, cid)
    toggle = box.locator("[aria-expanded]").first
    if toggle.get_attribute("aria-expanded") == "false":
        toggle.click()
    return box


def line(page: Page, n: int) -> Locator:
    """Реплика расшифровки, не кнопка с тем же `data-n`."""
    return page.locator(f'[data-n="{n}"]:not([data-act])')


def role(page: Page, name: str) -> None:
    page.locator(f'[data-act="role"][data-role="{name}"]').click()
