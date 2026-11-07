import json
from pathlib import Path
from typing import Any

import pytest
import respx
from pydantic import SecretStr

from cqa import compose
from cqa.adapters.cassette import CassetteMissing, _key
from cqa.adapters.llm import PROFILES
from cqa.compose import build_evaluator
from cqa.domain.models import Checklist, Dialog
from cqa.domain.prompt import build_messages, render_dialog
from cqa.http.app import create_app
from cqa.services.errors import ConfigError
from cqa.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CHECKLIST = Checklist.model_validate_json((FIXTURES / "checklist_v3.json").read_text(encoding="utf-8"))
CHAT = next(
    Dialog.model_validate(d)
    for d in json.loads((FIXTURES / "dialogs_prototype.json").read_text(encoding="utf-8"))
    if d["id"] == "p1-ru-022"
)
FIRST = CHECKLIST.criteria[0]


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"_env_file": None, "anonymize": False, "llm_base_url": "https://llm.test/v1"}
    return Settings(**(base | kw))


async def test_replay_answers_from_cassette_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings()
    messages = build_messages(render_dialog(CHAT), CHECKLIST.rules, FIRST)[0]
    body = {"model": s.llm_model, "messages": messages} | PROFILES[s.llm_profile][s.llm_reasoning]
    answer = {"reason_ru": "Поздоровался и представился.", "answer": "yes"}
    record = {
        "request": body,
        "status": 200,
        "response": {"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {}},
    }
    (tmp_path / "llm").mkdir()
    (tmp_path / "llm" / f"{_key(body)}.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(compose, "CASSETTES", tmp_path)
    with respx.mock(assert_all_called=False) as net:
        out = await build_evaluator(s).evaluate(CHAT, CHECKLIST, [FIRST])
    assert net.calls.call_count == 0
    assert [(e.cid, e.result.a, e.result.calls) for e in out.results] == [(FIRST.id, "yes", 1)]


async def test_replay_without_cassette_never_reaches_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "CASSETTES", tmp_path)
    with respx.mock(assert_all_called=False) as net, pytest.raises(CassetteMissing):
        await build_evaluator(settings()).evaluate(CHAT, CHECKLIST, [FIRST])
    assert net.calls.call_count == 0


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"llm_mode": "live"}, "CQA_LLM_API_KEY"),
        ({"llm_mode": "record"}, "CQA_LLM_API_KEY"),
        ({"llm_mode": "live", "llm_api_key": SecretStr("k"), "llm_base_url": None}, "CQA_LLM_BASE_URL"),
        ({"llm_profile": "nope"}, "nope"),
        ({"verifier": "jev"}, "CQA_VERIFIER"),
    ],
)
async def test_config_errors_surface_at_evaluate_not_at_build(kw: dict[str, Any], message: str) -> None:
    evaluator = build_evaluator(settings(**kw))  # building never raises
    with respx.mock(assert_all_called=False) as net, pytest.raises(ConfigError, match=message):
        await evaluator.evaluate(CHAT, CHECKLIST, [FIRST])
    assert net.calls.call_count == 0


@pytest.mark.parametrize(("mode", "real"), [("replay", False), ("record", False), ("live", True)])
def test_only_live_mode_sends_real_data(mode: str, real: bool) -> None:
    evaluator = build_evaluator(settings(llm_mode=mode, llm_api_key=SecretStr("k"), anonymize=True))
    assert (evaluator.sends_real_data, evaluator.anonymize, evaluator.verifier) == (real, True, None)


def test_create_app_builds_the_evaluator_when_none_is_given() -> None:
    app = create_app(settings(db_path=":memory:"))
    assert app.state.runner is not None
