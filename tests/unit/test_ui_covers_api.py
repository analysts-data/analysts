"""Интерфейс охватывает весь HTTP API сервера (требование: «фронт охватывает весь функционал backend»).

Каждый путь из src/cqa/http/*.py должен встречаться в frontend/src (клиент lib/api.js или экран),
а каждый метод клиента createApi — вызываться хотя бы с одного экрана или из state.js.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTTP = ROOT / "src" / "cqa" / "http"
FRONT = ROOT / "frontend" / "src"
# Служебные пути без экрана: проверка живости для мониторинга и вход по ссылке с токеном (make share).
EXEMPT = {
    "/health",
    "/login",
    # пути отчётов приходят из каталога GET /api/reports (href_template, items), в коде интерфейса их нет
    "/quality",
    "/quality/{report_id}",
    "/runs/{run_id}/report",
    "/results/{which}",
    # текущий сотрудник: интерфейс знает его по выбору «Вы вошли как» (X-CQA-User), отдельный запрос не нужен
    "/me",
}
# UI в работе: шкала оценок, «что если», песочница, нормировка, шаблоны, готовые чек-листы (PR #91)
EXEMPT |= {
    "/bands", "/checklist/simulate", "/checklist/trial", "/checklist/normalize", "/checklist/presets",
    "/criteria/templates",
}  # fmt: skip
# UI в работе: колокольчик, страница алертов, чипы и фильтр маркеров (PR #87)
EXEMPT |= {
    "/alerts",
    "/alerts/evaluate",
    "/alerts/rules",
    "/alerts/{alert_id}/ack",
    "/alerts/{alert_id}/assignee",
    "/alerts/{alert_id}/resolve",
    "/dialogs/{dialog_id}/markers",
    "/markers/catalog",
}
# страницы документации, не API интерфейса (src/cqa/http/docs.py)
EXEMPT |= {"/docs", "/docs/", "/docs/search.json", "/docs/{slug}"}
# UI в работе: экран «Правила обработки» (спецификация в PR «правила обработки по типу взаимодействия»).
EXEMPT |= {"/routing", "/routing/explain"}
# UI в работе: выбор «Причина решения» в форме решения, плитка «Изменено людьми» в аналитике (PR #92)
EXEMPT |= {"/appeals/reasons", "/appeals/stats"}
# UI в работе: темы обращений (PR #95)
EXEMPT |= {"/products", "/products/stats", "/dialogs/{dialog_id}/product"}

ROUTE = re.compile(r'@(?:router|app)\.(?:get|post|put|delete|patch)\(\s*"([^"]+)"')


def _routes() -> set[str]:
    paths = set()
    for f in HTTP.glob("*.py"):
        for p in ROUTE.findall(f.read_text(encoding="utf-8")):
            paths.add(p.removeprefix("/api"))
    return paths - EXEMPT


def _front() -> str:
    files = (f for f in FRONT.rglob("*") if f.suffix in {".js", ".ts", ".tsx"})
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def test_every_backend_route_is_reachable_from_the_interface() -> None:
    src = _front()
    missing = []
    for path in sorted(_routes()):
        # {id} в маршруте — ${...} или любой сегмент в шаблоне клиента
        pattern = re.escape(path).replace(r"\{", "{").replace(r"\}", "}")
        pattern = re.sub(r"\{[^}]+\}", r"[^/\\s'\"`?]+", pattern)
        if not re.search(pattern + r"(?=[?'\"`/$]|$)", src, re.M):
            missing.append(path)
    assert not missing, f"нет входа в интерфейсе: {missing}"


def test_every_api_client_method_is_used_by_a_screen() -> None:
    api = (FRONT / "lib" / "api.js").read_text(encoding="utf-8")
    body = api[api.index("return {") :]
    methods = set(re.findall(r"^\s{4}(\w+)\s*[:,]", body, re.M)) - {"base", "get", "post", "put"}
    rest = "\n".join(
        f.read_text(encoding="utf-8")
        for f in FRONT.rglob("*")
        if f.suffix in {".js", ".ts", ".tsx"} and f.name != "api.js"
    )
    unused = sorted(m for m in methods if not re.search(rf"\.{m}\b|\b{m}\(", rest))
    assert not unused, f"метод клиента не вызывается ни с одного экрана: {unused}"
