"""
MarkerUI — PDF to Markdown converter
=====================================
FastAPI backend wrapping marker-pdf.
Upload a PDF → get back a .zip with .md + extracted images.
"""

import os
import uuid
import zipfile
import asyncio
import logging
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("/app/uploads_temp")
OUTPUT_DIR = Path("/app/outputs")

@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("MarkerUI démarré")
    yield
    logger.info("MarkerUI arrêté")

app = FastAPI(title="MarkerUI", lifespan=lifespan)

# ── Static files ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok"}

# ── Convert ───────────────────────────────────────────────────────────────────
@app.post("/api/convert")
async def convert(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    job_id = str(uuid.uuid4())
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True)

    # Sauvegarde du PDF uploadé
    upload_path = UPLOAD_DIR / f"{job_id}.pdf"
    try:
        content = await file.read()
        upload_path.write_bytes(content)
        logger.info(f"PDF reçu : {file.filename} ({len(content) / 1024:.0f} KB)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur upload : {e}")

    # Lancement de marker en subprocess
    output_subdir = job_dir / "result"
    output_subdir.mkdir()

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
            logger.error(f"marker_single failed: {stderr.decode()}")
            raise HTTPException(status_code=500, detail=f"Erreur Marker : {stderr.decode()[-500:]}")

        logger.info(f"Conversion réussie : {job_id}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="marker_single introuvable. Vérifiez l'installation.")
    finally:
        upload_path.unlink(missing_ok=True)

    # Création du zip
    stem = Path(file.filename).stem
    zip_path = job_dir / f"{stem}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f_path in output_subdir.rglob("*"):
            if f_path.is_file():
                zf.write(f_path, f_path.relative_to(output_subdir))

    logger.info(f"Zip créé : {zip_path.name}")
    return JSONResponse({"job_id": job_id, "filename": f"{stem}.zip"})


@app.get("/api/download/{job_id}")
async def download(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job introuvable ou expiré.")

    zips = list(job_dir.glob("*.zip"))
    if not zips:
        raise HTTPException(status_code=404, detail="Fichier zip introuvable.")

    zip_path = zips[0]
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_path.name,
        background=None,
    )


@app.delete("/api/job/{job_id}")
async def cleanup_job(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {"deleted": job_id}
