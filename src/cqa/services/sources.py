"""Реестр источников диалогов (GET/POST /api/sources …): настройка, приём webhook, учёт и здоровье.

Секреты (ссылка API организаторов, значение заголовка авторизации, токен webhook) только записываются:
в ответах есть `has_secret`, сам секрет — нет. Токен webhook показывается один раз при создании.
"""

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from cqa.adapters.store import Store
from cqa.domain.ingest import ingest_records
from cqa.domain.models import Dialog, IngestResult
from cqa.domain.sources import (
    BUILTIN,
    PULL,
    WINDOW,
    health,
    key_paths,
    map_records,
    org_url_error,
    per_source,
    records_at,
    validate,
)
from cqa.services.datasets import logged
from cqa.services.errors import Conflict, Invalid, NotFound, Unauthorized
from cqa.services.state import current_state
from cqa.settings import Settings

PUBLIC: Final = (
    "id",
    "name",
    "kind",
    "service",
    "channel_default",
    "product_default",
    "config",
    "enabled",
    "schedule_min",
    "created",
    "archived",
)
MAX_PUSH_BYTES: Final = 10_000_000
SIGNATURE: Final = "X-CQA-Signature"  # sha256=<hex HMAC-SHA256 тела по токену>


def view(src: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: src[k] for k in PUBLIC}
    out["has_secret"] = bool(src["secret"])
    out["ingest_path"] = f"/api/sources/{src['id']}/ingest" if src["kind"] == "webhook" else None
    return out


def list_sources(store: Store) -> list[dict[str, Any]]:
    return [view(s) for s in store.sources()]


def get_source(store: Store, source_id: str) -> dict[str, Any]:
    src = store.source(source_id)
    if src is None:
        raise NotFound(f"Источник {source_id} не найден")
    return src


def check(body: Mapping[str, Any], *, saved_secret: str | None) -> None:
    """Поля формы источника; 422 с `fields` — по каждому неверному полю."""
    kind, config, secret = body["kind"], body.get("config") or {}, body.get("secret") or ""
    errors = validate(kind, config) if kind not in BUILTIN else {}
    if not str(body.get("name") or "").strip() or len(body["name"]) > 80:
        errors["name"] = "название от 1 до 80 знаков"
    if not 0 <= int(body.get("schedule_min") or 0) <= 1440:
        errors["schedule_min"] = "от 0 (только вручную) до 1440 минут"
    if kind == "org_api":
        if secret and (msg := org_url_error(secret.strip())):
            errors["secret"] = msg
        elif body.get("enabled") and not (secret or saved_secret):
            errors["secret"] = "нужна ссылка API организаторов (https://…), без неё источник выключен"
    if kind == "http_json" and config.get("auth_header") and not (secret or saved_secret):
        errors["secret"] = "укажите значение заголовка авторизации"
    if errors:
        raise Invalid("Проверьте поля источника", errors)


def _row(body: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "name": body["name"].strip(),
        "kind": body["kind"],
        "service": (body.get("service") or "").strip(),
        "channel_default": body.get("channel_default"),
        "product_default": (body.get("product_default") or "").strip() or None,
        "config": dict(body.get("config") or {}),
        "enabled": bool(body.get("enabled", True)),
        "schedule_min": int(body.get("schedule_min") or 0),
        **extra,
    }


def create_source(store: Store, body: Mapping[str, Any]) -> dict[str, Any]:
    """Новый источник `src<n>`; у webhook ответ один раз содержит `token`."""
    if body["kind"] in BUILTIN:
        raise Invalid("Проверьте поля источника", {"kind": "встроенные источники создаются сами"})
    check(body, saved_secret=None)
    taken = {s["id"] for s in store.sources()}
    source_id = next(f"src{n}" for n in range(1, len(taken) + 2) if f"src{n}" not in taken)
    token = secrets.token_urlsafe(24) if body["kind"] == "webhook" else None
    secret = token or (body.get("secret") or "").strip() or None
    store.put_source(_row(body, id=source_id, secret=secret, archived=False))
    out = view(get_source(store, source_id))
    return {**out, "token": token} if token else out


