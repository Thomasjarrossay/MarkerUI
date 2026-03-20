/* ── State ───────────────────────────────────────────────────────────────── */
let currentJobId = null;
let currentFilename = null;

/* ── Init ────────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  const dropZone  = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");

  // Drag & drop
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  // Click to browse
  dropZone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) handleFile(fileInput.files[0]);
  });
});

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

  try {
    const res = await fetch("/api/convert", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Erreur inconnue");
    }

    const data = await res.json();
    currentJobId  = data.job_id;
    currentFilename = data.filename;

    showStatus("✅", "Conversion réussie !", file.name);
    setProgress(100);
    document.getElementById("downloadBtn").style.display = "flex";
    document.getElementById("resetBtn").style.display   = "block";

  } catch (err) {
    showStatus("❌", `Erreur : ${err.message}`, file.name);
    setProgress(0);
    document.getElementById("resetBtn").style.display = "block";
  }
}

/* ── Download ────────────────────────────────────────────────────────────── */
async function downloadResult() {
  if (!currentJobId) return;

  const link = document.createElement("a");
  link.href     = `/api/download/${currentJobId}`;
  link.download = currentFilename || "result.zip";
  link.click();

  // Cleanup côté serveur après 5s
  setTimeout(() => {
    fetch(`/api/job/${currentJobId}`, { method: "DELETE" }).catch(() => {});
  }, 5000);
}

/* ── Reset ───────────────────────────────────────────────────────────────── */
function reset() {
  currentJobId   = null;
  currentFilename = null;

  document.getElementById("statusCard").style.display  = "none";
  document.getElementById("downloadBtn").style.display = "none";
  document.getElementById("resetBtn").style.display    = "none";
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
