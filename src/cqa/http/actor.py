"""Текущий сотрудник из заголовка `X-CQA-User: <id>`. Пароля нет: в продукте личность — SSO / Dynamics."""

from fastapi import Request

from cqa.services.audit import ANONYMOUS, Actor

HEADER = "X-CQA-User"


def actor_from(request: Request, sign: str = "") -> Actor:
    """Активный сотрудник заголовка; иначе без входа — подпись роли `sign` из тела запроса, как раньше."""
    user = request.headers.get(HEADER, "").strip()
    found = request.app.state.store.employee(user) if user else None
    if found is None or not found["active"]:
        return Actor(None, sign.strip() or ANONYMOUS)
    return Actor(found["id"], found["name"], found["role"])


def signed(actor: Actor, sign: str) -> str:
    """Подпись в записи (`by`, `reviewer`): имя вошедшего сотрудника, без входа — подпись из тела."""
    return actor.name if actor.id else sign
