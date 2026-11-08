"""Звук звонка: MP3 по свежей ссылке → моно 16 кГц (ffmpeg) → кадры F0 и интенсивности (Praat).

Запись скачивается в память, разбирается локально и нигде не сохраняется; в модели не уходит.
"""

import asyncio
import subprocess

import httpx
import numpy as np
import numpy.typing as npt
import parselmouth

from cqa.domain.prosody import Tracks

RATE = 16_000
STEP_S = 0.01
PITCH_FLOOR_HZ, PITCH_CEILING_HZ = 75.0, 500.0  # голос взрослого по телефону
FETCH_TIMEOUT_S = 60.0
DECODE_TIMEOUT_S = 120.0


def decode(data: bytes) -> npt.NDArray[np.float64]:
    """Что знает ffmpeg (MP3, WAV) → моно float 16 кГц; `CalledProcessError`, если не разобрал."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0"]
    cmd += ["-f", "f32le", "-ac", "1", "-ar", str(RATE), "pipe:1"]
    out = subprocess.run(cmd, input=data, capture_output=True, check=True, timeout=DECODE_TIMEOUT_S).stdout
    return np.frombuffer(out, dtype=np.float32).astype(np.float64)


def tracks(samples: npt.NDArray[np.float64], rate: int = RATE) -> Tracks:
    """Кадры по 10 мс: F0 автокорреляцией Praat (0 — тона нет) и интенсивность, дБ."""
    sound = parselmouth.Sound(samples, sampling_frequency=rate)
    pitch = sound.to_pitch(time_step=STEP_S, pitch_floor=PITCH_FLOOR_HZ, pitch_ceiling=PITCH_CEILING_HZ)
    intensity = sound.to_intensity(minimum_pitch=PITCH_FLOOR_HZ, time_step=STEP_S)
    return Tracks(
        pitch_t=pitch.xs(),
        f0=pitch.selected_array["frequency"],
        int_t=intensity.xs(),
        db=intensity.values[0],
    )


class PraatVoice:
    """Реализует `Voice`: один GET записи, разбор в отдельном потоке — цикл событий не ждёт."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def tracks(self, link: str) -> Tracks | None:
        try:
            response = await self._http.get(link, timeout=FETCH_TIMEOUT_S, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if not response.is_success:
            return None
        try:
            return await asyncio.to_thread(lambda: tracks(decode(response.content)))
        except (OSError, subprocess.SubprocessError, parselmouth.PraatError):
            return None
