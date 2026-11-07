from cqa.domain.audio_timeline import audio_starts
from cqa.domain.events import classify_event

BASE = 1_793_516_400.0  # секунды POSIX: формула работает с разностями меток
TEXT_29 = "Добрый день, чем могу помочь?"
REC = "Запись и транскрибирование запущены"
PAUSE = "Запись и транскрибирование приостановлены"
RESUME = "Запись и транскрибирование возобновлены"


def starts(
    lines: list[tuple[float, str, str]], *, shift_s: float = 0.3, shift_paused_s: float = 4.5
) -> list[float | None]:
    ends = [BASE + at for at, _, _ in lines]
    who = [w for _, w, _ in lines]
    texts = [t for _, _, t in lines]
    kinds = [classify_event(t) if w in ("system", "bot") else None for _, w, t in lines]
    return audio_starts(ends, texts, who, kinds, shift_s=shift_s, shift_paused_s=shift_paused_s)


def test_start_is_end_minus_text_duration_plus_shift() -> None:
    lines = [
        (0, "system", REC),
        (1, "operator", TEXT_29),
        (10, "operator", TEXT_29),
        (12, "client", "Да."),
        (20, "system", "Клиент завершил разговор"),
    ]
    assert len(TEXT_29) == 29
    assert starts(lines) == [0.3, 0.0, 8.3, 11.7, 20.3]


def test_lines_before_recording_start_have_no_start() -> None:
    lines = [(0, "bot", "Здравствуйте!"), (4, "client", "Алло"), (6, "bot", "Соединяю"), (8, "system", REC)]
    assert starts([*lines, (18, "operator", TEXT_29)]) == [None, None, None, 0.3, 8.3]


def test_kazakh_recording_start_event_counts() -> None:
    lines = [(0, "bot", "Сәлеметсіз бе!"), (8, "system", "Жазу және транскрипция басталды")]
    assert starts([*lines, (18, "operator", TEXT_29)]) == [None, 0.3, 8.3]


def test_without_start_event_recording_starts_at_first_line() -> None:
    result = starts([(0, "bot", "Здравствуйте!"), (10, "operator", TEXT_29)])
    assert result[0] is not None
    assert result[1] == 8.3


def test_closed_pause_is_subtracted_and_paused_shift_applies_to_whole_call() -> None:
    lines = [
        (0, "system", REC),
        (20, "operator", TEXT_29),
        (30, "system", PAUSE),
        (40, "client", "Да."),
        (45, "system", RESUME),
        (60, "client", TEXT_29),
    ]
    result = starts(lines)
    assert result[1] == 22.5
    assert result[3] is None
    assert result[5] == 47.5


def test_unclosed_pause_lasts_until_the_end() -> None:
    lines = [(0, "system", REC), (10, "operator", TEXT_29), (20, "system", PAUSE), (30, "client", "Да.")]
    assert starts(lines) == [4.5, 12.5, 24.5, None]
