"""Правила обработки из интерфейса: разные модели и настройки для звонков, чатов, языков, продуктов.

Правила хранятся в базе (`overrides["routing"]`) поверх `CQA_ROUTING`, как режим оценки. Пока их не
сохраняли, список — демонстрационные правила, выключенные. Без включённых правил оценщик тот же, что
был: `compose.build_routed` возвращает `build_evaluator` без обёртки.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from typing import Any

from pydantic import TypeAdapter, ValidationError

from cqa.adapters.store import Store
from cqa.domain.models import Checklist, Criterion, Dialog, DialogEvaluation, Line
from cqa.domain.routing import DEFAULT, Facts, Match, Rule, Use, conditions, first_match, matches
from cqa.services.errors import ConfigError, Invalid, NotFound
from cqa.services.llm_config import Apply, as_llm, config_error
from cqa.services.ports import Evaluator
from cqa.services.state import mode_from_settings
from cqa.settings import Settings

_RULES = TypeAdapter(list[Rule])
DEFAULT_RULE = Rule(
    id=DEFAULT,
    name="По умолчанию — общий режим",
    why="Всё, что не подошло правилам выше, оценивается по «Режиму оценки»: основная модель, второе "
    "мнение и обезличивание задаются там.",
)
# Демонстрационные правила, выключены. Порядок важен: первое подходящее правило выигрывает, поэтому
# короткие чаты стоят раньше всех чатов, а казахский язык — раньше деления по каналу.
SEEDS: list[dict[str, Any]] = [
    {
        "id": "short-chats",
        "name": "Короткие чаты (<4 реплик) → только Jev",
        "enabled": False,
        "why": "В чате из двух-трёх реплик почти нечего обосновывать: Jev отвечает на все критерии одним "
        "быстрым запросом, дешевле и без очереди к основной модели.",
        "match": {"ch": "chat", "max_lines": 3},
        "use": {"evaluator": "jev"},
    },
    {
        "id": "kazakh",
        "name": "Казахский → основная модель + второе мнение Jev",
        "enabled": False,
        "why": "На казахском модели ошибаются чаще, чем на русском: второе мнение Jev отмечает расхождения, "
        "и специалист КК проверяет их первыми.",
        "match": {"lang": ["KZ"]},
        "use": {"verifier": "jev"},
    },
    {
        "id": "calls",
        "name": "Звонки → основная модель + интонация",
        "enabled": False,
        "why": "На звонке важны паузы, перебивания и тон: модель получает разбор записи вместе "
        "с расшифровкой.",
        "match": {"ch": "call"},
        "use": {"prosody": True},
    },
    {
        "id": "chats",
        "name": "Чаты → основная модель",
        "enabled": False,
        "why": "Чат оценивает основная модель с обоснованием по каждому критерию; в карточке видно, что "
        "диалог прошёл по ветке чатов.",
        "match": {"ch": "chat"},
        "use": {},
    },
]
_RU = {  # сообщения pydantic по-русски; остальное — как есть
    "missing": "обязательное поле",
    "extra_forbidden": "неизвестное поле",
    "string_pattern_mismatch": "код правила — строчная латиница, цифры и дефис, до 32 знаков",
    "string_too_short": "не может быть пустым",
    "string_type": "нужна строка",
    "bool_type": "нужно true или false",
    "bool_parsing": "нужно true или false",
    "int_type": "нужно целое число",
    "int_parsing": "нужно целое число",
    "greater_than_equal": "не меньше {ge}",
    "greater_than": "больше {gt}",
    "list_type": "нужен список",
    "model_type": "нужен объект",
    "model_attributes_type": "нужен объект",
    "literal_error": "допустимо: {expected}",
}


def facts(store: Store, dialog: Dialog) -> Facts:
    return Facts(
        ch=dialog.ch,
        lang=dialog.lang,
        source_id=getattr(dialog, "source_id", None),  # Dialog.source_id и product добавляют соседние ветки
        product=getattr(dialog, "product", None),
        lines=sum(isinstance(x, Line) and x.who != "system" for x in dialog.lines or []),
        has_audio=store.audio_url(dialog.id) is not None,
    )


def _jev_usable(settings: Settings) -> bool:
    return settings.llm_mode == "replay" or settings.jev_api_key is not None


def rules(settings: Settings) -> list[Rule]:
    """Сохранённые правила (или демонстрационные) и правило по умолчанию последним."""
    if settings.routing is not None:
        return [*_RULES.validate_python(settings.routing), DEFAULT_RULE]
    jev = _jev_usable(settings)
    seeds = [s for s in SEEDS if jev or "jev" not in (s["use"].get("evaluator"), s["use"].get("verifier"))]
    return [*_RULES.validate_python(seeds), DEFAULT_RULE]


def _dump(rule: Rule) -> dict[str, Any]:
    """`use` без незаданных полей: явный `verifier: null` (без второго мнения) отличается от «как в общем»."""
    return {
        **rule.model_dump(mode="json", exclude={"match", "use"}),
        "match": rule.match.model_dump(mode="json", exclude_none=True),
        "use": rule.use.model_dump(mode="json", exclude_unset=True),
    }


def view(settings: Settings) -> list[dict[str, Any]]:
    """`GET /api/routing`: правила по порядку, `default` последним."""
    return [_dump(r) for r in rules(settings)]


def rule_settings(settings: Settings, use: Use) -> Settings:
    """Общий режим с действиями правила поверх. Обезличивание правило может только включить."""
    update = {k: v for k, v in use.model_dump(exclude_unset=True).items() if v is not None or k == "verifier"}
    update.pop("prosody", None)  # не настройка Settings: build_routed передаёт или не передаёт порт
    if "max_parallel" in update:  # одновременные запросы к модели правила
        update["llm_max_parallel"] = update.pop("max_parallel")
    if "anonymize" in update:
        update["anonymize"] = settings.anonymize or update["anonymize"]
    if "llm_provider" in update:
        found = settings.providers.get(update["llm_provider"])
        if found is None:
            raise Invalid(f"нет провайдера «{update['llm_provider']}»")
        update |= as_llm(found)
    return settings.model_copy(update=update)


def _at(i: int, name: object) -> str:
    return f"правило {i + 1}" + (f" «{name}»" if isinstance(name, str) and name else "") + " → "


def _parse(body: Any) -> list[Rule]:
    try:
        return _RULES.validate_python(body)
    except ValidationError as exc:
        out = []
        for e in exc.errors():
            loc = e["loc"]
            if not loc or not isinstance(loc[0], int):
                out.append("нужен список правил")
                continue
            raw = body[loc[0]]
            msg = _RU.get(e["type"], e["msg"]).format(**e.get("ctx", {})).replace(" or ", " или ")
            out.append(
                f"{_at(loc[0], raw.get('name') if isinstance(raw, dict) else None)}"
                f"{'.'.join(map(str, loc[1:]))}: {msg}"
            )
        raise Invalid("\n".join(out)) from None


def _use_errors(settings: Settings, use: Use) -> list[str]:
    out = []
    for field in ("llm_provider", "verifier"):
        pid = getattr(use, field)
        if pid is not None and pid not in settings.providers and not (field == "verifier" and pid == "jev"):
            out.append(f"use.{field}: нет провайдера «{pid}»")
    if use.anonymize is False and settings.anonymize:
        out.append(
            "use.anonymize: обезличивание включено в «Режиме оценки»; правило может только включить его, "
            "но не выключить — иначе имена и номера ушли бы модели без маскировки"
        )
    if out:
        return out
    error = config_error(rule_settings(settings, use))  # Jev без ключа, нет ключа провайдера и т. п.
    return [f"use: {error}"] if error else []


def _check(settings: Settings, found: Sequence[Rule]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    for i, r in enumerate(found):
        at = _at(i, r.name)
        if r.id in seen:
            errors.append(f"{at}id: код «{r.id}» уже есть у правила {seen[r.id] + 1}")
        seen.setdefault(r.id, i)
        if r.id == DEFAULT:
            if r.match != Match() or r.use != Use() or not r.enabled:
                errors.append(
                    f"{at}правило по умолчанию — это «Режим оценки»: меняйте модель и настройки там"
                )
            continue
        if (
            r.match.min_lines is not None
            and r.match.max_lines is not None
            and r.match.min_lines > r.match.max_lines
        ):
            errors.append(f"{at}match: min_lines больше max_lines — правило не подойдёт ни одному диалогу")
        if r.enabled:  # выключенное правило можно сохранить недоделанным
            errors += [at + e for e in _use_errors(settings, r.use)]
    return errors


def put_routing(store: Store, settings: Settings, body: Any, apply: Apply) -> Settings:
    """Проверить, применить (`apply` пересобирает оценщик, во время запуска — `Conflict`), сохранить.

    `default` в теле можно передать как есть: он не хранится и всегда стоит последним.
    """
    found = _parse(body)
    errors = _check(settings, found)
    if errors:
        raise Invalid("\n".join(errors))
    stored = [_dump(r) for r in found if r.id != DEFAULT]
    candidate = settings.model_copy(update={"routing": stored})
    apply(candidate)
    store.set_overrides({"routing": stored})
    return candidate


def explain(store: Store, settings: Settings, dialog_id: str) -> dict[str, Any]:
    """`POST /api/routing/explain`: какое правило возьмёт диалог и почему — каждое условие каждого правила."""
    dialog = store.get_dialog(dialog_id)
    if dialog is None:
        raise NotFound(f"Диалог {dialog_id} не найден")
    f = facts(store, dialog)
    found = rules(settings)
    chosen = first_match(found, f)
    s = rule_settings(settings, chosen.use)
    return {
        "dialog_id": dialog_id,
        "facts": asdict(f),
        "rule": {"id": chosen.id, "name": chosen.name},
        "use": {
            **mode_from_settings(s).model_dump(mode="json"),
            "evaluator": s.evaluator,
            "prosody": chosen.use.prosody is not False,
            "max_parallel": s.llm_max_parallel,
        },
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "enabled": r.enabled,
                "matched": matches(r, f),
                "chosen": r is chosen,
                "conditions": [asdict(c) for c in conditions(r, f)],
            }
            for r in found
        ],
    }


class RoutedEvaluator:
    """`Evaluator` по правилам: диалог оценивает оценщик первого подходящего правила, ответы получают
    `rule_id` и `rule_name`. Правило по умолчанию — общий оценщик, ответы без пометки, как раньше.

    `evaluators`: id правила → оценщик или текст ошибки сборки (провайдер правила удалён) — тогда
    падают только диалоги этого правила, как при ошибке конфигурации.
    """

    def __init__(
        self,
        found: list[Rule],
        default: Evaluator,
        evaluators: Mapping[str, Evaluator | str],
        facts: Callable[[Dialog], Facts],
    ) -> None:
        self._rules = found
        self._default = default
        self._evaluators = evaluators
        self._facts = facts

    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation:
        rule = first_match(self._rules, self._facts(dialog))
        if rule.id == DEFAULT:
            return await self._default.evaluate(dialog, checklist, criteria)
        evaluator = self._evaluators[rule.id]
        if isinstance(evaluator, str):
            raise ConfigError(f"Правило «{rule.name}»: {evaluator}")
        out = await evaluator.evaluate(dialog, checklist, criteria)
        mark = {"rule_id": rule.id, "rule_name": rule.name}
        return replace(
            out, results=[replace(e, result=e.result.model_copy(update=mark)) for e in out.results]
        )