def update_source(store: Store, source_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """Пустой `secret` оставляет сохранённый; `rotate_token` выдаёт webhook новый токен (один раз)."""
    src = get_source(store, source_id)
    if body["kind"] != src["kind"]:
        raise Invalid("Проверьте поля источника", {"kind": "вид источника не меняется"})
    if src["kind"] in BUILTIN:
        body = {**body, "config": {}, "enabled": True, "schedule_min": 0}
    check(body, saved_secret=src["secret"])
    token = secrets.token_urlsafe(24) if src["kind"] == "webhook" and body.get("rotate_token") else None
    secret = token or (body.get("secret") or "").strip() or src["secret"]
    store.put_source(_row(body, id=source_id, secret=secret, created=src["created"], archived=src["archived"]))
    out = view(get_source(store, source_id))
    return {**out, "token": token} if token else out


def delete_source(store: Store, source_id: str, *, archive: bool) -> dict[str, Any]:
    """Удалить источник без диалогов; с диалогами — только в архив (учёт и диалоги остаются)."""
    src = get_source(store, source_id)
    if src["kind"] in BUILTIN or source_id == "org":
        raise Conflict("Встроенный источник нельзя удалить, его можно выключить")
    n = store.source_dialogs().get(source_id, (0, None))[0]
    if archive:
        store.put_source({**src, "enabled": False, "archived": True})
        return {"archived": source_id}
    if n:
        raise Conflict(f"У источника {n} диалогов: удалить нельзя, отправьте его в архив (archive=true)")
    store.delete_source(source_id)
    return {"deleted": source_id}


def source_syncs(store: Store, source_id: str, limit: int = 50) -> list[dict[str, Any]]:
    get_source(store, source_id)
    return store.syncs(source_id, limit)


def _age_s(iso: str | None, now: datetime) -> float | None:
    return None if iso is None else round((now - datetime.fromisoformat(iso)).total_seconds())


def source_stats(store: Store, now: datetime) -> list[dict[str, Any]]:
    """Учёт по источникам: диалоги, оценки, итог, грубые ошибки, синхронизации, свежесть, здоровье."""
    checklist, dialogs, appeals = current_state(store)
    scored = per_source(checklist, dialogs, appeals)
    counts = store.source_dialogs()
    out = []
    for src in store.sources():
        sid = src["id"]
        syncs = store.syncs(sid, WINDOW + 1)
        running = syncs[0] if syncs and syncs[0]["status"] == "running" else None
        done = [s for s in syncs if s["status"] != "running"][:WINDOW]
        last = done[0] if done else None
        n, newest = counts.get(sid, (0, None))
        freshness = _age_s(newest, now)
        error_rate = round(sum(s["status"] == "error" for s in done) / len(done), 4) if done else None
        status, basis = health(
            kind=src["kind"],
            enabled=src["enabled"],
            last=last,
            error_rate=error_rate,
            freshness_s=freshness,
            dialogs=n,
        )
        out.append(
            {
                "id": sid,
                "name": src["name"],
                "kind": src["kind"],
                "enabled": src["enabled"],
                "archived": src["archived"],
                **scored.get(sid, {"dialogs": n, "scored": 0, "avg_total": None, "gross_share": None}),
                "running": running,
                "last_sync": last,
                "syncs": len(done),
                "error_rate": error_rate,
                "newest_at": newest,
                "freshness_s": freshness,
                "health": status,
                "basis": basis,
            }
        )
    return out


# --- сопоставление чужого JSON ---


def extract(src: Mapping[str, Any], body: Any) -> list[Any]:
    """Записи по `records_path`; пустой путь и объект в теле — одна запись (webhook на каждый диалог)."""
    path = src["config"].get("records_path") or ""
    records = records_at(body, path)
    if records is None and not path and isinstance(body, dict):
        return [body]
    if records is None:
        keys = ", ".join(list(body)[:8]) if isinstance(body, dict) else type(body).__name__
        raise Invalid(f"по пути «{path or '(тело)'}» нет списка записей; верхний уровень: {keys}")
    return records


def build(
    src: Mapping[str, Any], records: list[Any], settings: Settings, now: datetime
) -> tuple[IngestResult, list[dict[str, Any]]]:
    """Записи источника → диалоги с `source_id`, `external_id`, `product` и сопоставленные записи."""
    mapped, errors = map_records(
        records,
        src["config"]["mapping"],
        prefix=f"{src['id']}-",
        channel_default=src.get("channel_default"),
        product_default=src.get("product_default"),
    )
    result, _warnings = ingest_records(
        mapped,
        group_id=src["id"],
        now=now,
        shift_s=settings.audio_shift_s,
        shift_paused_s=settings.audio_shift_paused_s,
    )
    by_id = {m["conversation_id"]: m for m in mapped}
    dialogs = [
        d.model_copy(
            update={
                "source_id": src["id"],
                "external_id": by_id[d.id]["external_id"],
                "product": by_id[d.id]["product"],
                "title": ("Звонок " if d.ch == "call" else "Чат ") + by_id[d.id]["external_id"],
            }
        )
        for d in result.dialogs
    ]
    errs = errors + result.errors
    return IngestResult(dialogs, result.audio, len(errs), errs), mapped


def preview(
    records: list[Any], result: IngestResult, mapped: list[dict[str, Any]], *, ms: int
) -> dict[str, Any]:
    """Ответ «Проверить»: первые 3 диалога, ошибки разбора, пути полей первой записи для сопоставления."""
    by_id = {m["conversation_id"]: m for m in mapped}

    def item(d: Dialog) -> dict[str, Any]:
        lines = [x for x in d.lines or [] if not hasattr(x, "fold")]
        m = by_id.get(d.id, {})
        return {
            "id": d.id,
            "external_id": d.external_id or d.id,
            "title": d.title,
            "ch": d.ch,
            "lang": d.lang,
            "lines": len(lines),
            "operator": m.get("operator"),
            "product": d.product,
            "sample": [{"who": x.who, "text": x.text[:200]} for x in lines[:3]],  # type: ignore[union-attr]
        }

    first = records[0] if records else None
    return {
        "ok": True,
        "error": None,
        "ms": ms,
        "records": len(records),
        "preview": [item(d) for d in result.dialogs[:3]],
        "errors": result.errors[:10],
        "paths": key_paths(first),
    }


def failed(error: str, ms: int) -> dict[str, Any]:
    return {"ok": False, "error": error, "ms": ms, "records": 0, "preview": [], "errors": [], "paths": []}


# --- webhook ---


def _authorized(src: Mapping[str, Any], raw: bytes, headers: Mapping[str, str]) -> bool:
    token = src["secret"] or ""
    if not token:
        return False
    if src["config"].get("auth", "bearer") == "hmac":
        sent = headers.get(SIGNATURE.lower(), "").removeprefix("sha256=")
        expected = hmac.new(token.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sent.encode(), expected.encode())
    sent = headers.get("authorization", "").removeprefix("Bearer ").strip()
    return hmac.compare_digest(sent.encode(), token.encode())


def ingest_push(
    store: Store, settings: Settings, source_id: str, raw: bytes, headers: Mapping[str, str], now: datetime
) -> dict[str, Any]:
    """POST /api/sources/{id}/ingest: сначала токен, затем состояние и тело; поступление — в журнал."""
    src = store.source(source_id)
    if src is None or src["kind"] != "webhook":
        raise NotFound(f"Источник {source_id} не найден")
    if not _authorized(src, raw, headers):
        raise Unauthorized("Неверный токен источника")
    if not src["enabled"]:
        raise Conflict("Источник выключен: данные не принимаются")
    if len(raw) > MAX_PUSH_BYTES:
        raise Invalid(f"Тело больше {MAX_PUSH_BYTES // 1_000_000} МБ: отправляйте частями")
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise Invalid("Тело не JSON") from None
    with logged(store, source_id) as save:
        result, _ = build(src, extract(src, body), settings, now)
        counts = save(result)
    return {**counts, "errors": result.errors[:20]}
