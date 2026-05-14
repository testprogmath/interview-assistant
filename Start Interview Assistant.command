#!/bin/bash
# ============================================================
#  Интервью Ассистент — macOS launcher
#
#  Дважды щёлкните этот файл, чтобы запустить приложение.
#  При первом запуске зависимости установятся автоматически.
# ============================================================

set -euo pipefail
IFS=$'\n\t'

# ── Resolve script directory (works when double-clicked) ────────────────────
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
PID_FILE="$DIR/.server.pid"
PORT=8000
LOG_FILE="$DIR/logs/server.log"

# ── Pretty output ─────────────────────────────────────────────────────────────
info()  { echo "  ✓  $*"; }
step()  { echo "  →  $*"; }
error() { echo "  ✗  $*" >&2; }

echo ""
echo "  ════════════════════════════════════════════"
echo "   🎙  Интервью Ассистент"
echo "  ════════════════════════════════════════════"
echo ""

# ── Check Python 3 ────────────────────────────────────────────────────────────
PYTHON3=""
for candidate in python3 python3.12 python3.11 python3.10 python3.9; do
  if command -v "$candidate" &>/dev/null; then
    VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    MAJOR=$("$candidate" -c "import sys; print(sys.version_info.major)")
    MINOR=$("$candidate" -c "import sys; print(sys.version_info.minor)")
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
      PYTHON3="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON3" ]; then
  error "Python 3.9+ не найден."
  echo ""
  echo "  Установите Python 3 с сайта: https://www.python.org/downloads/"
  echo "  Затем запустите это приложение снова."
  echo ""
  read -rp "  Нажмите Enter для выхода..." _
  exit 1
fi
info "Python $VER найден ($PYTHON3)"

# ── Check if server is already running ────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    info "Сервер уже запущен (PID $OLD_PID)"
    step "Открываем браузер…"
    open "http://localhost:$PORT"
    echo ""
    echo "  Закройте это окно для остановки сервера."
    echo ""
    # Keep terminal open so user can stop it
    wait "$OLD_PID" 2>/dev/null || true
    exit 0
  else
    rm -f "$PID_FILE"
  fi
fi

# ── Create virtualenv if needed ───────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  step "Создаём виртуальное окружение…"
  "$PYTHON3" -m venv "$VENV"
  info "Виртуальное окружение создано"
fi

PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

# ── Install / verify dependencies ─────────────────────────────────────────────
if ! "$PYTHON" -c "import fastapi" &>/dev/null 2>&1; then
  step "Устанавливаем зависимости (первый запуск, может занять несколько минут)…"
  "$PIP" install --quiet --upgrade pip
  "$PIP" install --quiet -r "$DIR/requirements.txt"
  info "Зависимости установлены"
else
  info "Зависимости в порядке"
fi

# ── Create runtime directories ────────────────────────────────────────────────
mkdir -p "$DIR/uploads" "$DIR/outputs" "$DIR/logs"

# ── Start server ──────────────────────────────────────────────────────────────
step "Запускаем сервер…"
cd "$DIR"
"$PYTHON" app.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# ── Wait until server is ready (max 45 s) ────────────────────────────────────
step "Ждём готовности…"
READY=0
for i in $(seq 1 45); do
  if curl -s -o /dev/null "http://localhost:$PORT/" 2>/dev/null; then
    READY=1
    break
  fi
  # Check the process is still alive
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    error "Сервер завершился неожиданно."
    echo ""
    echo "  Последние строки лога ($LOG_FILE):"
    tail -20 "$LOG_FILE" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo ""
    read -rp "  Нажмите Enter для выхода..." _
    exit 1
  fi
  sleep 1
done

if [ "$READY" -eq 0 ]; then
  error "Сервер не ответил за 45 секунд."
  echo ""
  echo "  Последние строки лога ($LOG_FILE):"
  tail -20 "$LOG_FILE" 2>/dev/null || true
  kill "$SERVER_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo ""
  read -rp "  Нажмите Enter для выхода..." _
  exit 1
fi

# ── Open browser ──────────────────────────────────────────────────────────────
info "Интервью Ассистент готов к работе"
echo ""
step "Открываем браузер: http://localhost:$PORT"
open "http://localhost:$PORT"
echo ""

# ── Keep running until this Terminal window is closed ─────────────────────────
echo "  ────────────────────────────────────────────"
echo "  Сервер работает (PID $SERVER_PID)."
echo "  Закройте это окно, чтобы остановить его."
echo "  ────────────────────────────────────────────"
echo ""

cleanup() {
  echo ""
  step "Останавливаем сервер…"
  kill "$SERVER_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
  info "Сервер остановлен. До свидания!"
  echo ""
}
trap cleanup EXIT INT TERM

wait "$SERVER_PID" 2>/dev/null || true
