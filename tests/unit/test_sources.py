"""Источники диалогов: сопоставление полей, проверка настроек, правила здоровья (чистый домен)."""

from datetime import UTC, datetime

from cqa.domain.ingest import ingest_records
from cqa.domain.models import CriterionResult, Dialog
from cqa.domain.sources import (
    blocked_ip,
    health,
    key_paths,
    map_records,
    per_source,
    records_at,
    validate,
)
from fakes import prototype_checklist

MAPPING = {
    "conversation_id": "id",
    "channel": "type",
    "transcript": "messages",
    "speaker": "from",
    "text": "body",
    "timestamp": "time",
    "operator": "agent.name",
}
RECORD = {
    "id": 1042,
    "type": "chat",
    "agent": {"name": "Алия К."},
    "messages": [
        {"from": "customer", "body": "Здравствуйте, не приходит код", "time": "00:01"},
        {"from": "agent", "body": "Добрый день! Проверю", "time": "00:30"},
    ],
}
NOW = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


def test_records_at_follows_a_dotted_path_and_list_indices() -> None:
    body = {"data": {"pages": [{"items": [1, 2]}]}}
    assert records_at(body, "data.pages.0.items") == [1, 2]
    assert records_at(body, "$.data.pages.0.items") == [1, 2]
    assert records_at([3], "") == [3]
    assert records_at(body, "data.missing") is None


def test_map_records_builds_org_shaped_records_namespaced_by_source() -> None:
    mapped, errors = map_records(
        [RECORD], MAPPING, prefix="src3-", channel_default=None, product_default="Карты"
    )
    assert errors == []
    (rec,) = mapped
    assert rec["conversation_id"] == "src3-1042"
    assert rec["external_id"] == "1042"
    assert rec["channel"] == "agent chat"
    assert rec["language"] == "ru"  # нет поля языка — по тексту
    assert rec["operator"] == "Алия К."
    assert rec["product"] == "Карты"
    assert [t["speaker"] for t in rec["transcript"]] == ["client", "operator"]
    dialogs = ingest_records(mapped, group_id="src3", now=NOW, shift_s=0, shift_paused_s=0)[0].dialogs
    assert dialogs[0].id == "src3-1042" and dialogs[0].ch == "chat"


def test_map_records_reports_a_broken_record_and_keeps_the_rest() -> None:
    broken = {"id": "7", "messages": "не список"}
    mapped, errors = map_records(
        [broken, RECORD], MAPPING, prefix="s-", channel_default="call", product_default=None
    )
    assert [r["external_id"] for r in mapped] == ["1042"]
    assert errors == ["7: transcript (messages) должен быть списком реплик"]


def test_map_records_uses_channel_default_and_custom_speakers() -> None:
    rec = {"id": "c1", "messages": [{"from": "A", "body": "Алло", "time": "2026-11-08T09:00:00+05:00"}]}
    mapped, _ = map_records(
        [rec],
        {**MAPPING, "speakers": {"A": "operator"}},
        prefix="",
        channel_default="call",
        product_default=None,
    )
    assert mapped[0]["channel"] == "voice call"
    assert mapped[0]["transcript"][0]["speaker"] == "operator"


def test_map_records_numbers_turns_without_timestamps() -> None:
    mapping = {k: v for k, v in MAPPING.items() if k != "timestamp"}
    mapped, _ = map_records([RECORD], mapping, prefix="", channel_default=None, product_default=None)
    assert [t["timestamp"] for t in mapped[0]["transcript"]] == ["00:00", "00:01"]


def test_validate_reports_field_level_errors_for_http_json() -> None:
    errors = validate(
        "http_json",
        {
            "url": "ftp://chat.test/x?token=abc",
            "method": "DELETE",
            "records_path": "data..items",
            "mapping": {"conversation_id": "id"},
        },
    )
    assert set(errors) == {
        "config.url",
        "config.method",
        "config.records_path",
        "config.mapping.transcript",
        "config.mapping.speaker",
        "config.mapping.text",
    }


