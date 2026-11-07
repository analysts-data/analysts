"""Клиент API организаторов: подстановка group_id и один GET без утечки адреса."""

import pytest

from cqa.adapters.org_api import FETCH_TIMEOUT_S, group_url

TEMPLATE = "https://org.test/api/dialogs?group_id=DEV&token=t"


def test_group_url_replaces_value_and_keeps_other_params() -> None:
    assert group_url(TEMPLATE, "CTRL1") == "https://org.test/api/dialogs?group_id=CTRL1&token=t"


def test_group_url_appends_missing_param() -> None:
    assert group_url("https://org.test/api/dialogs?token=t", "DEV") == (
        "https://org.test/api/dialogs?token=t&group_id=DEV"
    )


def test_group_url_accepts_boundary_group_ids() -> None:
    assert group_url("https://org.test/api", "a" * 64).endswith("group_id=" + "a" * 64)
    assert group_url("https://org.test/api", "A-b_0") == "https://org.test/api?group_id=A-b_0"


@pytest.mark.parametrize("bad", ["../etc", "", " ", "a" * 65, "группа", "DEV 1", "a/b"])
def test_group_url_rejects_bad_group_id(bad: str) -> None:
    with pytest.raises(ValueError, match="group_id"):
        group_url(TEMPLATE, bad)


def test_fetch_timeout_is_thirty_seconds() -> None:
    assert FETCH_TIMEOUT_S == 30.0
