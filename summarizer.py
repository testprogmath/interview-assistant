"""
Generates structured Russian-language outputs from a diarised transcript.

Summary uses YandexGPT if configured; falls back to a template otherwise.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def generate_outputs(
    diarized: list[dict],
    candidate_name: str,
    position: str,
    output_dir: Path,
) -> dict:
    """Build all text artefacts, save them, return content for the UI."""
    from yandex_gpt import generate_summary as ygpt_summary, is_configured

    date_str = datetime.now().strftime("%d.%m.%Y")

    raw         = _raw_transcript(diarized)
    cleaned     = _cleaned_transcript(diarized)
    diarised_md = _diarised_transcript(diarized)

    # Try YandexGPT for the AI sections; fall back to placeholder text
    ai_sections: Optional[str] = None
    ai_used = False
    if is_configured():
        ai_sections = ygpt_summary(cleaned, candidate_name, position)
        ai_used = ai_sections is not None

    summary = _summary(diarized, candidate_name, position, date_str, ai_sections)

    (output_dir / "transcript_raw.txt").write_text(raw,         encoding="utf-8")
    (output_dir / "transcript_cleaned.txt").write_text(cleaned, encoding="utf-8")
    (output_dir / "transcript_diarised.md").write_text(diarised_md, encoding="utf-8")
    (output_dir / "summary.md").write_text(summary,             encoding="utf-8")

    logger.info("Файлы сохранены в: %s (YandexGPT: %s)", output_dir, ai_used)

    return {
        "raw_transcript":      raw,
        "cleaned_transcript":  cleaned,
        "diarised_transcript": diarised_md,
        "summary":             summary,
        "output_dir":          str(output_dir),
        "candidate_name":      candidate_name,
        "position":            position,
        "ai_used":             ai_used,
    }


# ─── Transcript formats ──────────────────────────────────────────────────────

def _raw_transcript(segments: list[dict]) -> str:
    return "\n".join(s["text"] for s in segments if s.get("text"))


def _cleaned_transcript(segments: list[dict]) -> str:
    if not segments:
        return ""

    paragraphs: list[str] = []
    buf_speaker = segments[0].get("speaker", "Спикер 1")
    buf_text    = segments[0]["text"].strip()

    for seg in segments[1:]:
        speaker = seg.get("speaker", "Спикер 1")
        text    = seg["text"].strip()
        if not text:
            continue
        if speaker == buf_speaker:
            buf_text += " " + text
        else:
            if buf_text:
                paragraphs.append(f"**{buf_speaker}:** {buf_text}")
            buf_speaker = speaker
            buf_text    = text

    if buf_text:
        paragraphs.append(f"**{buf_speaker}:** {buf_text}")

    return "\n\n".join(paragraphs)


def _diarised_transcript(segments: list[dict]) -> str:
    if not segments:
        return ""

    lines = ["# Транскрипт с разметкой спикеров\n"]
    prev_speaker = None

    for seg in segments:
        speaker = seg.get("speaker", "Спикер")
        text    = seg["text"].strip()
        if not text:
            continue
        if prev_speaker and prev_speaker != speaker:
            lines.append("")
        lines.append(f"[{_fmt_ts(seg['start'])}] **{speaker}:** {text}")
        prev_speaker = speaker

    return "\n".join(lines)


# ─── Summary ─────────────────────────────────────────────────────────────────

def _summary(
    segments: list[dict],
    candidate_name: str,
    position: str,
    date_str: str,
    ai_sections: Optional[str],
) -> str:
    if segments:
        duration_str      = _fmt_duration(segments[-1]["end"] - segments[0]["start"])
        interviewer_turns = [s for s in segments if s.get("speaker") == "Интервьюер"]
        candidate_turns   = [s for s in segments if s.get("speaker") == "Кандидат"]
        questions = [
            s["text"].strip()
            for s in interviewer_turns
            if s["text"].strip().endswith("?")
        ]
    else:
        duration_str      = "н/д"
        interviewer_turns = candidate_turns = questions = []

    position_line = f"\n**Позиция:** {position}" if position else ""
    questions_block = (
        "\n".join(f"- {q}" for q in questions[:15])
        if questions
        else "_Вопросы не определены автоматически._"
    )

    if ai_sections:
        analysis_block = ai_sections
    else:
        analysis_block = """\
## Краткое резюме

_Заполнить вручную или настройте YandexGPT в ⚙ Настройках для автоматической генерации._

---

## Сильные стороны

_Заполнить по итогам интервью_

---

## Риски и опасения

_Заполнить по итогам интервью_

---

## Интересные ответы

_Заполнить по итогам интервью_"""

    diarised_md = _diarised_transcript(segments)

    return f"""\
# Резюме интервью

**Кандидат:** {candidate_name}{position_line}
**Дата:** {date_str}
**Длительность:** {duration_str}
**Реплик интервьюера:** {len(interviewer_turns)}
**Реплик кандидата:** {len(candidate_turns)}

---

{analysis_block}

---

## Вопросы интервьюера

{questions_block}

---

## Транскрипт

{diarised_md}
"""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h} ч {m} мин"
    if m > 0:
        return f"{m} мин {s} сек"
    return f"{s} сек"
