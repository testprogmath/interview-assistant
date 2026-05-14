"""
Interview Assistant — local-first interview recording and transcription tool.
Run with:  python app.py
"""

import asyncio
import json
import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")

# ─── Directories ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
LOG_DIR = BASE_DIR / "logs"

for _dir in (UPLOAD_DIR, OUTPUT_DIR, LOG_DIR):
    _dir.mkdir(exist_ok=True)

# ─── App setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="Interview Assistant", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ─── In-memory session store ─────────────────────────────────────────────────
# Single-user local tool: a plain dict is sufficient.

sessions: dict[str, dict] = {}

# Thread pool for blocking transcription work
executor = ThreadPoolExecutor(max_workers=2)

STATUS_LABELS: dict[str, str] = {
    "created":      "Готов к работе",
    "processing":   "Обработка...",
    "transcribing": "Транскрибация аудио…",
    "diarizing":    "Разделение по спикерам…",
    "summarizing":  "Генерация резюме…",
    "done":         "Готово!",
    "error":        "Ошибка",
}

# ─── Routes ──────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/sessions")
async def create_session(candidate_name: str = Form(default="")):
    session_id = uuid.uuid4().hex[:8]
    sessions[session_id] = {
        "id": session_id,
        "candidate_name": candidate_name.strip() or "Кандидат",
        "created_at": datetime.now().isoformat(),
        "status": "created",
        "error": None,
        "audio_path": None,
        "output_dir": None,
        "results": {},
    }
    logger.info("Создана сессия %s для '%s'", session_id, sessions[session_id]["candidate_name"])
    return JSONResponse({"session_id": session_id})


@app.post("/sessions/{session_id}/upload")
async def upload_audio(
    session_id: str,
    audio: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session = sessions[session_id]

    # Determine extension from content-type (browsers send audio/webm)
    content_type = audio.content_type or "audio/webm"
    ext = ".webm" if "webm" in content_type else ".wav"

    audio_dir = UPLOAD_DIR / session_id
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"recording{ext}"

    content = await audio.read()
    audio_path.write_bytes(content)
    logger.info("Аудио сохранено: %s (%.1f MB)", audio_path, len(content) / 1_048_576)

    session["audio_path"] = str(audio_path)
    session["status"] = "processing"

    background_tasks.add_task(_process_session, session_id)

    return JSONResponse({"status": "processing", "session_id": session_id})


@app.get("/sessions/{session_id}/status")
async def get_status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session = sessions[session_id]
    return JSONResponse({
        "status": session["status"],
        "label":  STATUS_LABELS.get(session["status"], session["status"]),
        "error":  session.get("error"),
        "done":   session["status"] == "done",
    })


@app.get("/sessions/{session_id}/results", response_class=HTMLResponse)
async def get_results(request: Request, session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session = sessions[session_id]
    if session["status"] != "done":
        return HTMLResponse("")

    return templates.TemplateResponse(
        "results.html",
        {"request": request, "session": session, **session["results"]},
    )


@app.get("/sessions/{session_id}/files/{filename}")
async def download_file(session_id: str, filename: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session = sessions[session_id]
    output_dir = Path(session.get("output_dir", ""))
    file_path = (output_dir / filename).resolve()

    # Prevent directory traversal
    if not str(file_path).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")

    return FileResponse(str(file_path), filename=filename)


# ─── Background processing pipeline ─────────────────────────────────────────


async def _process_session(session_id: str) -> None:
    """Run transcription → diarisation → summary in a background thread pool."""
    from diarization import diarize_segments
    from summarizer import generate_outputs
    from whisper_worker import transcribe_audio

    session = sessions[session_id]

    try:
        audio_path = session["audio_path"]
        candidate_name = session["candidate_name"]

        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_name = _slugify(candidate_name)
        output_dir = OUTPUT_DIR / f"{date_str}_{safe_name}_{session_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        session["output_dir"] = str(output_dir)

        loop = asyncio.get_running_loop()

        # 1. Transcribe
        session["status"] = "transcribing"
        logger.info("[%s] Транскрибация...", session_id)
        segments: list[dict] = await loop.run_in_executor(
            executor, transcribe_audio, audio_path
        )

        # 2. Diarise
        session["status"] = "diarizing"
        logger.info("[%s] Диаризация (%d сегментов)...", session_id, len(segments))
        diarized: list[dict] = await loop.run_in_executor(
            executor, diarize_segments, segments
        )

        # 3. Generate outputs
        session["status"] = "summarizing"
        logger.info("[%s] Генерация файлов...", session_id)
        results: dict = await loop.run_in_executor(
            executor, generate_outputs, diarized, candidate_name, output_dir
        )

        # Copy original recording to output dir
        rec_src = Path(audio_path)
        shutil.copy2(rec_src, output_dir / rec_src.name)

        # Save metadata
        metadata = {
            "session_id":     session_id,
            "candidate_name": candidate_name,
            "created_at":     session["created_at"],
            "processed_at":   datetime.now().isoformat(),
            "audio_file":     rec_src.name,
            "segments_count": len(segments),
        }
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        session["results"] = results
        session["status"] = "done"
        logger.info("[%s] Готово. Файлы в %s", session_id, output_dir)

    except Exception as exc:
        session["status"] = "error"
        session["error"] = str(exc)
        logger.exception("[%s] Ошибка обработки: %s", session_id, exc)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_TRANSLIT = {
    "а": "a",  "б": "b",  "в": "v",  "г": "g",  "д": "d",  "е": "e",  "ё": "yo",
    "ж": "zh", "з": "z",  "и": "i",  "й": "y",  "к": "k",  "л": "l",  "м": "m",
    "н": "n",  "о": "o",  "п": "p",  "р": "r",  "с": "s",  "т": "t",  "у": "u",
    "ф": "f",  "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "",   "ы": "y",  "ь": "",   "э": "e",  "ю": "yu", "я": "ya",
}


def _slugify(text: str) -> str:
    import re
    result = "".join(_TRANSLIT.get(c, c) for c in text.lower())
    result = re.sub(r"[^a-z0-9]+", "-", result).strip("-")
    return result[:30] or "kandidat"


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Интервью Ассистент запущен.")
    print("  Откройте браузер: http://localhost:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
