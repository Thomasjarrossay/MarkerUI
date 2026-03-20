/* ── State ───────────────────────────────────────────────────────────────── */
let currentJobId   = null;
let pollInterval   = null;
let elapsedTimer   = null;
let elapsedSeconds = 0;
let obsidianEnabled = false;

/* ── Init ────────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  const dropZone  = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");

  dropZone.addEventListener("dragover",  (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", ()  => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });
  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

  loadModels();

  document.getElementById("obsidianToggle").addEventListener("change", (e) => {
    obsidianEnabled = e.target.checked;
    document.getElementById("modelRow").style.display = obsidianEnabled ? "flex" : "none";
  });
});

/* ── Load models from API ────────────────────────────────────────────────── */
async function loadModels() {
  try {
    const res  = await fetch("/api/models");
    const data = await res.json();
    const toggle = document.getElementById("obsidianToggle");
    const hint   = document.getElementById("obsidianHint");
    const select = document.getElementById("modelSelect");

    if (data.enabled) {
      toggle.disabled  = false;
      toggle.checked   = true;
      obsidianEnabled  = true;
      hint.textContent = "Formatage Obsidian activé";
      document.getElementById("modelRow").style.display = "flex";

      data.models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = m.label;
        if (m.id === data.current) opt.selected = true;
        select.appendChild(opt);
      });
    } else {
      toggle.disabled  = true;
      hint.textContent = "Configurez OPENROUTER_API_KEY pour activer";
    }
  } catch (_) {}
}

/* ── File handling ───────────────────────────────────────────────────────── */
function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    alert("Seuls les fichiers PDF sont acceptés.");
    return;
  }
  uploadFile(file);
}

async function uploadFile(file) {
  showStatus("⏳", "Envoi du PDF…", file.name);
  setProgress("indeterminate");

  const formData = new FormData();
  formData.append("file", file);

  const model    = document.getElementById("modelSelect")?.value || "";
  const url      = `/api/convert?obsidian=${obsidianEnabled}${model ? `&model=${encodeURIComponent(model)}` : ""}`;

  try {
    const res = await fetch(url, { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Erreur inconnue");
    }
    const data = await res.json();
    currentJobId = data.job_id;
    startPolling(file.name);
  } catch (err) {
    showError(`Erreur upload : ${err.message}`);
  }
}

/* ── Polling ─────────────────────────────────────────────────────────────── */
function startPolling(filename) {
  elapsedSeconds = 0;
  startElapsedTimer();
  showStatus("⚙️", "Conversion en cours…", filename);
  setProgress("indeterminate");

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${currentJobId}`);
      if (!res.ok) return;
      const data = await res.json();

      if (data.step) {
        document.getElementById("stepLabel").textContent = data.step;
      }
      if (data.status === "done") {
        stopPolling();
        showSuccess(data.elapsed);
      } else if (data.status === "error") {
        stopPolling();
        showError(data.error || "Erreur inconnue lors de la conversion.");
      }
      // "pending" et "processing" → on continue à poller
    } catch (_) { /* réseau temporairement indispo, on réessaie */ }
  }, 2000);
}

function stopPolling() {
  clearInterval(pollInterval);
  clearInterval(elapsedTimer);
  pollInterval = null;
  elapsedTimer = null;
}

/* ── Elapsed timer ───────────────────────────────────────────────────────── */
function startElapsedTimer() {
  elapsedTimer = setInterval(() => {
    elapsedSeconds++;
    const el = document.getElementById("elapsedTime");
    if (el) el.textContent = formatTime(elapsedSeconds);

    // Estimation : ~3s/page en moyenne sur CPU, affiche après 10s
    const hint = document.getElementById("timeHint");
    if (hint && elapsedSeconds >= 10) {
      hint.style.display = "block";
      const estRemaining = Math.max(0, Math.round((elapsedSeconds / 0.4) - elapsedSeconds));
      hint.textContent = estRemaining > 5
        ? `Estimation : encore ~${formatTime(estRemaining)}`
        : "Finalisation…";
    }
  }, 1000);
}

function formatTime(s) {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r > 0 ? `${m}m ${r}s` : `${m}m`;
}

/* ── Success / Error ─────────────────────────────────────────────────────── */
function showSuccess(elapsed) {
  setProgress(100);
  document.getElementById("statusIcon").textContent  = "✅";
  document.getElementById("statusLabel").textContent = `Conversion terminée en ${formatTime(elapsed)} !`;
  document.getElementById("elapsedRow").style.display = "none";
  document.getElementById("timeHint").style.display  = "none";
  document.getElementById("downloadBtn").style.display = "flex";
  document.getElementById("resetBtn").style.display   = "block";
}

function showError(msg) {
  setProgress(0);
  document.getElementById("statusIcon").textContent  = "❌";
  document.getElementById("statusLabel").textContent = `Erreur : ${msg}`;
  document.getElementById("elapsedRow").style.display = "none";
  document.getElementById("timeHint").style.display  = "none";
  document.getElementById("resetBtn").style.display  = "block";
}

/* ── Download ────────────────────────────────────────────────────────────── */
async function downloadResult() {
  if (!currentJobId) return;
  const link = document.createElement("a");
  link.href     = `/api/download/${currentJobId}`;
  link.download = "";
  link.click();
  setTimeout(() => {
    fetch(`/api/job/${currentJobId}`, { method: "DELETE" }).catch(() => {});
  }, 5000);
}

/* ── Reset ───────────────────────────────────────────────────────────────── */
function reset() {
  stopPolling();
  currentJobId = null;
  elapsedSeconds = 0;

  document.getElementById("statusCard").style.display  = "none";
  document.getElementById("downloadBtn").style.display = "none";
  document.getElementById("resetBtn").style.display    = "none";
  document.getElementById("elapsedRow").style.display  = "flex";
  document.getElementById("timeHint").style.display    = "none";
  document.getElementById("stepLabel").textContent     = "";
  document.getElementById("dropZone").style.display    = "flex";
  document.getElementById("fileInput").value           = "";
}

/* ── UI helpers ──────────────────────────────────────────────────────────── */
function showStatus(icon, label, filename) {
  document.getElementById("dropZone").style.display   = "none";
  document.getElementById("statusCard").style.display = "flex";
  document.getElementById("statusIcon").textContent   = icon;
  document.getElementById("statusLabel").textContent  = label;
  document.getElementById("statusFile").textContent   = filename || "";
  document.getElementById("elapsedTime").textContent  = "0s";
  document.getElementById("elapsedRow").style.display = "flex";
  document.getElementById("timeHint").style.display   = "none";
}

function setProgress(value) {
  const fill = document.getElementById("progressFill");
  if (value === "indeterminate") {
    fill.classList.add("indeterminate");
    fill.style.width = "";
  } else {
    fill.classList.remove("indeterminate");
    fill.style.width = `${value}%`;
  }
}
