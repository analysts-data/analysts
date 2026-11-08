"""Ответ 422 на тело или параметры: путь поля, сообщение по-русски и ожидаемый формат.

`detail` — строка, как у ошибок сервисов: интерфейс показывает её как есть.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cqa.http.integration import FORMATS, EvaluateBatchIn, RecordIn, TextIn, TurnIn

MESSAGES = {
    "missing": "обязательное поле",
    "string_type": "нужна строка",
    "int_type": "нужно целое число",
    "int_parsing": "нужно целое число",
    "float_type": "нужно число",
    "float_parsing": "нужно число",
    "bool_type": "нужно true или false",
    "bool_parsing": "нужно true или false",
    "list_type": "нужен массив",
    "dict_type": "нужен объект",
    "model_attributes_type": "нужен объект",
    "literal_error": "недопустимое значение",
    "too_short": "слишком мало элементов",
    "too_long": "слишком много элементов",
    "string_too_short": "слишком короткая строка",
    "string_too_long": "слишком длинная строка",
    "json_invalid": "тело не JSON",
    "dialog_format": "тело не похоже ни на запись организаторов, ни на текст диалога",
}
TYPES = {
    "string": "строка",
    "int": "целое число",
    "float": "число",
    "bool": "true или false",
    "list": "массив",
}
BOTH_FORMATS = (
    "{conversation_id, channel, language, transcript: [{timestamp, speaker, text}]} или {text, ch, title}"
)
# описания полей интеграционных тел — они же в OpenAPI
HINTS: Mapping[str, str] = {
    name: f.description
    for m in (TurnIn, RecordIn, TextIn, EvaluateBatchIn)
    for name, f in m.model_fields.items()
    if f.description
}


def _expected(error: Mapping[str, Any], field: str) -> str:
    ctx = error.get("ctx") or {}
    if error["type"] == "dialog_format":
        return BOTH_FORMATS
    if "expected" in ctx:
        return str(ctx["expected"]).replace(" or ", " или ")
    if "min_length" in ctx and error["type"].endswith("too_short"):
        return f"не меньше {ctx['min_length']}"
    if "max_length" in ctx and error["type"].endswith("too_long"):
        return f"не больше {ctx['max_length']}"
    return HINTS.get(field) or TYPES.get(error["type"].split("_")[0], "см. схему в /api/openapi.json")


def field_errors(errors: Any) -> list[dict[str, str]]:
    out = []
    for e in errors:
        loc = [str(x) for x in e["loc"] if x not in FORMATS]
        loc = loc[1:] if loc and loc[0] == "body" else loc
        field = next((x for x in reversed(loc) if not x.isdigit()), "")
        out.append(
            {
                "path": ".".join(loc),
                "message": MESSAGES.get(e["type"], e["msg"]),
                "expected": _expected(e, field),
            }
        )
    return out


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = field_errors(exc.errors())
    brief = "; ".join(f"{e['path'] or 'тело'} — {e['message']}" for e in errors[:3])
    return JSONResponse({"detail": f"Запрос не прошёл проверку: {brief}", "errors": errors}, status_code=422)
