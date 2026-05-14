"use strict";

// ── State ─────────────────────────────────────────────────────────────────

let mediaRecorder   = null;
let audioChunks     = [];
let timerInterval   = null;
let pollInterval    = null;
let recordStart     = null;
let currentSession  = null;   // session_id string

// ── Entry point ───────────────────────────────────────────────────────────

async function toggleRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    stopRecording();
  } else {
    await startRecording();
  }
}

// ── Recording ─────────────────────────────────────────────────────────────

async function startRecording() {
  // Request microphone access
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch (err) {
    showError("Нет доступа к микрофону: " + err.message +
              "\n\nПроверьте системные настройки → Конфиденциальность → Микрофон.");
    return;
  }

  // Create a session on the server
  const candidateName = document.getElementById("candidate-name").value.trim();
  const fd = new FormData();
  fd.append("candidate_name", candidateName || "Кандидат");

  let sessionId;
  try {
    const res = await fetch("/sessions", { method: "POST", body: fd });
    ({ session_id: sessionId } = await res.json());
  } catch (err) {
    showError("Не удалось создать сессию: " + err.message);
    stream.getTracks().forEach(t => t.stop());
    return;
  }
  currentSession = sessionId;

  // Choose the best supported format
  const mimeType = pickMimeType();
  mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
  audioChunks = [];

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) audioChunks.push(e.data);
  };

  mediaRecorder.onstop = () => {
    stream.getTracks().forEach(t => t.stop());
    uploadAudio();
  };

  // Collect data every second — keeps memory usage low for long recordings
  mediaRecorder.start(1000);

  setUIState("recording");
  startTimer();
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  stopTimer();
  setUIState("uploading");
}

// ── Upload ────────────────────────────────────────────────────────────────

async function uploadAudio() {
  const type = audioChunks[0]?.type || "audio/webm";
  const blob = new Blob(audioChunks, { type });

  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");

  setStatus("uploading", "Загрузка записи на сервер…");

  try {
    const res = await fetch(`/sessions/${currentSession}/upload`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
  } catch (err) {
    showError("Ошибка загрузки: " + err.message);
    return;
  }

  setStatus("processing", "Обработка аудио…");
  startPolling();
}

// ── Status polling ────────────────────────────────────────────────────────

function startPolling() {
  if (pollInterval) clearInterval(pollInterval);

  pollInterval = setInterval(async () => {
    try {
      const res  = await fetch(`/sessions/${currentSession}/status`);
      const data = await res.json();

      setStatus(data.status, data.label);

      if (data.status === "done") {
        clearInterval(pollInterval);
        loadResults();
      } else if (data.status === "error") {
        clearInterval(pollInterval);
        showError(data.error || "Неизвестная ошибка");
      }
    } catch (err) {
      // Network hiccup — keep polling
      console.warn("Ошибка опроса статуса:", err);
    }
  }, 2000);
}

// ── Results ───────────────────────────────────────────────────────────────

async function loadResults() {
  try {
    const res  = await fetch(`/sessions/${currentSession}/results`);
    const html = await res.text();

    const section   = document.getElementById("results-section");
    const container = document.getElementById("results-container");
    container.innerHTML = html;
    section.style.display = "block";
    section.scrollIntoView({ behavior: "smooth", block: "start" });

    setUIState("done");
    setStatus("done", "Готово!");
  } catch (err) {
    showError("Не удалось загрузить результаты: " + err.message);
  }
}

// ── Tab management (called from results.html onclick) ─────────────────────

function showTab(name, clickedBtn) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(el => el.classList.remove("active"));

  const panel = document.getElementById("tab-" + name);
  if (panel) panel.classList.add("active");
  if (clickedBtn) clickedBtn.classList.add("active");
}

function copyActiveTab(btn) {
  const panel = document.querySelector(".tab-content.active");
  const text  = panel?.querySelector("pre")?.textContent || "";
  if (!text) return;

  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = "Скопировано ✓";
    setTimeout(() => { btn.textContent = orig; }, 2200);
  }).catch(() => {
    // Fallback for older browsers
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    const orig = btn.textContent;
    btn.textContent = "Скопировано ✓";
    setTimeout(() => { btn.textContent = orig; }, 2200);
  });
}

// ── Timer ─────────────────────────────────────────────────────────────────

function startTimer() {
  recordStart = Date.now();
  timerInterval = setInterval(tickTimer, 500);
}

function stopTimer() {
  clearInterval(timerInterval);
}

function tickTimer() {
  const elapsed = Math.floor((Date.now() - recordStart) / 1000);
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = elapsed % 60;
  document.getElementById("timer").textContent =
    `${pad(h)}:${pad(m)}:${pad(s)}`;
}

function pad(n) { return String(n).padStart(2, "0"); }

// ── UI helpers ────────────────────────────────────────────────────────────

function setUIState(state) {
  const btn       = document.getElementById("record-btn");
  const btnDot    = document.getElementById("btn-dot");
  const btnLabel  = document.getElementById("btn-label");
  const setup     = document.getElementById("setup-section");

  // Remove all state classes
  btn.classList.remove("is-recording", "is-processing");
  btn.disabled = false;

  switch (state) {
    case "recording":
      btn.classList.add("is-recording");
      btnDot.textContent   = "■";
      btnLabel.textContent = "Остановить запись";
      setup.style.opacity        = "0.45";
      setup.style.pointerEvents  = "none";
      break;

    case "uploading":
    case "processing":
      btn.classList.add("is-processing");
      btn.disabled         = true;
      btnDot.textContent   = "●";
      btnLabel.textContent = "Обработка…";
      break;

    case "done":
      btnDot.textContent   = "●";
      btnLabel.textContent = "Новая запись";
      setup.style.opacity        = "1";
      setup.style.pointerEvents  = "auto";
      break;

    case "error":
      btnDot.textContent   = "●";
      btnLabel.textContent = "Попробовать снова";
      setup.style.opacity        = "1";
      setup.style.pointerEvents  = "auto";
      break;
  }
}

function setStatus(dotClass, text) {
  const dot = document.getElementById("status-dot");
  dot.className = "status-dot " + dotClass;
  document.getElementById("status-text").textContent = text;
}

function showError(msg) {
  setUIState("error");
  setStatus("error", "Ошибка");
  alert("Ошибка:\n\n" + msg);
}

// ── Media type detection ──────────────────────────────────────────────────

function pickMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}
