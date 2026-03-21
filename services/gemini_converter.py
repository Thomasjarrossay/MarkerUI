"""
Gemini Vision Converter
=======================
Remplace Marker + PyTorch.
Convertit un PDF en Markdown via Gemini Flash Vision.

Pipeline :
  PDF → pages PIL (pdf2image) → Gemini Flash (vision) → Markdown

Variables d'env :
  GOOGLE_API_KEY       — clé Google AI Studio (obligatoire)
  GEMINI_MODEL         — modèle (défaut: gemini-2.0-flash)
  GEMINI_PAGES_PER_REQ — pages envoyées par requête (défaut: 4)
"""

import os
import io
import asyncio
import logging
import base64
from pathlib import Path

import google.generativeai as genai
from pdf2image import convert_from_path
from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_MODEL      = "gemini-2.0-flash"
PAGES_PER_BATCH    = int(os.getenv("GEMINI_PAGES_PER_REQ", "4"))
RATE_LIMIT_DELAY   = 4.5  # secondes entre requêtes (≤ 15 RPM free tier)

PAGE_PROMPT = """Convert these PDF page(s) to clean Markdown.

Rules:
- Preserve ALL text content faithfully — do not summarize or skip anything
- Use proper Markdown heading hierarchy (# ## ###)
- Convert tables to Markdown table format (| col | col |)
- Use ``` fences for code blocks, with language if identifiable
- For figures, charts, diagrams: write a description as a callout:
  > **[Figure]** Description of what the image shows
- Remove page numbers, running headers, and footers
- Preserve mathematical formulas as LaTeX: inline $formula$, block $$formula$$
- Return ONLY the Markdown content, no preamble or explanation
"""


def _page_to_jpeg_bytes(page: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


async def convert_pdf_to_markdown(
    pdf_path: Path,
    job: dict,
) -> str:
    """
    Convertit un PDF en Markdown via Gemini Vision.
    Met à jour job["step"] et job["progress"] (0-100) en temps réel.
    Retourne le Markdown complet.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY non configuré")

    model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    # ── Conversion PDF → images ──────────────────────────────────────────
    job["step"] = "Conversion PDF → images…"
    loop = asyncio.get_event_loop()
    pages = await loop.run_in_executor(
        None,
        lambda: convert_from_path(str(pdf_path), dpi=150, fmt="jpeg"),
    )
    total_pages = len(pages)
    logger.info(f"PDF → {total_pages} pages | modèle: {model_name} | batch: {PAGES_PER_BATCH}")

    # ── Envoi par batch à Gemini ─────────────────────────────────────────
    chunks = []
    batch_size = PAGES_PER_BATCH

    for batch_start in range(0, total_pages, batch_size):
        batch = pages[batch_start: batch_start + batch_size]
        page_range = f"{batch_start + 1}-{min(batch_start + batch_size, total_pages)}"
        job["step"] = f"Gemini — pages {page_range}/{total_pages}…"
        job["progress"] = int((batch_start / total_pages) * 90)  # 0-90% pour la conversion

        # Prépare le contenu multimodal
        content = [PAGE_PROMPT]
        for page_img in batch:
            img_bytes = await loop.run_in_executor(None, _page_to_jpeg_bytes, page_img)
            content.append({
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode(),
            })

        try:
            response = await model.generate_content_async(content)
            chunk = response.text.strip()
            if chunk:
                chunks.append(chunk)
            logger.info(f"Batch {page_range} OK ({len(chunk)} chars)")
        except Exception as e:
            logger.error(f"Batch {page_range} échoué : {e}")
            chunks.append(f"\n\n<!-- Erreur page {page_range} : {e} -->\n\n")

        # Rate limiting (free tier : 15 RPM)
        if batch_start + batch_size < total_pages:
            await asyncio.sleep(RATE_LIMIT_DELAY)

    job["progress"] = 95
    job["step"] = "Assemblage du Markdown…"

    separator = "\n\n---\n\n"
    return separator.join(chunks)


async def extract_images(pdf_path: Path, output_dir: Path) -> int:
    """
    Extrait les images du PDF via pdfimages (poppler).
    Retourne le nombre d'images extraites.
    """
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "pdfimages", "-png", str(pdf_path), str(images_dir / "img"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    count = len(list(images_dir.glob("*.png")))
    logger.info(f"{count} images extraites")
    return count
