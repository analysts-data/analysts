import json
from pathlib import Path
from typing import Any

import pytest
import respx
from pydantic import SecretStr

from cqa import compose
from cqa.adapters.cassette import CassetteMissing, _key
from cqa.adapters.jev import JEV_URL, JevVerifier
from cqa.adapters.llm import PROFILES
from cqa.adapters.store import Store, connect
from cqa.compose import build_evaluator, build_routed
from cqa.domain.models import Checklist, Dialog
from cqa.domain.prompt import build_messages, render_dialog
from cqa.http.app import create_app
from cqa.services.errors import ConfigError
from cqa.services.llm_config import effective
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
    messages = build_messages(render_dialog(CHAT), CHECKLIST.rules, FIRST, CHAT.ch)[0]
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
        ({"llm_mode": "live", "llm_api_key": SecretStr("k"), "verifier": "jev"}, "CQA_JEV_API_KEY"),
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


def test_jev_verifier_is_built_on_request_without_key_in_replay() -> None:
    evaluator = build_evaluator(settings(verifier="jev"))
    assert isinstance(evaluator.verifier, JevVerifier)
    assert evaluator.config_error is None


async def test_scenario_5_calls_deepseek_with_thinking_and_jev_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "CASSETTES", tmp_path)
    s = settings(
        llm_mode="live", llm_api_key=SecretStr("k"), llm_profile="deepseek", verifier="jev",
        jev_api_key=SecretStr("j"), llm_price_in=0.435, llm_price_out=0.87,
    )  # fmt: skip
    answer = {"reason_ru": "Поздоровался и представился.", "answer": "yes"}
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    with respx.mock(assert_all_called=True) as net:
        llm = net.post("https://llm.test/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": json.dumps(answer)}}], "usage": usage}
        )
        jev = net.post(JEV_URL).respond(
            200,
            json={
                "answers": {"q0": {"type": "choice", "choice": "no", "confidence": 0.8, "probabilities": {}}},
                "usage": {"input_tokens": 1000},
            },
        )
        out = await build_evaluator(s).evaluate(CHAT, CHECKLIST, [FIRST])
    [e] = out.results
    assert (e.result.a, e.result.alt, e.result.calls) == ("yes", "no", 1)
    assert e.result.cost == pytest.approx((1000 * 0.435 + 100 * 0.87) / 1e6)
    assert (out.verifier_calls, out.verifier_usd) == (1, pytest.approx(1000 * 0.042 / 1e6))
    assert json.loads(llm.calls.last.request.content)["thinking"] == {"type": "enabled"}
    assert jev.calls.last.request.headers["authorization"] == "Bearer j"
    assert not list(tmp_path.rglob("*.json"))  # live пишет записи только в record


async def test_second_opinion_from_a_provider_asks_its_own_model_with_its_own_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "CASSETTES", tmp_path)
    s = effective(
        settings(llm_mode="live", llm_api_key=SecretStr("k")),
        {
            "providers": {
                "ds": {"label": "DS", "base_url": "https://ds.test", "model": "ds-pro", "profile": "plain",
                       "where": "external", "key": "sk-ds"},
            },
            "verifier": "ds",
        },
    )  # fmt: skip
    main = {"reason_ru": "Поздоровался и представился.", "answer": "yes"}
    second = {"reason_ru": "Не представился.", "answer": "no"}
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    with respx.mock(assert_all_called=True) as net:
        net.post("https://llm.test/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": json.dumps(main)}}], "usage": usage}
        )
        ds = net.post("https://ds.test/chat/completions").respond(
            200, json={"choices": [{"message": {"content": json.dumps(second)}}], "usage": usage}
        )
        out = await build_evaluator(s).evaluate(CHAT, CHECKLIST, [FIRST])
    [e] = out.results
    assert (e.result.a, e.result.alt, out.verifier_calls) == ("yes", "no", 1)
    assert json.loads(ds.calls.last.request.content)["model"] == "ds-pro"
    assert ds.calls.last.request.headers["authorization"] == "Bearer sk-ds"


def test_jev_only_evaluator_is_built_without_llm_key_and_needs_jev_key_in_live() -> None:
    from cqa.services.evaluation import JevEvaluator

    evaluator = build_evaluator(settings(evaluator="jev", llm_mode="live", jev_api_key=SecretStr("j")))
    assert isinstance(evaluator, JevEvaluator)
    assert (evaluator.config_error, evaluator.model_name, evaluator.sends_real_data) == (
        None,
        "jev-latest",
        True,
    )
    assert build_evaluator(settings(evaluator="jev")).config_error is None  # replay: ключ не нужен


