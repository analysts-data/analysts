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
    # интеграционный API, не для интерфейса: CRM, Dynamics 365 и контакт-центр
    "/evaluate",
    "/evaluate/batch",
    "/dialogs/{dialog_id}",
    "/runs/{run_id}/dialogs",
}

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
