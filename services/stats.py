"""
Stats Manager
=============
Persistance des statistiques d'utilisation dans /app/data/stats.json.
Thread-safe via asyncio.Lock.
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

STATS_FILE = Path("/app/data/stats.json")

# Pricing OpenRouter (USD per 1M tokens, input/output)
MODEL_PRICING = {
    "google/gemini-flash-1.5":          (0.075,  0.30),
    "google/gemini-pro-1.5":            (1.25,   5.00),
    "anthropic/claude-3-5-haiku":       (0.80,   4.00),
    "anthropic/claude-3-5-sonnet":      (3.00,  15.00),
    "openai/gpt-4o-mini":               (0.15,   0.60),
    "openai/gpt-4o":                    (2.50,  10.00),
    "meta-llama/llama-3.3-70b-instruct":(0.12,   0.30),
}

DEFAULT_STATS = {
    "total_conversions":    0,
    "total_failures":       0,
    "total_pages":          0,
    "total_size_mb":        0.0,
    "total_duration_s":     0,
    "llm_calls":            0,
    "llm_tokens_input":     0,
    "llm_tokens_output":    0,
    "llm_cost_usd":         0.0,
    "last_conversion":      None,
}

_lock = asyncio.Lock()


def _load() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except Exception:
            pass
    return DEFAULT_STATS.copy()


def _save(stats: dict):
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))


async def record_conversion(
    success: bool,
    pages: int = 0,
    size_mb: float = 0.0,
    duration_s: int = 0,
):
    async with _lock:
        s = _load()
        if success:
            s["total_conversions"] += 1
            s["total_pages"]       += pages
            s["total_size_mb"]     = round(s["total_size_mb"] + size_mb, 2)
            s["total_duration_s"]  += duration_s
            s["last_conversion"]   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        else:
            s["total_failures"] += 1
        _save(s)


async def record_llm_call(model: str, tokens_input: int, tokens_output: int):
    async with _lock:
        s = _load()
        s["llm_calls"]         += 1
        s["llm_tokens_input"]  += tokens_input
        s["llm_tokens_output"] += tokens_output

        price_in, price_out = MODEL_PRICING.get(model, (1.0, 3.0))
        cost = (tokens_input * price_in + tokens_output * price_out) / 1_000_000
        s["llm_cost_usd"] = round(s["llm_cost_usd"] + cost, 6)
        _save(s)


def get_stats() -> dict:
    s = _load()
    total = s["total_conversions"]
    s["avg_duration_s"] = round(s["total_duration_s"] / total, 1) if total else 0
    s["success_rate"]   = round(total / max(total + s["total_failures"], 1) * 100, 1)
    return s
