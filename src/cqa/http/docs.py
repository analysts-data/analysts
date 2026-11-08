"""Документация продукта на /docs/: страницы Markdown из docs/site и справочник API из app.openapi().

Всё отдаёт сервер, без CDN и внешних шрифтов: страница работает без сети и в Dynamics. Сырой HTML в
Markdown экранируется. Справочник строится из живой схемы, поэтому новый маршрут виден в нём сразу.
"""

import json
import re
from functools import cache, lru_cache
from html import escape, unescape
from pathlib import Path
from string import Template
from typing import Any

import markdown
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markdown.extensions.toc import slugify_unicode

from cqa.services.errors import NotFound

ROOT = Path(__file__).resolve().parents[3]
# порядок навигации — по номеру в имени файла; регламент живёт в docs/ и подключается последним
FILES = [*sorted((ROOT / "docs" / "site").glob("*.md")), ROOT / "docs" / "runbook.md"]
PAGES = {re.sub(r"^\d+-", "", f.stem): f for f in FILES}
API_PAGE = "api"
LAYOUT = Template(Path(__file__).with_name("docs.html").read_text(encoding="utf-8"))
HEADING = re.compile(r'<h([23]) id="([^"]+)">(.*?)</h\1>', re.S)
H2 = re.compile(r'(<h2 id="[^"]+">.*?</h2>)', re.S)
# группы справочника: тег операции, иначе первый сегмент пути после /api
GROUPS = {
    "health": "Служебное",
    "state": "Состояние",
    "datasets": "Наборы диалогов",
    "source": "Наборы диалогов",
    "dialogs": "Диалоги",
    "runs": "Запуски оценки",
    "checklist": "Чек-лист",
    "appeals": "Апелляции и решения",
    "decisions": "Апелляции и решения",
    "owners": "Аналитика и отчёт",
    "report": "Аналитика и отчёт",
    "config": "Режим оценки и модели",
    "providers": "Режим оценки и модели",
}
RU = {"Successful Response": "Успешно", "Validation Error": "Ошибка проверки тела или параметров"}
SAMPLE = {"string": "строка", "integer": 0, "number": 0.0, "boolean": True}

router = APIRouter(include_in_schema=False)


def to_html(text: str) -> str:
    """Markdown → HTML: таблицы, блоки кода, якоря у заголовков; сырой HTML выводится как текст."""
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    return md.convert(text)


@cache
def _page(slug: str) -> tuple[str, str]:
    """(заголовок, HTML) страницы; файлы не меняются, пока работает сервер."""
    text = PAGES[slug].read_text(encoding="utf-8")
    title = re.search(r"^# (.+)$", text, re.M)
    return (title.group(1).strip() if title else slug), to_html(text)


