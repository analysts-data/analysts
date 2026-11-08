"""Источники диалогов: виды, проверка настроек, сопоставление полей чужого JSON, правила здоровья.

Чистое ядро без ввода-вывода. Запись внешнего сервиса превращается в запись формата организаторов
(`OrgRecord`), дальше работает общая загрузка `ingest_records`.
"""

import ipaddress
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal
from urllib.parse import parse_qsl, urlsplit

from cqa.domain.models import Appeal, Checklist, Dialog
from cqa.domain.paste import ROLES, detect_lang
from cqa.domain.review import effective_answer
from cqa.domain.scoring import r2, total

Kind = Literal["org_api", "http_json", "webhook", "file", "paste", "api"]
PULL: Final = frozenset({"org_api", "http_json"})  # сервер забирает сам, по расписанию или кнопкой
BUILTIN: Final = frozenset({"file", "paste", "api"})  # встроенные: файл, вставка текста, интеграционный API
Health = Literal["ok", "warning", "error"]

MAPPING_FIELDS: Final = (
    "conversation_id",
    "channel",
    "language",
    "transcript",
    "speaker",
    "text",
    "timestamp",
    "audio_url",
    "operator",
    "product",
)
REQUIRED: Final = ("conversation_id", "transcript", "speaker", "text")
TURN_FIELDS: Final = frozenset({"speaker", "text", "timestamp"})  # пути внутри реплики transcript

FRESH_S: Final = 24 * 3600  # «нет новых данных 24 ч»
ERROR_RATE: Final = 0.2  # доля синхронизаций с ошибкой среди последних WINDOW
WINDOW: Final = 10

SPEAKERS: Final[dict[str, str]] = {
    **ROLES,
    "agent": "operator",
    "employee": "operator",
    "support": "operator",
    "user": "client",
    "abonent": "client",
    "абонент": "client",
}
_CHANNELS: Final = {
    "chat": "agent chat",
    "agent chat": "agent chat",
    "messenger": "agent chat",
    "чат": "agent chat",
    "call": "voice call",
    "voice": "voice call",
    "voice call": "voice call",
    "phone": "voice call",
    "звонок": "voice call",
}
_PATH_RE: Final = re.compile(r"^[^.\s]+(\.[^.\s]+)*$")
_GROUP_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HEADER_RE: Final = re.compile(r"^[A-Za-z0-9-]{1,64}$")
# параметры адреса, похожие на секрет: такой адрес попал бы в ответы и журнал, ключ — в заголовок
_SECRET_PARAM_RE: Final = re.compile(r"token|key|secret|sig|signature|password|passwd|auth", re.I)


def _norm(path: str) -> str:
    return path.strip().removeprefix("$").removeprefix(".")


def get_path(obj: Any, path: str) -> Any:
    """Значение по пути `a.b.0.c`; пустой путь — сам объект; нет такого — `None`."""
    path = _norm(path)
    if not path:
        return obj
    for seg in path.split("."):
        if isinstance(obj, Mapping):
            obj = obj.get(seg)
        elif isinstance(obj, list) and seg.isdigit() and int(seg) < len(obj):
            obj = obj[int(seg)]
        else:
            return None
    return obj


def records_at(body: Any, path: str) -> list[Any] | None:
    """Список записей по пути `records_path`; не список — `None`."""
    found = get_path(body, path)
    return found if isinstance(found, list) else None


def key_paths(obj: Any, depth: int = 3, prefix: str = "") -> list[str]:
    """Пути полей записи для подсказки сопоставления: вложенные объекты раскрываются, списки — нет."""
    if not isinstance(obj, Mapping) or depth == 0:
        return []
    out: list[str] = []
    for k, v in obj.items():
        path = f"{prefix}{k}"
        nested = key_paths(v, depth - 1, f"{path}.") if isinstance(v, Mapping) else []
        out += nested or [path]
    return out


def _text(v: Any) -> str | None:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v).strip()
    return s or None


