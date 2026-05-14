"""
Whisper transcription worker.

Uses faster-whisper for fully local, privacy-preserving transcription.
Model is downloaded from HuggingFace on first use and cached locally.

First run with `medium` model:  downloads ~1.5 GB, takes several minutes.
Subsequent runs:                loads from local cache, takes ~10–30 s.
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cached model instance — shared across requests within one server process
_model_cache: dict[str, Any] = {}

# Default model size.  Options: tiny | base | small | medium | large-v2 | large-v3
# medium  →  good accuracy, ~1.5 GB, works on CPU
# large-v3 →  best accuracy, ~3 GB, slower on CPU
MODEL_SIZE = "medium"


def get_model(model_size: str = MODEL_SIZE):
    """Load WhisperModel and cache it in memory for reuse."""
    if model_size not in _model_cache:
        from faster_whisper import WhisperModel

        logger.info("Загружаем модель Whisper '%s'…", model_size)
        logger.info("(Первый запуск: скачивание ~1.5 GB, подождите несколько минут)")

        # int8 quantisation: fast on CPU and Apple Silicon, minimal quality loss
        _model_cache[model_size] = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
        )
        logger.info("Модель '%s' загружена.", model_size)

    return _model_cache[model_size]


def transcribe_audio(audio_path: str, model_size: str = MODEL_SIZE) -> list[dict]:
    """
    Transcribe an audio file and return a list of segments.

    Each segment is a dict with keys:
        start (float)  — start time in seconds
        end   (float)  — end time in seconds
        text  (str)    — transcribed text

    VAD filter skips silence, which reduces hallucinations and speeds up
    transcription significantly.
    """
    logger.info("Начинаем транскрибацию: %s", Path(audio_path).name)

    model = get_model(model_size)

    segments_iter, info = model.transcribe(
        audio_path,
        language="ru",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
    )

    result = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        result.append({
            "start": round(seg.start, 2),
            "end":   round(seg.end, 2),
            "text":  text,
        })

    logger.info(
        "Транскрибация завершена: %d сегментов, длительность ~%.0f с",
        len(result),
        info.duration,
    )
    return result