def test_validate_rejects_credentials_in_the_url() -> None:
    assert "config.url" in validate("http_json", {"url": "https://u:p@chat.test/x", "mapping": MAPPING})
    assert "config.url" in validate("http_json", {"url": "https://chat.test/x?api_key=1", "mapping": MAPPING})
    assert validate("http_json", {"url": "https://chat.test/x?page=1", "mapping": MAPPING}) == {}


def test_validate_webhook_needs_mapping_and_known_auth() -> None:
    assert set(validate("webhook", {"auth": "basic", "mapping": MAPPING})) == {"config.auth"}
    assert validate("webhook", {"mapping": MAPPING}) == {}


def test_validate_org_api_needs_a_group_id() -> None:
    assert set(validate("org_api", {"group_id": "bad id!"})) == {"config.group_id"}
    assert validate("org_api", {"group_id": "DEV"}) == {}


def test_blocked_ip_covers_private_loopback_link_local_and_mapped() -> None:
    for ip in (
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "192.168.1.5",
        "::1",
        "::ffff:127.0.0.1",
        "0.0.0.0",
    ):
        assert blocked_ip(ip), ip
    assert not blocked_ip("93.184.216.34")


def test_key_paths_lists_nested_fields_for_the_mapping_preview() -> None:
    assert key_paths(RECORD) == ["id", "type", "agent.name", "messages"]


def _health(**kw: object) -> tuple[str, str]:
    args: dict[str, object] = {
        "kind": "http_json",
        "enabled": True,
        "last": {"status": "ok", "errors": []},
        "error_rate": 0.0,
        "freshness_s": 60.0,
        "dialogs": 3,
    }
    args.update(kw)
    return health(**args)  # type: ignore[arg-type]


def test_health_is_error_after_a_failed_sync() -> None:
    status, basis = _health(last={"status": "error", "errors": ["источник ответил статусом 500"]})
    assert status == "error"
    assert basis == "последняя синхронизация с ошибкой: источник ответил статусом 500"


def test_health_warns_on_partial_sync_high_error_rate_and_stale_data() -> None:
    assert _health(last={"status": "partial", "errors": ["a", "b"]}) == (
        "warning",
        "последняя синхронизация с пропусками: 2 записи не разобраны",
    )
    assert _health(error_rate=0.3) == ("warning", "30% синхронизаций с ошибкой (последние 10)")
    assert _health(freshness_s=25 * 3600) == ("warning", "нет новых данных 24 ч")
    assert _health(enabled=False) == ("warning", "источник выключен")
    assert _health(last=None) == ("warning", "ещё не синхронизировался")


def test_health_is_ok_for_a_fresh_source_and_for_manual_uploads() -> None:
    assert _health() == ("ok", "последняя синхронизация успешна, данные свежие")
    assert _health(kind="file", last=None, freshness_s=None, dialogs=0) == ("ok", "загрузка вручную")
    assert _health(kind="webhook", last=None, freshness_s=None, dialogs=0) == (
        "warning",
        "данные ещё не поступали",
    )


def test_per_source_counts_scored_average_and_gross_share() -> None:
    checklist = prototype_checklist()
    yes = {c.id: CriterionResult(a="yes") for c in checklist.criteria if c.type == "bool"}
    flag = next(c for c in checklist.criteria if c.type == "flag")
    gross = {flag.id: CriterionResult(a={q.k: True for q in flag.questions or []})}
    dialogs = [
        Dialog(id="a", ch="chat", lang="RU", at="", lines=[], res=yes, source_id="s1"),
        Dialog(id="b", ch="chat", lang="RU", at="", lines=[], res={**yes, **gross}, source_id="s1"),
        Dialog(id="c", ch="chat", lang="RU", at="", lines=[], source_id="s1"),
        Dialog(id="d", ch="chat", lang="RU", at="", lines=[], source_id="s2"),
    ]
    out = per_source(checklist, dialogs, [])
    assert out["s1"] == {"dialogs": 3, "scored": 2, "avg_total": 100.0, "gross_share": 0.5}
    assert out["s2"] == {"dialogs": 1, "scored": 0, "avg_total": None, "gross_share": None}
