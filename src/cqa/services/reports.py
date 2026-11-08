"""Отчёты по замерам: прогоны make eval из каталога отчётов, отчёт запуска, файлы результатов, каталог.

Отчёты make eval содержат обоснования модели по реальным диалогам: сервер отдаёт их локально,
в git и фикстуры они не попадают (каталог в .gitignore).
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cqa.adapters.store import Store
from cqa.domain.reports import quality_checks, quality_doc, run_doc, run_report
from cqa.domain.review import stamp
from cqa.domain.tables import to_csv, to_html, to_markdown
from cqa.services.errors import NotFound
from cqa.services.quality_eval import REPO, THRESHOLDS, load_thresholds

Format = Literal["html", "json", "md", "csv"]
STAMP = "%Y%m%dT%H%M%SZ"  # имя файла make eval: eval/reports/<STAMP>.json
RENDER = {"html": to_html, "md": to_markdown, "csv": to_csv}


def _when(report_id: str) -> datetime:
    """Время прогона из имени файла; другое имя (holdout-…, «../…») — ValueError."""
    return datetime.strptime(report_id, STAMP).replace(tzinfo=UTC)


def _body(path: Path) -> dict[str, Any] | None:
    """Тело отчёта make eval; битый файл или другой формат — None."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and "agree_total" in body else None


def quality_runs(directory: Path) -> list[dict[str, Any]]:
    """Прогоны make eval, новые первыми; нет каталога — пустой список."""
    out = []
    for path in directory.glob("*.json"):
        try:
            created = _when(path.stem)
        except ValueError:
            continue
        if (body := _body(path)) is not None:
            out.append(
                {
                    "id": path.stem,
                    "created": f"{created:%Y-%m-%dT%H:%M:%SZ}",
                    "model": body.get("model"),
                    "n_dialogs": body.get("n_dialogs"),
                    "agree_total": body.get("agree_total"),
                    "passed": not body.get("problems"),
                }
            )
    return sorted(out, key=lambda r: r["created"], reverse=True)


def quality(store: Store, directory: Path, report_id: str, fmt: Format) -> dict[str, Any] | str:
    """json — тело отчёта с обоснованиями и проверкой порогов; csv, md, html — без текстов модели."""
    try:
        created = _when(report_id)
    except ValueError:
        raise NotFound(f"Замер {report_id} не найден") from None
    body = _body(directory / f"{report_id}.json")
    if body is None:
        raise NotFound(f"Замер {report_id} не найден")
    thresholds = load_thresholds((REPO / THRESHOLDS).read_text(encoding="utf-8"))
    if fmt == "json":
        return {"id": report_id, "created": f"{created:%Y-%m-%dT%H:%M:%SZ}", **body} | {
            "thresholds": quality_checks(body, thresholds)
        }
    checklist = store.current_checklist()
    names = {c.id: c.name for c in checklist.criteria} if checklist else {}
    meta = f"Прогон make eval {stamp(created)} · {report_id}"
    return RENDER[fmt](quality_doc(body, thresholds, names=names, meta=meta))


def run(store: Store, run_id: int, fmt: Format, now: float) -> dict[str, Any] | str:
    row = store.get_run(run_id)
    if row is None:
        raise NotFound(f"Запуск {run_id} не найден")
    checklist = store.current_checklist()
    names = {c.id: c.name for c in checklist.criteria} if checklist else {}
    results = store.results_between(row.started, row.finished or now)
    rep = run_report(asdict(row), results, names=names)
    return rep if fmt == "json" else RENDER[fmt](run_doc(rep))


def results_file(directory: Path, which: str) -> Path:
    path = directory / which / "results.json"
    if not path.is_file():
        raise NotFound(f"Файла результатов {which} нет: соберите его make results SET={which}")
    return path


ALL: list[Format] = ["html", "json", "md", "csv"]
# route — путь в приложении: отчёт попадает в каталог, только если путь есть (чужие PR ещё не слиты)
CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "executive",
        "title": "Отчёт для руководства",
        "description": "Средний итог, грубые нарушения, критерии, причины потери баллов, каналы и языки",
        "formats": ALL,
        "href_template": "/api/report?format={format}",
        "route": "/api/report",
    },
    {
        "id": "quality",
        "title": "Качество оценки",
        "description": "Прогон make eval: совпадение с эталоном по языкам и критериям, грубые ошибки, N/A, "
        "стабильность, основания, цена, пороги и расхождения",
        "formats": ALL,
        "href_template": "/api/quality/{id}?format={format}",
        "items": "/api/quality",
        "route": "/api/quality/{report_id}",
    },
    {
        "id": "run",
        "title": "Запуск оценки",
        "description": "Ход, цена и ошибки запуска, модель, версия чек-листа и ответы по критериям",
        "formats": ALL,
        "href_template": "/api/runs/{id}/report?format={format}",
        "items": "/api/runs",
        "route": "/api/runs/{run_id}/report",
    },
    {
        "id": "scores",
        "title": "Итоги по диалогам",
        "description": "Итог и ответы каждого диалога для Excel",
        "formats": ["csv"],
        "href_template": "/api/scores/export?format={format}",
        "route": "/api/scores/export",
    },
    {
        "id": "operators",
        "title": "Аналитика по операторам",
        "description": "Итоги и нарушения по операторам",
        "formats": ["json"],
        "href_template": "/api/operators",
        "route": "/api/operators",
    },
    {
        "id": "checklist",
        "title": "Чек-лист",
        "description": "Текущая версия: памятка оператора для печати, таблица для Excel, Markdown, JSON",
        "formats": ALL,
        "href_template": "/api/checklist/export?format={format}",
        "route": "/api/checklist/export",
    },
    {
        "id": "checklist-diff",
        "title": "Что изменилось в чек-листе",
        "description": "Разница версии from и текущей: что нужно оценить заново",
        "formats": ["md", "json"],
        "href_template": "/api/checklist/diff?from={from}&format={format}",
        "route": "/api/checklist/diff",
    },
]


def catalogue(routes: set[str], results_dir: Path) -> list[dict[str, Any]]:
    """Отчёты продукта для страницы «Отчёты»: только с путём в приложении; файлы результатов — если есть."""
    out = [{k: v for k, v in r.items() if k != "route"} for r in CATALOGUE if r["route"] in routes]
    for which in ("dev", "prod"):
        if (results_dir / which / "results.json").is_file():
            out.append(
                {
                    "id": f"results-{which}",
                    "title": f"Файл результатов для организаторов, {which.upper()}",
                    "description": "JSON 1.0 из make results: ответы по критериям каждого диалога",
                    "formats": ["json"],
                    "href_template": f"/api/results/{which}",
                }
            )
    return out
