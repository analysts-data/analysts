"""scripts/results.py: make results SET=dev|prod пишет results/<набор>/results.json (группа 9)."""

import importlib.util
import json
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import respx

from cqa.adapters.store import Store, connect
from cqa.domain.review import fingerprint
from cqa.services.answers import set_answer
from fakes import FakeEvaluator, prototype_checklist, prototype_dialogs

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "results.py"
IDS = [d.id for d in prototype_dialogs()]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("results_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


results = load()


def envelope(path: Path, ids: Sequence[str]) -> Path:
    records = [{"conversation_id": i, "channel": "chat", "language": "ru", "transcript": []} for i in ids]
    data = {"dataset_group_id": path.stem, "total_records": len(records), "records": records}
    path.write_text(json.dumps({"error": None, "isSuccess": True, "data": data}), encoding="utf-8")
    return path


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """База с прототипом: чек-лист v3, десять диалогов и их ответы от модели qwen3-6."""
    db = tmp_path / "cqa.db"
    conn = connect(str(db))
    store = Store(conn)
    checklist = prototype_checklist()
    store.add_checklist(checklist, "начальная версия")
    dialogs = prototype_dialogs()
    store.add_dialogs(dialogs, {})
    for d in dialogs:
        for c in checklist.criteria:
            r = d.res[c.id].model_copy(update={"model": "qwen3-6", "alt": None})
            store.add_result(d.id, c.id, checklist.version, fingerprint(checklist, c, d.ch), r)
    conn.close()
    for key in ("CQA_LLM_MODEL", "CQA_VERIFIER"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CQA_DB_PATH", str(db))
    monkeypatch.setenv("CQA_DATA_WHERE", "kz")
    monkeypatch.setenv("CQA_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("CQA_EVAL_DATASET", str(envelope(tmp_path / "dev.json", [*IDS, "ghost-1"])))
    return tmp_path


def test_dev_export_writes_one_utf8_record_per_snapshot_dialog(base: Path) -> None:
    out = base / "out" / "results.json"

    assert results.main(["dev", "--out", str(out)]) == 0

    text = out.read_text(encoding="utf-8")
    doc = json.loads(text)
    assert text.startswith('{\n  "schema_version": "1.0"')
    assert "Оператор" in text  # ensure_ascii=False
    assert [r["conversation_id"] for r in doc["results"]] == [*IDS, "ghost-1"]
    assert [r["status"] for r in doc["results"]].count("error") == 1
    assert doc["model"] == {"mode": "external_api", "name": "qwen3-6"}
    assert doc["team_name"] == "analysts"


def test_prod_reads_group_snapshot_and_takes_overrides(base: Path) -> None:
    (base / "raw").mkdir()
    envelope(base / "raw" / "CTRL-1.json", IDS)  # снимок, который сервер пишет при «Получить набор»
    out = base / "prod.json"

    code = results.main(
        ["prod", "--group", "CTRL-1", "--out", str(out), "--team", "Команда", "--mode", "hybrid",
         "--model-name", "qwen3-6, jev-latest"]
    )  # fmt: skip

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert len(doc["results"]) == 10
    assert doc["team_name"] == "Команда"
    assert doc["model"] == {"mode": "hybrid", "name": "qwen3-6, jev-latest"}


def test_several_snapshots_join_in_order_without_repeats(base: Path) -> None:
    (base / "raw").mkdir()
    envelope(base / "raw" / "CHATS.json", IDS[:7])
    envelope(base / "raw" / "CALLS.json", IDS[5:])
    out = base / "dev.json"

    assert results.main(["dev", "--group", "CHATS", "--group", "CALLS", "--out", str(out)]) == 0

    assert [r["conversation_id"] for r in json.loads(out.read_text(encoding="utf-8"))["results"]] == IDS


def test_manual_answer_is_the_exported_answer_and_not_a_model_name(base: Path) -> None:
    conn = connect(str(base / "cqa.db"))
    set_answer(Store(conn), dlg=IDS[0], cid="01", a="no", reason="Не поздоровался", by="Анна")
    conn.close()
    out = base / "out.json"

    assert results.main(["dev", "--out", str(out)]) == 0

    doc = json.loads(out.read_text(encoding="utf-8"))
    first = next(c for c in doc["results"][0]["criteria"] if c["criterion_id"] == "contact")
    assert (first["value"], first["rationale"]) == (False, "Не поздоровался")
    assert doc["model"]["name"] == "qwen3-6"


def test_prod_without_exactly_ten_records_fails_loudly_but_keeps_the_file(
    base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = base / "prod.json"

    code = results.main(["prod", "--source", str(envelope(base / "nine.json", IDS[:9])), "--out", str(out)])

    assert code == 1
    assert out.exists()
    assert "ровно 10" in capsys.readouterr().err


def test_prod_needs_a_group_or_source(base: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        results.main(["prod", "--out", str(base / "prod.json")])
    assert exc.value.code == 2
    assert not (base / "prod.json").exists()


def test_model_name_lists_every_model_that_answered_and_the_second_opinion() -> None:
    dialogs = prototype_dialogs()
    first = dialogs[0].res["01"].model_copy(update={"model": "glm-4.5-flash"})
    dialogs[0] = dialogs[0].model_copy(update={"res": {**dialogs[0].res, "01": first}})
    for d in dialogs:
        d.res.update({cid: r.model_copy(update={"model": r.model or "qwen3-6"}) for cid, r in d.res.items()})

    assert results.model_names(dialogs) == "glm-4.5-flash, qwen3-6, jev-latest"  # alt есть у прототипа


ORG_PAYLOAD = Path(__file__).resolve().parents[1] / "fixtures" / "org_payload.json"
SYN = [r["conversation_id"] for r in json.loads(ORG_PAYLOAD.read_bytes())["data"]["records"]]
ORG_API = "https://org.test/api/dialogs"


@pytest.fixture
def empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """База после первого запуска сервера: только чек-лист, диалогов нет."""
    db = tmp_path / "cqa.db"
    conn = connect(str(db))
    Store(conn).add_checklist(prototype_checklist(), "начальная версия")
    conn.close()
    monkeypatch.setenv("CQA_DB_PATH", str(db))
    monkeypatch.setenv("CQA_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("CQA_ORG_API_URL", f"{ORG_API}?group_id=DEV&token=t")
    return tmp_path


def fake_model(monkeypatch: pytest.MonkeyPatch, evaluator: FakeEvaluator) -> None:
    monkeypatch.setattr(results, "build_evaluator", lambda settings: evaluator)


def test_evaluate_loads_the_file_evaluates_missing_pairs_and_exports_them(
    empty: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evaluator = FakeEvaluator(fail_on=[SYN[0]])
    fake_model(monkeypatch, evaluator)
    out = empty / "dev.json"
    args = ["dev", "--source", str(ORG_PAYLOAD), "--evaluate", "--model-name", "fake", "--out", str(out)]

    assert results.main(args) == 0

    printed = capsys.readouterr().out
    total = len(SYN) * len(prototype_checklist().criteria)
    assert f"оценка {total}/{total}, ошибок 1" in printed
    assert f"{SYN[0]}: timeout" in printed
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [r["conversation_id"] for r in doc["results"]] == SYN
    assert [r["status"] for r in doc["results"]] == ["error", *["ok"] * (len(SYN) - 1)]
    assert sorted(evaluator.order) == sorted(SYN)

    again = FakeEvaluator()
    fake_model(monkeypatch, again)
    assert results.main(args) == 0
    assert again.order == [SYN[0]]  # готовые ответы не пересчитываются


@respx.mock
def test_evaluate_fetches_the_group_and_exports_from_its_snapshot(
    empty: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = respx.get(ORG_API).mock(return_value=httpx.Response(200, content=ORG_PAYLOAD.read_bytes()))
    fake_model(monkeypatch, FakeEvaluator())
    out = empty / "dev.json"

    code = results.main(["dev", "--group", "CTRL1", "--evaluate", "--model-name", "fake", "--out", str(out)])

    assert code == 0
    assert str(route.calls.last.request.url) == f"{ORG_API}?group_id=CTRL1&token=t"
    assert (empty / "raw" / "CTRL1.json").read_bytes() == ORG_PAYLOAD.read_bytes()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [(r["conversation_id"], r["status"]) for r in doc["results"]] == [(i, "ok") for i in SYN]


@respx.mock
def test_evaluate_stops_before_the_model_when_the_set_does_not_load(
    empty: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get(ORG_API).mock(return_value=httpx.Response(500))
    evaluator = FakeEvaluator()
    fake_model(monkeypatch, evaluator)

    code = results.main(["prod", "--group", "CTRL1", "--evaluate", "--out", str(empty / "prod.json")])

    assert code == 2
    assert evaluator.calls == 0
    assert "статусом 500" in capsys.readouterr().err
    assert not (empty / "prod.json").exists()


def test_make_target_passes_set_and_group() -> None:
    makefile = (SCRIPT.parents[1] / "Makefile").read_text(encoding="utf-8")

    assert "uv run python scripts/results.py $(SET) $(foreach g,$(GROUP),--group $(g)) $(ARGS)" in makefile
