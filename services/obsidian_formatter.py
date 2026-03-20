"""
Obsidian Formatter
==================
Post-traitement LLM du Markdown généré par Marker.
Utilise le skill obsidian-markdown de kepano comme system prompt.

Variables d'env :
  OPENROUTER_API_KEY  — clé OpenRouter (obligatoire)
  OPENROUTER_MODEL    — modèle à utiliser (défaut: google/gemini-flash-1.5)
  OPENROUTER_BASE_URL — base URL (défaut: https://openrouter.ai/api/v1)
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_MODEL       = "google/gemini-flash-1.5"

# ── Skill obsidian-markdown (kepano/obsidian-skills) ─────────────────────────
OBSIDIAN_SKILL = """
# Obsidian Flavored Markdown Skill

Create and edit valid Obsidian Flavored Markdown. Obsidian extends CommonMark and GFM with wikilinks, embeds, callouts, properties, comments, and other syntax.

## Workflow: Creating an Obsidian Note
1. Add frontmatter with properties (title, author, year, tags, type) at the top.
2. Write content using standard Markdown for structure, plus Obsidian-specific syntax.
3. Link related concepts using wikilinks ([[concept]]) for internal vault connections.
4. Add callouts for key insights, warnings, or summaries.

## Internal Links (Wikilinks)
[[Note Name]]               Link to note
[[Note Name|Display Text]]  Custom display text

## Callouts
> [!abstract] Summary
> Brief summary of the content.

> [!note]
> Key insight or important information.

> [!tip]
> Practical recommendation or takeaway.

> [!warning]
> Important caveat or limitation.

Common types: note, tip, warning, info, example, quote, abstract, summary

## Properties (Frontmatter)
---
title: Book Title
author: Author Name
year: 2024
type: livre
tags:
  - topic1
  - topic2
status: lu
rating:
---

## Tags
Tags can contain letters, numbers, underscores, hyphens. Use plural form (#voyages not #voyage).

## Obsidian-Specific Formatting
==Highlighted text==   Highlight syntax
"""

SYSTEM_PROMPT = f"""{OBSIDIAN_SKILL}

---

You are an Obsidian note formatter. Your task is to transform raw Markdown (extracted from a PDF by Marker) into a clean, well-structured Obsidian note.

Rules:
1. Extract metadata from the content and write a complete YAML frontmatter block (title, author, year, type: livre, tags, status: non-lu, rating: empty).
2. Add a `> [!abstract]` callout right after the title with a 3-5 sentence summary of the book.
3. Preserve ALL original content — do not summarize chapters or remove text.
4. Fix heading hierarchy if broken (ensure logical H1 > H2 > H3 structure).
5. Add `> [!note]` callouts for key concepts or important passages (max 5 per document).
6. Use [[wikilinks]] for key concepts, author names, and topics that might be notes in a vault.
7. Clean up OCR artifacts (repeated headers/footers, page numbers, broken sentences across pages).
8. Tags must be in French and plural (#philosophies, #developpement-personnel, etc.).
9. Return ONLY the formatted Markdown. No explanation, no preamble.
"""


async def format_for_obsidian(markdown_content: str, model: str | None = None) -> tuple[str, int, int]:
    """
    Retourne (formatted_content, tokens_input, tokens_output).
    """
    """
    Envoie le contenu Markdown à OpenRouter pour reformatage Obsidian.

    - N'envoie que les 8000 premiers tokens (~6000 mots) pour extraire les métadonnées
      et structurer l'intro. Le reste du document est conservé tel quel.
    - Retourne le contenu formaté.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY absent — formatage Obsidian ignoré.")
        return markdown_content, 0, 0

    selected_model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)

    # Limite : on envoie les 8000 premiers caractères pour l'extraction metadata + intro
    # Le reste est ajouté tel quel après le retour LLM
    CHAR_LIMIT = 8000
    head = markdown_content[:CHAR_LIMIT]
    tail = markdown_content[CHAR_LIMIT:] if len(markdown_content) > CHAR_LIMIT else ""

    user_message = f"""Format this Markdown content as an Obsidian note.
{'Note: this is the beginning of a long document. Format only this section (add frontmatter, summary callout, fix structure). The rest of the document will be appended unchanged.' if tail else ''}

<content>
{head}
</content>"""

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Thomasjarrossay/MarkerUI",
                    "X-Title": "MarkerUI",
                },
                json={
                    "model": selected_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_message},
                    ],
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            data = response.json()
            formatted = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens_in  = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            logger.info(f"Formatage Obsidian OK — modèle: {selected_model} | tokens: {tokens_in}→{tokens_out}")

            if tail:
                formatted = formatted.rstrip() + "\n\n---\n\n" + tail

            return formatted, tokens_in, tokens_out

    except httpx.HTTPStatusError as e:
        logger.error(f"OpenRouter HTTP error {e.response.status_code}: {e.response.text[:300]}")
        return markdown_content, 0, 0
    except Exception as e:
        logger.error(f"Erreur formatage Obsidian : {e}")
        return markdown_content, 0, 0
