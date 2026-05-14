"""
Generates structured Russian-language outputs from a diarised transcript.

No LLM required — everything is template-based.  The summary and recruiter
notes use the transcript content directly and leave placeholders for the
recruiter to fill in manually.

All five artefacts are written to `output_dir` and also returned as strings
so the web UI can display them without re-reading files.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_outputs(
    diarized: list[dict],
    candidate_name: str,
    output_dir: Path,
) -> dict:
    """
    Build all five text artefacts and save them to output_dir.

    Returns a dict with keys matching the Jinja template variables.
    """
    date_str = datetime.now().strftime("%d.%m.%Y")

    raw          = _raw_transcript(diarized)
    cleaned      = _cleaned_transcript(diarized)
    diarised_md  = _diarised_transcript(diarized)
    summary      = _summary(diarized, candidate_name, date_str)
    notes        = _recruiter_notes(diarized, candidate_name, date_str)

    (output_dir / "transcript_raw.txt").write_text(raw,         encoding="utf-8")
    (output_dir / "transcript_cleaned.txt").write_text(cleaned, encoding="utf-8")
    (output_dir / "transcript_diarised.md").write_text(diarised_md, encoding="utf-8")
    (output_dir / "summary.md").write_text(summary,             encoding="utf-8")
    (output_dir / "recruiter_notes.md").write_text(notes,       encoding="utf-8")

    logger.info("Файлы сохранены в: %s", output_dir)

    return {
        "raw_transcript":      raw,
        "cleaned_transcript":  cleaned,
        "diarised_transcript": diarised_md,
        "summary":             summary,
        "recruiter_notes":     notes,
        "output_dir":          str(output_dir),
        "candidate_name":      candidate_name,
    }


# ─── Transcript formats ──────────────────────────────────────────────────────

def _raw_transcript(segments: list[dict]) -> str:
    """Plain concatenated text, no speaker labels."""
    return "\n".join(s["text"] for s in segments if s.get("text"))


def _cleaned_transcript(segments: list[dict]) -> str:
    """
    Speaker-labelled text.  Consecutive utterances from the same speaker
    are merged into a single paragraph.
    """
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
    """Timestamped transcript with speaker labels."""
    if not segments:
        return ""

    lines = ["# Транскрипт с разметкой спикеров\n"]
    prev_speaker = None

    for seg in segments:
        speaker = seg.get("speaker", "Спикер")
        text    = seg["text"].strip()
        if not text:
            continue

        # Blank line between turns for readability
        if prev_speaker and prev_speaker != speaker:
            lines.append("")

        ts = _fmt_ts(seg["start"])
        lines.append(f"[{ts}] **{speaker}:** {text}")
        prev_speaker = speaker

    return "\n".join(lines)


# ─── Summary and notes ───────────────────────────────────────────────────────

def _summary(segments: list[dict], candidate_name: str, date_str: str) -> str:
    if not segments:
        duration_str = "н/д"
        interviewer_count = candidate_count = 0
        questions_block = "_Вопросы не определены._"
    else:
        duration_str = _fmt_duration(segments[-1]["end"] - segments[0]["start"])
        interviewer_turns = [s for s in segments if s.get("speaker") == "Интервьюер"]
        candidate_turns   = [s for s in segments if s.get("speaker") == "Кандидат"]
        interviewer_count = len(interviewer_turns)
        candidate_count   = len(candidate_turns)

        questions = [
            s["text"].strip()
            for s in interviewer_turns
            if s["text"].strip().endswith("?")
        ]
        if questions:
            questions_block = "\n".join(f"- {q}" for q in questions[:15])
        else:
            questions_block = "_Вопросы не определены автоматически._"

    diarised_md = _diarised_transcript(segments)

    return f"""\
# Резюме интервью

**Кандидат:** {candidate_name}
**Дата:** {date_str}
**Длительность:** {duration_str}
**Реплик интервьюера:** {interviewer_count}
**Реплик кандидата:** {candidate_count}

---

## Краткое резюме

_Автоматическое резюме требует локальной языковой модели (Ollama и др.)._
_Заполните этот раздел вручную после прочтения транскрипта._

---

## Сильные стороны

_Заполнить по итогам интервью_

---

## Риски и опасения

_Заполнить по итогам интервью_

---

## Вопросы интервьюера

{questions_block}

---

## Интересные ответы кандидата

_Заполнить по итогам интервью_

---

## Транскрипт

{diarised_md}
"""


def _recruiter_notes(segments: list[dict], candidate_name: str, date_str: str) -> str:
    candidate_questions = [
        s["text"].strip()
        for s in segments
        if s.get("speaker") == "Кандидат" and s["text"].strip().endswith("?")
    ]
    cq_block = (
        "\n".join(f"- {q}" for q in candidate_questions)
        if candidate_questions
        else "_Вопросов от кандидата не обнаружено_"
    )

    return f"""\
# Заметки рекрутера

**Кандидат:** {candidate_name}
**Дата интервью:** {date_str}
**Интервьюер:** _______________

---

## Общее впечатление

_Заполнить после интервью_

---

## Технические компетенции

| Навык | Оценка (1–5) | Комментарий |
|-------|-------------|-------------|
|       |             |             |
|       |             |             |
|       |             |             |

---

## Soft Skills

- **Коммуникация:** \_\_\_/5
- **Самостоятельность:** \_\_\_/5
- **Мотивация:** \_\_\_/5
- **Культурный fit:** \_\_\_/5

---

## Вопросы от кандидата

{cq_block}

---

## Красные флаги

_Заполнить если есть_

---

## Рекомендация

- [ ] Перейти на следующий этап
- [ ] Отклонить кандидата
- [ ] Обсудить с командой

**Обоснование:** _______________

---

## Дополнительные заметки

_Свободные заметки_
"""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h} ч {m} мин"
    if m > 0:
        return f"{m} мин {s} сек"
    return f"{s} сек"
