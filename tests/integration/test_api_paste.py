"""POST /api/dialogs/text: диалог из вставленного текста сохраняется, оценка не запускается."""

import pytest
from fastapi.testclient import TestClient

from cqa.adapters.store import Store
from cqa.domain.models import Dialog
from fakes import FakeEvaluator

TEXT = "Клиент: Здравствуйте, хочу карту\nОператор: Добрый день! Как вас зовут?"


def paste(client: TestClient, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"title": "Демо из буфера", "ch": "chat", "text": TEXT}
    body.update(overrides)
    return client.post("/api/dialogs/text", json=body).json()  # type: ignore[no-any-return]


def state_dialog(client: TestClient, dialog_id: str) -> Dialog:
    return next(d for d in client.get("/api/state").json()["dialogs"] if d["id"] == dialog_id)


def test_pasted_dialog_is_saved_and_waits_for_evaluation(
    client: TestClient, evaluator: FakeEvaluator
) -> None:
    response = client.post("/api/dialogs/text", json={"title": "Демо из буфера", "ch": "chat", "text": TEXT})
    assert (response.status_code, response.json()) == (200, {"id": "paste-1"})
    dialog = state_dialog(client, "paste-1")
    assert (dialog["title"], dialog["ch"], dialog["lang"]) == ("Демо из буфера", "chat", "RU")
    assert [line["who"] for line in dialog["lines"]] == ["client", "operator"]
    assert dialog["res"] == {}  # оценка сама не запускается
    assert evaluator.calls == 0


def test_id_avoids_collision_with_saved_dialogs(
    client: TestClient, store: Store, dialogs: list[Dialog]
) -> None:
    taken = dialogs[0].model_copy(update={"id": "paste-1"})
    assert store.add_dialogs([taken], {}) == (1, 0)
    assert paste(client) == {"id": "paste-2"}


def test_dialog_without_operator_line_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/dialogs/text",
        json={"title": "Без оператора", "ch": "chat", "text": "Клиент: один на свете"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "в диалоге нет реплики оператора"


@pytest.mark.parametrize("body", [{}, {"title": "т", "ch": "sms", "text": TEXT}])
def test_body_out_of_contract_is_422(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/api/dialogs/text", json=body).status_code == 422
