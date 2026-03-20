"""
MarkerUI — PDF to Markdown converter
=====================================
FastAPI backend wrapping marker-pdf.
Architecture : upload → job en background → polling status → téléchargement zip.
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


# ── Upload & start job ────────────────────────────────────────────────────────
@app.post("/api/convert")
async def convert(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    job_id  = str(uuid.uuid4())
    stem    = Path(file.filename).stem
    upload_path = UPLOAD_DIR / f"{job_id}.pdf"

    content = await file.read()
    upload_path.write_bytes(content)

    jobs[job_id] = {
        "status":   JobStatus.PENDING,
        "filename": f"{stem}.zip",
        "stem":     stem,
        "started_at": None,
        "elapsed":  0,
        "error":    None,
    }

    background_tasks.add_task(run_marker, job_id, upload_path, stem)
    logger.info(f"Job {job_id} créé pour '{file.filename}' ({len(content)//1024} KB)")
    return {"job_id": job_id}


# ── Background conversion ─────────────────────────────────────────────────────
async def run_marker(job_id: str, upload_path: Path, stem: str):
    job = jobs[job_id]
    job["status"]     = JobStatus.PROCESSING
    job["started_at"] = time.time()

    job_dir       = OUTPUT_DIR / job_id
    output_subdir = job_dir / "result"
    output_subdir.mkdir(parents=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            "marker_single",
            str(upload_path),
            "--output_dir", str(output_subdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[-600:])

        # Zip
        zip_path = job_dir / f"{stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_subdir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(output_subdir))

        job["status"]  = JobStatus.DONE
        job["elapsed"] = int(time.time() - job["started_at"])
        logger.info(f"Job {job_id} terminé en {job['elapsed']}s")

    except Exception as e:
        job["status"] = JobStatus.ERROR
        job["error"]  = str(e)
        logger.error(f"Job {job_id} échoué : {e}")
    finally:
        upload_path.unlink(missing_ok=True)
        if "started_at" in job and job["started_at"]:
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
        "status":   job["status"],
        "filename": job["filename"],
        "elapsed":  elapsed,
        "error":    job.get("error"),
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
@app.delete("/api/job/{job_id}")
async def cleanup_job(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    jobs.pop(job_id, None)
    return {"deleted": job_id}
