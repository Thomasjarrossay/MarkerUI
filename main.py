"""
MarkerUI — PDF to Markdown converter
=====================================
Architecture : upload → job en background → polling status → téléchargement zip.
Conversion : Gemini Flash Vision (remplace Marker + PyTorch).
"""

import os
import uuid
import zipfile
import asyncio
import logging
import shutil
import time
from pathlib import Path
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from services.gemini_converter import convert_pdf_to_markdown, extract_images
from services.obsidian_formatter import format_for_obsidian
from services.stats import record_conversion, record_llm_call, get_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("/app/uploads_temp")
OUTPUT_DIR = Path("/app/outputs")

# ── Jobs store (in-memory) ────────────────────────────────────────────────────
class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    DONE       = "done"
    ERROR      = "error"

jobs: dict[str, dict] = {}

# Modèles OpenRouter disponibles (pour l'API /api/models)
AVAILABLE_MODELS = [
    {"id": "google/gemini-flash-1.5",          "label": "Gemini Flash 1.5 (rapide, économique)"},
    {"id": "google/gemini-pro-1.5",             "label": "Gemini Pro 1.5 (précis)"},
    {"id": "anthropic/claude-3-5-haiku",        "label": "Claude 3.5 Haiku (rapide)"},
    {"id": "anthropic/claude-3-5-sonnet",       "label": "Claude 3.5 Sonnet (équilibré)"},
    {"id": "openai/gpt-4o-mini",                "label": "GPT-4o Mini (économique)"},
    {"id": "openai/gpt-4o",                     "label": "GPT-4o (précis)"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B (open source)"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("MarkerUI démarré")
    yield


app = FastAPI(title="MarkerUI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/models")
async def get_models():
    current = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
    has_key  = bool(os.getenv("OPENROUTER_API_KEY", ""))
    return {"models": AVAILABLE_MODELS, "current": current, "enabled": has_key}


# ── Upload & start job ────────────────────────────────────────────────────────
@app.post("/api/convert")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: str | None = None,
    obsidian: bool = True,
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    job_id  = str(uuid.uuid4())
    stem    = Path(file.filename).stem
    upload_path = UPLOAD_DIR / f"{job_id}.pdf"

    content = await file.read()
    upload_path.write_bytes(content)

    jobs[job_id] = {
        "status":     JobStatus.PENDING,
        "filename":   f"{stem}.zip",
        "stem":       stem,
        "started_at": None,
        "elapsed":    0,
        "error":      None,
        "step":       "En attente…",
    }

    # Compte les pages avant de démarrer (pdfinfo disponible via poppler-utils)
    page_count = await get_pdf_page_count(upload_path)
    # ~4s/page sur CPU, +30s pour chargement des modèles au premier appel
    estimated_seconds = page_count * 4 + 30 if page_count else 120

    jobs[job_id]["page_count"]        = page_count
    jobs[job_id]["estimated_seconds"] = estimated_seconds

    background_tasks.add_task(run_conversion, job_id, upload_path, stem, model, obsidian)
    logger.info(f"Job {job_id} créé pour '{file.filename}' ({len(content)//1024} KB) | pages={page_count} | est={estimated_seconds}s")
    return {"job_id": job_id, "page_count": page_count, "estimated_seconds": estimated_seconds}


# ── Background conversion ─────────────────────────────────────────────────────
async def get_pdf_page_count(pdf_path: Path) -> int:
    """Retourne le nombre de pages via pdfinfo. Timeout 5s."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pdfinfo", str(pdf_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        for line in stdout.decode().splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except Exception as e:
        logger.warning(f"pdfinfo échoué : {e}")
    return 0


async def run_conversion(job_id: str, upload_path: Path, stem: str, model: str | None, obsidian: bool):
    job = jobs[job_id]
    job["status"]     = JobStatus.PROCESSING
    job["started_at"] = time.time()

    job_dir       = OUTPUT_DIR / job_id
    output_subdir = job_dir / "result"
    output_subdir.mkdir(parents=True)

    try:
        # ── Étape 1 : Conversion PDF → Markdown via Gemini Vision ─────────
        markdown = await convert_pdf_to_markdown(upload_path, job)
        md_path  = output_subdir / f"{stem}.md"
        md_path.write_text(markdown, encoding="utf-8")

        # ── Étape 2 : Extraction des images réelles ────────────────────────
        job["step"] = "Extraction des images…"
        await extract_images(upload_path, output_subdir)

        # ── Étape 3 : Formatage Obsidian via LLM (optionnel) ──────────────
        if obsidian and os.getenv("OPENROUTER_API_KEY"):
            job["step"] = "Formatage Obsidian via LLM…"
            original = md_path.read_text(encoding="utf-8")
            formatted, tok_in, tok_out = await format_for_obsidian(original, model)
            md_path.write_text(formatted, encoding="utf-8")
            if tok_in or tok_out:
                await record_llm_call(
                    model or os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5"),
                    tok_in, tok_out
                )

        # ── Étape 4 : Zip ─────────────────────────────────────────────────
        job["step"] = "Création du zip…"
        zip_path = job_dir / f"{stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_subdir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(output_subdir))

        duration = int(time.time() - job["started_at"])
        job["status"]   = JobStatus.DONE
        job["step"]     = "Terminé"
        job["elapsed"]  = duration
        job["progress"] = 100
        size_mb = upload_path.stat().st_size / 1_048_576 if upload_path.exists() else 0
        await record_conversion(success=True, pages=job.get("page_count", 0), size_mb=size_mb, duration_s=duration)
        logger.info(f"Job {job_id} terminé en {duration}s")

    except Exception as e:
        job["status"] = JobStatus.ERROR
        job["step"]   = "Erreur"
        job["error"]  = str(e)
        logger.error(f"Job {job_id} échoué : {e}")
        await record_conversion(success=False)
    finally:
        upload_path.unlink(missing_ok=True)
        if job.get("started_at"):
            job["elapsed"] = int(time.time() - job["started_at"])


# ── Status polling ────────────────────────────────────────────────────────────
@app.get("/api/status/{job_id}")
async def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable.")

    elapsed = job["elapsed"]
    if job["status"] == JobStatus.PROCESSING and job["started_at"]:
        elapsed = int(time.time() - job["started_at"])

    return {
        "status":            job["status"],
        "filename":          job["filename"],
        "elapsed":           elapsed,
        "estimated_seconds": job.get("estimated_seconds", 0),
        "page_count":        job.get("page_count", 0),
        "step":              job.get("step", ""),
        "error":             job.get("error"),
    }


# ── Download ──────────────────────────────────────────────────────────────────
@app.get("/api/download/{job_id}")
async def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != JobStatus.DONE:
        raise HTTPException(status_code=404, detail="Job introuvable ou pas encore terminé.")

    zip_path = OUTPUT_DIR / job_id / job["filename"]
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Fichier zip introuvable.")

    return FileResponse(path=str(zip_path), media_type="application/zip", filename=job["filename"])


# ── Cleanup ───────────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def stats():
    return get_stats()


@app.delete("/api/job/{job_id}")
async def cleanup_job(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    jobs.pop(job_id, None)
    return {"deleted": job_id}
