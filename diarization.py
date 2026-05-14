"""
Simple speaker diarisation.

Approach: gap-based speaker alternation.
  1. Merge Whisper segments that are very close together (< MERGE_GAP s)
     into longer utterances — prevents single words getting their own turn.
  2. Detect speaker changes at silence gaps longer than CHANGE_GAP s.
  3. Assign speakers alternating between "Интервьюер" and "Кандидат".

This works well for structured 1-on-1 interviews where speakers alternate
clearly and there are natural pauses between turns.  It is not perfect —
for maximum accuracy a dedicated diarisation model (pyannote.audio) can be
added later without changing the rest of the pipeline.
"""

import logging

logger = logging.getLogger(__name__)

SPEAKERS = ["Интервьюер", "Кандидат"]

# Silence gap (seconds) that triggers a speaker change
CHANGE_GAP = 1.2

# Segments closer than this (seconds) are merged into one utterance
MERGE_GAP = 0.5


def diarize_segments(segments: list[dict]) -> list[dict]:
    """Add a 'speaker' key to each segment."""
    if not segments:
        return []

    merged = _merge_close(segments, MERGE_GAP)
    diarized = _assign_speakers(merged, CHANGE_GAP)

    logger.info(
        "Диаризация: %d сегментов → %d реплик (%s: %d, %s: %d)",
        len(segments),
        len(diarized),
        SPEAKERS[0],
        sum(1 for s in diarized if s["speaker"] == SPEAKERS[0]),
        SPEAKERS[1],
        sum(1 for s in diarized if s["speaker"] == SPEAKERS[1]),
    )
    return diarized


def _merge_close(segments: list[dict], gap: float) -> list[dict]:
    """Merge segments whose gap is smaller than `gap` seconds."""
    merged = [dict(segments[0])]
    for seg in segments[1:]:
        if seg["start"] - merged[-1]["end"] < gap:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = merged[-1]["text"].rstrip() + " " + seg["text"].lstrip()
        else:
            merged.append(dict(seg))
    return merged


def _assign_speakers(segments: list[dict], change_gap: float) -> list[dict]:
    """Alternate speakers whenever the silence gap exceeds `change_gap`."""
    result = []
    speaker_idx = 0

    for i, seg in enumerate(segments):
        if i > 0:
            gap = seg["start"] - segments[i - 1]["end"]
            if gap >= change_gap:
                speaker_idx = 1 - speaker_idx  # toggle

        result.append({**seg, "speaker": SPEAKERS[speaker_idx]})

    return result