def _text(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


# --- справочник API ---


def _name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _type(s: dict[str, Any]) -> str:
    """Тип поля схемы одной строкой HTML; модели — ссылки на раздел «Схемы данных»."""
    if "$ref" in s:
        name = escape(_name(s["$ref"]))
        return f'<a href="#schema-{name}">{name}</a>'
    for key in ("anyOf", "oneOf"):
        if key in s:
            return " | ".join(_type(x) for x in s[key])
    if "enum" in s or "const" in s:
        values = s.get("enum", [s.get("const")])
        return " | ".join(f"<code>{escape(json.dumps(v, ensure_ascii=False))}</code>" for v in values)
    if s.get("type") == "array":
        return _type(s.get("items", {})) + "[]"
    extra = s.get("additionalProperties")
    if isinstance(extra, dict) and extra:
        return "{строка: " + _type(extra) + "}"
    return escape(str(s.get("type", "любое")))


def _example(s: dict[str, Any], comps: dict[str, Any], depth: int = 0) -> Any:
    if depth > 6:  # рекурсивная модель
        return {}
    if "$ref" in s:
        return _example(comps[_name(s["$ref"])], comps, depth + 1)
    for key in ("example", "default", "const"):
        if key in s:
            return s[key]
    for key in ("anyOf", "oneOf"):
        if key in s:
            return _example(next((x for x in s[key] if x.get("type") != "null"), {}), comps, depth + 1)
    if "enum" in s:
        return s["enum"][0]
    if "properties" in s:
        return {k: _example(v, comps, depth + 1) for k, v in s["properties"].items()}
    if s.get("type") == "array":
        return [_example(s.get("items", {}), comps, depth + 1)]
    extra = s.get("additionalProperties")
    if isinstance(extra, dict) and extra:
        return {"<ключ>": _example(extra, comps, depth + 1)}
    return SAMPLE.get(s.get("type", ""), {})


def _fields(s: dict[str, Any], comps: dict[str, Any]) -> str:
    """Таблица полей модели или одна строка типа."""
    model = comps[_name(s["$ref"])] if "$ref" in s else s
    props = model.get("properties")
    if not props:
        return f"<p>Тип: {_type(s)}</p>"
    required = set(model.get("required", []))
    rows = "".join(
        f"<tr><td><code>{escape(k)}</code></td><td>{_type(v)}</td><td>{'да' if k in required else ''}</td>"
        f"<td>{escape(json.dumps(v['default'], ensure_ascii=False)) if 'default' in v else ''}</td></tr>"
        for k, v in props.items()
    )
    return (
        "<table><thead><tr><th>Поле</th><th>Тип</th><th>Обязательно</th><th>По умолчанию</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _ru(response: dict[str, Any]) -> str:
    text = str(response.get("description", ""))
    return RU.get(text, text)


def _operation(path: str, method: str, op: dict[str, Any], comps: dict[str, Any]) -> str:
    anchor = "op-" + method + "-" + re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    out = [
        f'<h3 id="{anchor}"><span class="method {method}">{method.upper()}</span> '
        f"<code>{escape(path)}</code></h3>",
        f"<p><strong>{escape(op.get('summary', ''))}</strong></p>",
    ]
    if op.get("description"):
        out.append(f"<p>{escape(op['description'])}</p>")
    params = op.get("parameters", [])
    if params:
        rows = "".join(
            f"<tr><td><code>{escape(p['name'])}</code></td>"
            f"<td>{'путь' if p['in'] == 'path' else 'запрос'}</td>"
            f"<td>{_type(p.get('schema', {}))}</td><td>{'да' if p.get('required') else ''}</td></tr>"
            for p in params
        )
        out.append(
            "<h4>Параметры</h4><table><thead><tr><th>Имя</th><th>Где</th><th>Тип</th><th>Обязательно</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    if body:
        sample = json.dumps(_example(body, comps), ensure_ascii=False, indent=2)
        out += ["<h4>Тело запроса</h4>", _fields(body, comps), f"<pre><code>{escape(sample)}</code></pre>"]
    curl = f"curl -X {method.upper()} http://127.0.0.1:8000{path}"
    if body:
        curl += " \\\n  -H 'Content-Type: application/json' -d @body.json"
    out.append(f'<pre class="curl"><code>{escape(curl)}</code></pre>')
    rows = "".join(
        f"<tr><td><code>{escape(code)}</code></td><td>{escape(_ru(r))}</td>"
        f"<td>{_type(r.get('content', {}).get('application/json', {}).get('schema', {}))}</td></tr>"
        for code, r in op.get("responses", {}).items()
    )
    out.append(
        f"<h4>Ответы</h4><table><thead><tr><th>Код</th><th>Что значит</th><th>Тело</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return "\n".join(out)


@lru_cache(maxsize=8)
def _reference(app: FastAPI) -> str:
    """Справочник из живой схемы: группы, операции, параметры, тела, ответы, схемы данных."""
    schema = app.openapi()
    comps = schema.get("components", {}).get("schemas", {})
    groups: dict[str, list[str]] = {}
    for path, item in schema["paths"].items():
        for method, op in item.items():
            key = (op.get("tags") or [path.removeprefix("/api/").split("/")[0]])[0]
            groups.setdefault(GROUPS.get(key, key), []).append(_operation(path, method, op, comps))
    out = [
        f'<h2 id="{slugify_unicode(g, "-")}">{escape(g)}</h2>\n' + "\n".join(ops) for g, ops in groups.items()
    ]
    out.append('<h2 id="schemas">Схемы данных</h2>')
    out += [f'<h3 id="schema-{escape(n)}">{escape(n)}</h3>{_fields(s, comps)}' for n, s in comps.items()]
    return "\n".join(out)


# --- страницы ---


def _body(slug: str, app: FastAPI) -> tuple[str, str]:
    if slug not in PAGES:
        raise NotFound(f"Страницы документации {slug} нет")
    title, body = _page(slug)
    return title, body + _reference(app) if slug == API_PAGE else body


def _render(slug: str, app: FastAPI) -> str:
    title, body = _body(slug, app)
    slugs = list(PAGES)
    nav = "".join(
        f'<a href="{s}"{" aria-current=page" if s == slug else ""}>{escape(_page(s)[0])}</a>' for s in slugs
    )
    toc = "".join(
        f'<a class="l{level}" href="#{anchor}">{escape(_text(name))}</a>'
        for level, anchor, name in HEADING.findall(body)
    )
    i = slugs.index(slug)
    pager = "".join(
        f'<a class="{cls}" href="{slugs[j]}"><small>{label}</small>{escape(_page(slugs[j])[0])}</a>'
        for cls, label, j in (("prev", "Назад", i - 1), ("next", "Далее", i + 1))
        if 0 <= j < len(slugs)
    )
    return LAYOUT.substitute(title=escape(title), nav=nav, body=body, toc=toc, pager=pager)


@router.get("/docs")
async def docs_root() -> RedirectResponse:
    return RedirectResponse("docs/")  # относительные ссылки страниц считаются от /docs/


@router.get("/docs/", response_class=HTMLResponse)
async def docs_index(request: Request) -> str:
    return _render(next(iter(PAGES)), request.app)


@router.get("/docs/search.json")
async def docs_search(request: Request) -> list[dict[str, str]]:
    """Индекс поиска по разделам H2; строится при запросе из страниц в памяти."""
    index = []
    for slug in PAGES:
        title, body = _body(slug, request.app)
        intro, *rest = H2.split(body)
        index.append({"url": slug, "title": title, "text": _text(intro)})
        for head, part in zip(rest[::2], rest[1::2], strict=True):
            anchor = re.search(r'id="([^"]+)"', head)
            index.append(
                {
                    "url": f"{slug}#{anchor.group(1) if anchor else ''}",
                    "title": f"{title}: {_text(head)}",
                    "text": _text(part),
                }
            )
    return index


@router.get("/docs/{slug}", response_class=HTMLResponse)
async def docs_page(slug: str, request: Request) -> str:
    return _render(slug, request.app)
