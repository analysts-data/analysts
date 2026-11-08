"""Достаточность данных: исходы правил из базы поверх умолчаний, оценка диалогов (/api/sufficiency)."""

from collections.abc import Mapping, Sequence
from typing import Any, cast, get_args

from cqa.adapters.store import Store
from cqa.domain.models import Dialog, Outcome, Sufficiency
from cqa.domain.sufficiency import RULES, assess
from cqa.services.errors import Invalid


def assess_dialogs(store: Store, dialogs: Sequence[Dialog]) -> dict[str, Sufficiency]:
    """id диалога → достаточность при текущих исходах правил; считается при каждом чтении, не хранится."""
    outcomes, audio = store.sufficiency_outcomes(), store.audio_ids()
    return {d.id: assess(d, has_audio=d.id in audio, outcomes=outcomes) for d in dialogs}


def view(store: Store) -> dict[str, Any]:
    outcomes = store.sufficiency_outcomes()
    return {
        "rules": [
            {
                "id": r.id,
                "text": r.text,
                "why": r.why,
                "default": r.default,
                "outcome": outcomes.get(r.id, r.default),
            }
            for r in RULES
        ]
    }


def configure(store: Store, body: Mapping[str, str]) -> dict[str, Any]:
    """Исходы части правил: `{"<id правила>": "block" | "flag" | "info"}`; неизвестное — Invalid целиком."""
    known = {r.id for r in RULES}
    if unknown := sorted(set(body) - known):
        raise Invalid(f"Нет правил достаточности: {', '.join(unknown)}")
    if bad := sorted(k for k, v in body.items() if v not in get_args(Outcome)):
        raise Invalid(f"Исход правила — block, flag или info: {', '.join(bad)}")
    store.set_sufficiency_outcomes(cast("dict[str, Outcome]", dict(body)))
    return view(store)
