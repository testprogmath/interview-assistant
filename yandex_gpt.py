"""
YandexGPT client for interview summary generation.

Reads credentials from config.json in the project root.
Falls back to template-based output silently if not configured or on error.

API docs: https://yandex.cloud/ru/docs/foundation-models/text-generation/api-ref/
"""

import json
import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"
API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# Truncate transcript sent to the API to stay within token limits
MAX_TRANSCRIPT_CHARS = 12_000


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_configured() -> bool:
    cfg = load_config().get("yandex_gpt", {})
    return bool(cfg.get("enabled") and cfg.get("api_key") and cfg.get("folder_id"))


def generate_summary(
    transcript: str,
    candidate_name: str,
    position: str,
) -> Optional[str]:
    """
    Call YandexGPT and return a structured Russian summary.
    Returns None if not configured or on any error.
    """
    cfg = load_config().get("yandex_gpt", {})
    if not (cfg.get("enabled") and cfg.get("api_key") and cfg.get("folder_id")):
        return None

    api_key   = cfg["api_key"]
    folder_id = cfg["folder_id"]
    model     = cfg.get("model", "yandexgpt")

    # Truncate long transcripts
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[... транскрипт обрезан ...]"

    position_str = f" на позицию «{position}»" if position else ""
    system_prompt = (
        "Ты — опытный ассистент рекрутера. "
        "Отвечай строго на русском языке. "
        "Пиши кратко, структурированно, без воды."
    )
    user_prompt = f"""\
Проанализируй транскрипт интервью с кандидатом {candidate_name}{position_str}.

Составь краткое структурированное резюме в следующем формате (используй markdown):

## Краткое резюме
(3–5 предложений об общем впечатлении)

## Сильные стороны
(маркированный список)

## Риски и опасения
(маркированный список или «Не выявлено»)

## Интересные ответы
(1–3 цитаты или момента, которые стоит отметить)

Транскрипт:
{transcript}"""

    payload = {
        "modelUri": f"gpt://{folder_id}/{model}/latest",
        "completionOptions": {
            "stream": False,
            "temperature": 0.3,
            "maxTokens": "2000",
        },
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user",   "text": user_prompt},
        ],
    }
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id":   folder_id,
        "Content-Type":  "application/json",
    }

    try:
        logger.info("Отправляем запрос в YandexGPT (модель: %s)…", model)
        with httpx.Client(timeout=60) as client:
            resp = client.post(API_URL, json=payload, headers=headers)
            resp.raise_for_status()

        text = resp.json()["result"]["alternatives"][0]["message"]["text"]
        logger.info("YandexGPT ответил успешно.")
        return text.strip()

    except Exception as exc:
        logger.warning("YandexGPT недоступен, используем шаблон: %s", exc)
        return None


def test_connection() -> tuple[bool, str]:
    """Quick connectivity test. Returns (ok, message)."""
    cfg = load_config().get("yandex_gpt", {})
    api_key   = cfg.get("api_key", "")
    folder_id = cfg.get("folder_id", "")

    if not api_key or not folder_id:
        return False, "API-ключ или идентификатор каталога не заполнены."

    model = cfg.get("model", "yandexgpt")
    payload = {
        "modelUri": f"gpt://{folder_id}/{model}/latest",
        "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "5"},
        "messages": [{"role": "user", "text": "Привет"}],
    }
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id":   folder_id,
        "Content-Type":  "application/json",
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(API_URL, json=payload, headers=headers)
            resp.raise_for_status()
        return True, "Соединение установлено успешно."
    except httpx.HTTPStatusError as exc:
        return False, f"Ошибка API: {exc.response.status_code} — {exc.response.text[:200]}"
    except Exception as exc:
        return False, f"Ошибка соединения: {exc}"
