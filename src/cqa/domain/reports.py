"""Отчёты по замерам: качество оценки (тело eval/reports/*.json от make eval) и запуск оценки.

Чистые функции: данные для json и форма `Doc` для csv, md и html. В `Doc` нет текстов модели
(`why`, `quote`): печатные отчёты не несут производного от диалогов текста.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any

from cqa.domain.agreement import Thresholds
from cqa.domain.models import CriterionResult
from cqa.domain.review import ASTANA, stamp
from cqa.domain.tables import Doc, Table

ANSWER = {"yes": "да", "no": "нет", "na": "N/A", "none": "без нарушений"}


def _d(x: float | None, nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _key(a: Any) -> str:
    """Ответ строкой: yes, no, na, ступень; у флага — отмеченные подвопросы через «+» или none."""
    if isinstance(a, dict):
        return "+".join(k for k, v in a.items() if v) or "none"
    return str(a)


def _answer(a: Any) -> str:
    return "нет ответа" if a is None else ANSWER.get(k := _key(a), k)


def _named(cid: str, names: Mapping[str, str]) -> str:
    return f"{cid} {names[cid]}" if cid in names else cid


# --- Качество оценки ---

CHECKS = {  # порог eval/thresholds.yaml -> (подпись, поле отчёта; None — считается отдельно)
    "gross_recall_min": ("Полнота грубых ошибок, худший вид и язык", None),
    "kz_gap_max_pts": ("Разрыв RU−KZ, пункты", "kz_gap_pts"),
    "na_precision_min": ("Точность N/A", "na_precision"),
    "na_recall_min": ("Полнота N/A", "na_recall"),
    "stability_min": ("Стабильность двух прогонов", "stability"),
    "evidence_ok_min": ("Основания прошли проверку цитаты", "evidence_ok"),
    "holdout_agreement_min": ("Совпадение отложенных критериев", "holdout_agreement"),
    # ponytail: лучший прогон в отчёт не пишется, значения нет; регресс к нему — в `problems`
    "baseline_drop_max_pts": ("Падение к лучшему прогону, пункты", None),
}


def _value(name: str, rep: Mapping[str, Any]) -> float | None:
    if name == "gross_recall_min":
        values = [
            v for m in (rep["gross_recall"], rep["gross_recall_lang"]) for v in m.values() if v is not None
        ]
        return min(values) if values else None
    field = CHECKS.get(name, ("", None))[1]
    return None if field is None else rep.get(field)


def quality_checks(rep: Mapping[str, Any], thresholds: Thresholds) -> list[dict[str, Any]]:
    """Каждый порог eval/thresholds.yaml против значения прогона; ok None — значения нет."""
    out = []
    for name, limit in asdict(thresholds).items():
        value, upper = _value(name, rep), "_max" in name
        ok = None if value is None else (value <= limit if upper else value >= limit)
        label = CHECKS.get(name, (name, None))[0]
        out.append({"name": name, "label": label, "limit": limit, "upper": upper, "value": value, "ok": ok})
    return out


def _gold(gold: Sequence[Any]) -> str:
    return " / ".join(map(_answer, gold))


def quality_doc(
    rep: Mapping[str, Any], thresholds: Thresholds, *, names: Mapping[str, str], meta: str
) -> Doc:
    verifier, tags = rep.get("verifier"), rep.get("tags")
    summary = [
        ["Диалогов эталона", str(rep["n_dialogs"])],
        ["Модель", rep["model"] or "—"],
        ["Совпадение с эталоном", _d(rep["agree_total"])],
        ["Разрыв RU−KZ, пункты", _d(rep["kz_gap_pts"], 1)],
        ["Ждут оценки (нет ответа)", str(rep["missing"])],
        ["Стабильность двух прогонов", _d(rep["stability"])],
        ["Основания прошли проверку цитаты", _d(rep["evidence_ok"])],
        [
            "Итог make eval",
            "пороги пройдены" if not rep["problems"] else f"не прошло: {len(rep['problems'])}",
        ],
    ]
    if verifier:
        summary.append(
            [
                "Второе мнение: расходится / ловит ошибки",
                f"{_d(verifier['disagree'])} / {_d(verifier['catch'])}",
            ]
        )
    if tags:
        summary.append(["Теги причин: повторяются / одиночные", f"{tags['recurring']} / {tags['single']}"])
    gross = [[f"вид {k}", _d(v)] for k, v in rep["gross_recall"].items()]
    gross += [[f"язык {k}", _d(v)] for k, v in rep["gross_recall_lang"].items()]
    gross.append(["Ложные флаги", str(rep["false_flags"])])
    cost = [
        ["Стоимость, $", _d(rep["cost"], 4)],
        ["На диалог, $", _d(rep.get("cost_per_dialog"), 4)],
        ["Вызовов модели", str(rep["calls"])],
        ["Вызовов на диалог", _d(rep.get("calls_per_dialog"), 1)],
        ["Время прогона, с", _d(rep["seconds"], 0)],
    ]
    checks = [
        [
            c["label"],
            f"{'≤' if c['upper'] else '≥'} {_d(c['limit'])}",
            _d(c["value"]),
            "нет данных" if c["ok"] is None else "пройден" if c["ok"] else "не пройден",
        ]
        for c in quality_checks(rep, thresholds)
    ]
    tables = [
        Table("Сводка", ["Показатель", "Значение"], summary, {1}),
        Table(
            "Совпадение по языкам",
            ["Язык", "Совпадение"],
            [[k, _d(v)] for k, v in rep["per_lang"].items()],
            {1},
        ),
        Table(
            "Совпадение по критериям",
            ["Критерий", "Совпадение"],
            [[_named(k, names), _d(v)] for k, v in sorted(rep["per_cid"].items())],
            {1},
        ),
        Table("Полнота грубых ошибок", ["Срез", "Значение"], gross, {1}),
        Table("Пропущенные грубые ошибки", ["Диалог", "Вид"], [list(m) for m in rep["gross_missed"]]),
        Table(
            "N/A",
            ["Показатель", "Значение"],
            [["Точность", _d(rep["na_precision"])], ["Полнота", _d(rep["na_recall"])]],
            {1},
        ),
        Table("Цена и время", ["Показатель", "Значение"], cost, {1}),
        Table("Пороги", ["Порог", "Требование", "Значение", "Итог"], checks, {1, 2}),
        Table("Замечания прогона", ["Замечание"], [[p] for p in rep["problems"]]),
        Table(
            "Расхождения с эталоном",
            ["Диалог", "Критерий", "Эталон", "Ответ модели"],
            [
                [d["dlg"], _named(d["cid"], names), _gold(d["gold"]), _answer(d["got"])]
                for d in rep["disagreements"]
            ],
        ),
    ]
    note = (
        "Обоснования модели по расхождениям — только в json отчёта: печатный отчёт не несёт текста диалогов."
    )
    return Doc("Качество оценки", "Сверка с эталоном", meta, tables, note)


# --- Запуск оценки ---

STATUS = {"running": "идёт", "done": "завершён", "cancelled": "отменён"}


def _when(epoch: float | None) -> str | None:
    return None if epoch is None else stamp(datetime.fromtimestamp(epoch, ASTANA))


def run_report(
    run: Mapping[str, Any], results: Sequence[tuple[str, int, CriterionResult]], *, names: Mapping[str, str]
) -> dict[str, Any]:
    """`run` — строка таблицы runs; `results` — (cid, версия чек-листа, результат) ответов этого запуска."""
    by_cid: dict[str, Counter[str]] = {}
    for cid, _, r in results:
        by_cid.setdefault(cid, Counter())[_key(r.a)] += 1
    return {
        **run,
        "started_at": _when(run["started"]),
        "finished_at": _when(run["finished"]),
        "progress": round(run["done"] / run["total"], 4) if run["total"] else None,
        "models": sorted({r.model for _, _, r in results if r.model}),
        "checklist_versions": sorted({v for _, v, _ in results}),
        "criteria": [
            {"cid": cid, "name": names.get(cid), "n": sum(c.values()), "answers": dict(c.most_common())}
            for cid, c in sorted(by_cid.items())
        ],
    }


def run_doc(rep: Mapping[str, Any]) -> Doc:
    pct = "" if rep["progress"] is None else f" ({round(100 * rep['progress'])} %)"
    summary = [
        ["Статус", STATUS.get(rep["status"], rep["status"])],
        ["Начат", rep["started_at"] or "—"],
        ["Завершён", rep["finished_at"] or "—"],
        ["Оценено пар", f"{rep['done']} из {rep['total']}{pct}"],
        ["Стоимость, $", _d(rep["cost"], 4)],
        ["Вызовов модели", str(rep["calls"])],
        ["Ошибок", str(len(rep["errors"]))],
        ["Модель", ", ".join(rep["models"]) or "—"],
        ["Версия чек-листа", ", ".join(f"v{v}" for v in rep["checklist_versions"]) or "—"],
    ]
    dist = [
        [
            f"{c['cid']} {c['name']}" if c["name"] else c["cid"],
            str(c["n"]),
            " · ".join(f"{ANSWER.get(k, k)} {n}" for k, n in c["answers"].items()),
        ]
        for c in rep["criteria"]
    ]
    tables = [
        Table("Сводка", ["Показатель", "Значение"], summary, {1}),
        Table("Ответы по критериям", ["Критерий", "Ответов", "Распределение"], dist, {1}),
        Table("Ошибки", ["Ошибка"], [[e] for e in rep["errors"]]),
    ]
    note = "Ответы запуска — результаты, записанные между его началом и концом, включая ручные."
    return Doc("Запуск оценки", f"Запуск №{rep['id']}", f"Начат {rep['started_at']}", tables, note)
