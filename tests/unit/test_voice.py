"""Адаптер звука на синтетике: синус и глиссандо с известным тоном, громкостью и тишиной.

Настоящие записи звонков в тестах не используются.
"""

import io
import shutil
import subprocess
import wave

import httpx
import numpy as np
import pytest
import respx

from cqa.adapters.voice import RATE, PraatVoice, decode, tracks
from cqa.domain.models import Line
from cqa.domain.prosody import analyse

LINK = "https://storage.test/rec.mp3"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="нет ffmpeg")


def tone(hz: float, seconds: float, amp: float = 0.1, to_hz: float | None = None) -> np.ndarray:
    """Синус или глиссандо hz → to_hz (фаза — интеграл частоты)."""
    t = np.arange(int(seconds * RATE)) / RATE
    f = hz * ((to_hz or hz) / hz) ** (t / seconds)
    return amp * np.sin(2 * np.pi * np.cumsum(f) / RATE)


def hush(seconds: float) -> np.ndarray:
    return np.random.default_rng(0).normal(0, 1e-4, int(seconds * RATE))  # шум линии, не цифровой ноль


def voiced(samples: np.ndarray) -> np.ndarray:
    tr = tracks(samples)
    return tr.f0[tr.f0 > 0]


def mp3(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((samples * 32767).astype("<i2").tobytes())
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-f", "wav", "-i", "pipe:0", "-f", "mp3", "pipe:1"]
    return subprocess.run(cmd, input=buf.getvalue(), capture_output=True, check=True).stdout


def test_pitch_of_a_sine_is_its_frequency() -> None:
    assert np.median(voiced(tone(200, 1.0))) == pytest.approx(200, abs=2)


def test_silence_has_no_pitch() -> None:
    assert len(voiced(hush(1.0))) == 0


def test_double_amplitude_is_six_db_louder() -> None:
    tr = tracks(np.concatenate([tone(150, 1.0, amp=0.1), tone(150, 1.0, amp=0.2)]))
    quiet = tr.db[(tr.int_t > 0.2) & (tr.int_t < 0.8)].mean()
    loud = tr.db[(tr.int_t > 1.2) & (tr.int_t < 1.8)].mean()
    assert loud - quiet == pytest.approx(6.0, abs=0.5)


@needs_ffmpeg
def test_decode_turns_mp3_into_mono_16k_samples() -> None:
    samples = decode(mp3(tone(440, 1.0)))

    assert len(samples) == pytest.approx(RATE, rel=0.1)
    assert np.median(voiced(samples)) == pytest.approx(440, abs=4)


@needs_ffmpeg
def test_decode_of_garbage_raises() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        decode(b"not audio at all")


def test_synthetic_call_flags_raised_client_line_and_long_pause() -> None:
    """Оператор 120 Гц, клиент 200 Гц; реплика 6 клиента на 5 полутонов выше и втрое громче,
    перед репликой 7 оператор молчит 7 с. Реплика — 5 слов, по расшифровке 2 с."""
    text = " ".join(["слово"] * 5)
    parts, lines, at = [hush(1.0)], [], 1.0
    for n in range(1, 11):
        who = "operator" if n % 2 else "client"
        hz = 120.0 if who == "operator" else 200.0
        amp = 0.1
        if n == 6:
            hz, amp = hz * 2 ** (5 / 12), 0.3
        gap = 7.0 if n == 7 else 1.0
        if n > 1:
            parts.append(hush(gap))
            at += gap
        lines.append(Line(n=n, t=at, who=who, text=text, s=at, seg="conv"))
        parts.append(tone(hz / 1.12, 2.0, amp, to_hz=hz * 1.12))
        at += 2.0
    parts.append(hush(1.0))

    result = analyse(lines, tracks(np.concatenate(parts)))
    flags = {x["n"]: x["flags"] for x in result["lines"]}

    assert flags[6] == ["raised"]
    assert flags[7] == ["long_pause"]
    assert all(f == [] for n, f in flags.items() if n not in (6, 7))
    assert result["summary"] == [
        "Клиент повысил тон в реплике 6",
        "Пауза 7 с перед ответом оператора (реплика 7)",
    ]


@needs_ffmpeg
@respx.mock
async def test_voice_downloads_and_analyses_the_record() -> None:
    respx.get(LINK).mock(return_value=httpx.Response(200, content=mp3(tone(300, 1.0))))
    tr = await PraatVoice(httpx.AsyncClient()).tracks(LINK)

    assert tr is not None
    assert np.median(tr.f0[tr.f0 > 0]) == pytest.approx(300, abs=3)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(403, text="expired"), httpx.Response(200, content=b"<html>not audio</html>")],
)
@respx.mock
async def test_voice_returns_none_when_the_record_is_unavailable(response: httpx.Response) -> None:
    respx.get(LINK).mock(return_value=response)
    assert await PraatVoice(httpx.AsyncClient()).tracks(LINK) is None


@respx.mock
async def test_voice_returns_none_on_network_error() -> None:
    respx.get(LINK).mock(side_effect=httpx.ConnectTimeout("timed out"))
    assert await PraatVoice(httpx.AsyncClient()).tracks(LINK) is None