def map_records(
    records: Sequence[Any],
    mapping: Mapping[str, Any],
    *,
    prefix: str,
    channel_default: str | None,
    product_default: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Записи чужого формата → записи организаторов и ошибки `<id>: <что не так>`.

    `conversation_id` получает `prefix` (id источника), исходный id — в `external_id`. Канал и роли
    приводятся по синонимам и `mapping["speakers"]`; нет языка — по тексту; нет времени — `MM:SS` по номеру.
    """
    speakers = {**SPEAKERS, **{str(k).casefold(): v for k, v in (mapping.get("speakers") or {}).items()}}
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw in records:
        ext = _text(get_path(raw, mapping["conversation_id"]))
        if ext is None:
            errors.append(f"?: нет conversation_id ({mapping['conversation_id']})")
            continue
        turns_raw = get_path(raw, mapping["transcript"])
        if not isinstance(turns_raw, list):
            errors.append(f"{ext}: transcript ({mapping['transcript']}) должен быть списком реплик")
            continue
        turns = []
        for i, t in enumerate(turns_raw):
            who = _text(get_path(t, mapping["speaker"])) or "system"
            ts = _text(get_path(t, mapping["timestamp"])) if mapping.get("timestamp") else None
            turns.append(
                {
                    "speaker": speakers.get(who.casefold(), who),
                    "text": _text(get_path(t, mapping["text"])) or "",
                    "timestamp": ts or f"{i // 60:02d}:{i % 60:02d}",
                }
            )
        field = {k: _text(get_path(raw, p)) if p else None for k, p in mapping.items() if k in MAPPING_FIELDS}
        channel = field.get("channel") or channel_default or ""
        lang = field.get("language") or detect_lang(" ".join(t["text"] for t in turns))
        out.append(
            {
                "conversation_id": f"{prefix}{ext}",
                "external_id": ext,
                "channel": _CHANNELS.get(channel.casefold(), channel),
                "language": lang.lower(),
                "transcript": turns,
                "audio_url": field.get("audio_url"),
                "operator": field.get("operator"),
                "product": field.get("product") or product_default,
            }
        )
    return out, errors


def _url_error(url: Any, schemes: tuple[str, ...]) -> str | None:
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme not in schemes or not parts.hostname:
        return f"адрес должен начинаться с {' или '.join(s + '://' for s in schemes)}"
    if parts.username or parts.password:
        return "логин и пароль в адресе запрещены: ключ задаётся заголовком авторизации"
    if any(_SECRET_PARAM_RE.search(k) for k, _ in parse_qsl(parts.query)):
        return "ключ в адресе запрещён (адрес виден в интерфейсе): задайте его заголовком авторизации"
    return None


def _mapping_errors(mapping: Any) -> dict[str, str]:
    if not isinstance(mapping, Mapping):
        return {"config.mapping": "нужно сопоставление полей"}
    errors = {
        f"config.mapping.{f}": "обязательное поле: укажите путь в записи"
        for f in REQUIRED
        if not isinstance(mapping.get(f), str) or not mapping[f].strip()
    }
    for f in MAPPING_FIELDS:
        p = mapping.get(f)
        if f not in errors and p and (not isinstance(p, str) or not _PATH_RE.fullmatch(_norm(p))):
            errors[f"config.mapping.{f}"] = "путь вида data.items или agent.name"
    speakers = mapping.get("speakers") or {}
    if not isinstance(speakers, Mapping) or any(v not in ROLES.values() for v in speakers.values()):
        errors["config.mapping.speakers"] = "роли: client, operator, bot или system"
    return errors


def validate(kind: str, config: Mapping[str, Any]) -> dict[str, str]:
    """Ошибки настроек по полям (`config.url`, `config.mapping.text`, …); пусто — настройки верны."""
    errors: dict[str, str] = {}
    if kind == "org_api":
        if not _GROUP_RE.fullmatch(str(config.get("group_id") or "")):
            errors["config.group_id"] = "group_id: латиница, цифры, _ и -, до 64 знаков"
        return errors
    if kind not in ("http_json", "webhook"):
        return errors
    path = config.get("records_path") or ""
    if not isinstance(path, str) or (_norm(path) and not _PATH_RE.fullmatch(_norm(path))):
        errors["config.records_path"] = "путь к списку записей вида data.items; пусто — тело и есть список"
    errors |= _mapping_errors(config.get("mapping"))
    if kind == "webhook":
        if config.get("auth", "bearer") not in ("bearer", "hmac"):
            errors["config.auth"] = "bearer или hmac"
        return errors
    if msg := _url_error(config.get("url"), ("https", "http")):
        errors["config.url"] = msg
    if config.get("method", "GET") not in ("GET", "POST"):
        errors["config.method"] = "GET или POST"
    header = config.get("auth_header") or ""
    if not isinstance(header, str) or (header and not _HEADER_RE.fullmatch(header)):
        errors["config.auth_header"] = "имя заголовка: латиница, цифры и дефис"
    return errors


def org_url_error(url: str) -> str | None:
    """Ссылка API организаторов: только https (подписанная ссылка уходит по сети)."""
    parts = urlsplit(url)
    return (
        None
        if parts.scheme == "https" and parts.netloc
        else "Ссылка API организаторов должна начинаться с https://"
    )


def blocked_ip(ip: str) -> bool:
    """Адрес не в публичном интернете: частные сети, loopback, link-local (метаданные облака), служебные."""
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not addr.is_global or addr.is_multicast


def _records(n: int) -> str:
    tail = n % 100
    word = (
        "записей"
        if 11 <= tail <= 14
        else {1: "запись", 2: "записи", 3: "записи", 4: "записи"}.get(n % 10, "записей")
    )
    return f"{n} {word}"


def health(
    *,
    kind: str,
    enabled: bool,
    last: Mapping[str, Any] | None,
    error_rate: float | None,
    freshness_s: float | None,
    dialogs: int,
) -> tuple[Health, str]:
    """Здоровье источника и правило, которое его определило (`basis`), по порядку проверки."""
    if not enabled:
        return "warning", "источник выключен"
    if last is not None and last["status"] == "error":
        first = next(iter(last["errors"]), "причина не записана")
        return "error", f"последняя синхронизация с ошибкой: {first}"
    if error_rate is not None and error_rate > ERROR_RATE:
        return "warning", f"{round(error_rate * 100)}% синхронизаций с ошибкой (последние {WINDOW})"
    if last is not None and last["status"] == "partial":
        return (
            "warning",
            f"последняя синхронизация с пропусками: {_records(len(last['errors']))} не разобраны",
        )
    if kind in BUILTIN:
        return "ok", "загрузка вручную" if not dialogs else "ошибок нет"
    if kind in PULL and last is None:
        return "warning", "ещё не синхронизировался"
    if freshness_s is None:
        return "warning", "данные ещё не поступали"
    if freshness_s > FRESH_S:
        return "warning", "нет новых данных 24 ч"
    if kind in PULL:
        return "ok", "последняя синхронизация успешна, данные свежие"
    return "ok", "данные поступают"


def per_source(
    checklist: Checklist, dialogs: Sequence[Dialog], appeals: Sequence[Appeal]
) -> dict[str, dict[str, Any]]:
    """По источнику: диалогов, оценено, средний итог и доля с грубой ошибкой — с учётом решений."""
    flags = {c.id for c in checklist.criteria if c.type == "flag"}
    acc: dict[str, tuple[int, list[float], int]] = {}
    for d in dialogs:
        if d.source_id is None:
            continue
        n, totals, gross = acc.get(d.source_id, (0, [], 0))
        answers = {
            cid: effective_answer(r, [a for a in appeals if a.dlg == d.id and a.cid == cid])
            for cid, r in d.res.items()
        }
        t = total(checklist, answers)
        if t is not None:
            totals = [*totals, t]
            gross += any(isinstance(answers.get(f), dict) and any(answers[f].values()) for f in flags)  # type: ignore[union-attr]
        acc[d.source_id] = (n + 1, totals, gross)
    return {
        sid: {
            "dialogs": n,
            "scored": len(ts),
            "avg_total": r2(sum(ts) / len(ts)) if ts else None,
            "gross_share": round(g / len(ts), 4) if ts else None,
        }
        for sid, (n, ts, g) in acc.items()
    }