async def test_jev_only_without_key_in_live_fails_at_evaluate() -> None:
    evaluator = build_evaluator(settings(evaluator="jev", llm_mode="live"))
    with respx.mock(assert_all_called=False) as net, pytest.raises(ConfigError, match="CQA_JEV_API_KEY"):
        await evaluator.evaluate(CHAT, CHECKLIST, [FIRST])
    assert net.calls.call_count == 0


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@pytest.mark.parametrize("role", ["llm_provider", "verifier"])
async def test_jev_through_openrouter_works_as_main_model_and_as_second_opinion(
    role: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "CASSETTES", tmp_path)
    s = effective(
        settings(llm_mode="live", llm_api_key=SecretStr("k"), openrouter_api_key=SecretStr("sk-or")),
        {role: "openrouter-jev"},
    )
    main = {"reason_ru": "Поздоровался и представился.", "answer": "yes"}
    second = {"reason_ru": "Не представился.", "answer": "no"}
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "cost": 0.003}
    with respx.mock(assert_all_called=False) as net:
        net.post("https://llm.test/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": json.dumps(second)}}], "usage": usage}
        )
        router = net.post(OPENROUTER_URL).respond(
            200, json={"choices": [{"message": {"content": json.dumps(main)}}], "usage": usage}
        )
        out = await build_evaluator(s).evaluate(CHAT, CHECKLIST, [FIRST])
    [e] = out.results
    sent = router.calls.last.request
    assert json.loads(sent.content)["model"] == "typesafe/jev-router"
    assert (sent.headers["authorization"], sent.headers["x-title"]) == ("Bearer sk-or", "CQA")
    if role == "llm_provider":
        assert (e.result.a, e.result.why, e.result.model, e.result.cost) == (
            "yes", "Поздоровался и представился.", "typesafe/jev-router", 0.003
        )  # fmt: skip
        assert evaluator_mode(s) == "external"
    else:
        assert (e.result.a, e.result.alt, out.verifier_calls, out.verifier_usd) == ("no", "yes", 1, 0.003)


def evaluator_mode(s: Settings) -> str:
    from cqa.services.state import mode_from_settings

    return mode_from_settings(s).where


@pytest.mark.parametrize("mode", ["llm", "jev"])
def test_evaluator_gets_the_sound_analysis_port(mode: str) -> None:
    async def prosody(dialog_id: str) -> dict[str, Any]:
        return {"summary": []}

    assert build_evaluator(settings(evaluator=mode), prosody).prosody is prosody
    assert build_evaluator(settings(evaluator=mode)).prosody is None


def _cassette(tmp_path: Path, model: str, profile: str = "plain") -> None:
    """Запись ответа «yes» на первый критерий CHAT для модели `model`."""
    messages = build_messages(render_dialog(CHAT), CHECKLIST.rules, FIRST, CHAT.ch)[0]
    body = {"model": model, "messages": messages} | PROFILES[profile]["on"]
    response = {"choices": [{"message": {"content": json.dumps({"reason_ru": "Да.", "answer": "yes"})}}]}
    (tmp_path / "llm").mkdir(exist_ok=True)
    record = {"request": body, "status": 200, "response": response | {"usage": {}}}
    (tmp_path / "llm" / f"{_key(body)}.json").write_text(json.dumps(record), encoding="utf-8")


async def test_without_enabled_rules_routing_is_the_plain_evaluator_with_the_same_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "CASSETTES", tmp_path)
    _cassette(tmp_path, settings().llm_model)
    store = Store(connect(":memory:"))
    for s in (settings(), settings(routing=[{"id": "calls", "name": "Звонки", "enabled": False}])):
        evaluator = build_routed(s, None, store)  # демонстрационные правила выключены
        assert type(evaluator) is type(build_evaluator(s))
        with respx.mock(assert_all_called=False) as net:
            out = await evaluator.evaluate(CHAT, CHECKLIST, [FIRST])
        assert net.calls.call_count == 0
        assert [(e.result.a, e.result.rule_id) for e in out.results] == [("yes", None)]
