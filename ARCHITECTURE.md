# ARCHITECTURE — MarkerUI
> Cartographie relationnelle complète. Mettre à jour après chaque modification structurante.
> Dernière mise à jour : 2026-03-20

---

## 1. Arbre des fonctionnalités

```
[CORE] Job Orchestrator (main.py)
 ├── [FEATURE] POST /api/convert → déclenche run_marker
 │   ├── [SUB] PDF validation → bloque si non-.pdf
 │   ├── [UTILITY] get_pdf_page_count → utilise pdfinfo CLI
 │   └── [HOOK] BackgroundTasks.add_task → déclenche run_marker
 │
 ├── [FEATURE] run_marker (background task)
 │   ├── [SUB] Étape 1 : marker_single CLI → génère .md + images
 │   ├── [SUB] Étape 2 : format_for_obsidian → optionnel, dépend de OPENROUTER_API_KEY
 │   │   └── [HOOK] record_llm_call → persiste dans stats.json
 │   ├── [SUB] Étape 3 : création .zip (output_subdir → job_dir)
 │   └── [HOOK] record_conversion → persiste dans stats.json
 │
 ├── [FEATURE] GET /api/status/{job_id} → polling frontend
 │   └── [SUB] Calcul elapsed live (time.time - started_at)
 │
 ├── [FEATURE] GET /api/download/{job_id} → FileResponse .zip
 │   └── [SUB] Guard : status == DONE requis
 │
 ├── [FEATURE] GET /api/stats → utilise get_stats()
 │   └── [SUB] Métriques dérivées (avg_duration, success_rate)
 │
 ├── [FEATURE] GET /api/models → liste + état clé OpenRouter
 └── [FEATURE] DELETE /api/job/{job_id} → cleanup filesystem + jobs dict

[FEATURE] Obsidian Formatter (services/obsidian_formatter.py)
 ├── [SUB] SYSTEM_PROMPT — skill kepano/obsidian-markdown embarqué
 ├── [SUB] Truncation 8000 chars → LLM ne traite que le début
 ├── [SUB] Tail re-assembly → reste du doc ajouté inchangé après `---`
 └── [SUB] Error fallback → retourne markdown original si OpenRouter KO

[FEATURE] Stats Manager (services/stats.py)
 ├── [CORE] asyncio.Lock → thread-safety read-modify-write
 ├── [SUB] MODEL_PRICING dict → 7 modèles OpenRouter avec pricing input/output
 ├── [UTILITY] _load() / _save() → lecture/écriture stats.json
 ├── [FEATURE] record_conversion() → success/failure, pages, size, durée
 ├── [FEATURE] record_llm_call() → tokens + calcul coût USD
 └── [FEATURE] get_stats() → charge + calcule avg_duration, success_rate

[FEATURE] Frontend (static/)
 ├── [FEATURE] Settings Card (index.html + app.js)
 │   ├── [SUB] Obsidian Toggle → active/désactive formatage LLM
 │   │   └── [HOOK] onChange → toggle model-row visibility
 │   └── [SUB] Model Selector → dropdown 7 modèles (caché si toggle OFF)
 │       └── [HOOK] loadModels() → fetch /api/models au DOMContentLoaded
 │
 ├── [FEATURE] Upload Subsystem (app.js)
 │   ├── [SUB] Drop Zone → dragover / dragleave / drop / click handlers
 │   ├── [SUB] handleFile() → valide .pdf côté client
 │   └── [SUB] uploadFile() → POST /api/convert, récupère job_id + estimated_seconds
 │
 ├── [FEATURE] Polling Subsystem (app.js)
 │   ├── [SUB] startPolling() → setInterval 2s → GET /api/status/{job_id}
 │   ├── [SUB] Elapsed Timer → setInterval 1s → update UI + estimation restante
 │   └── [HOOK] if status==done → stopPolling() → showSuccess()
 │
 ├── [FEATURE] Stats Section (index.html + app.js)
 │   ├── [SUB] toggleStats() → collapsible, fetch /api/stats au clic
 │   └── [SUB] loadStats() → remplit 6 stat-cards
 │
 └── [UTILITY] UI Helpers (app.js)
     ├── showStatus() / showSuccess() / showError()
     ├── setProgress() → indeterminate animation ou valeur fixe
     ├── formatTime() → secondes → "Xm Ys"
     └── reset() → réinitialise tout l'état

[INFRASTRUCTURE] Dockerfile
 ├── [CORE] python:3.12-slim base
 ├── [SUB] libgomp1 + poppler-utils (apt-get)
 ├── [SUB] torch CPU-only (index-url pytorch.org/whl/cpu)
 ├── [SUB] requirements.txt install
 └── [HOOK] Model pre-warming → create_model_dict() au build
     └── Persiste dans /root/.cache/datalab/ (layer Docker)
```

---

## 2. Table des relations

| De | Type | Vers |
|---|---|---|
| `POST /api/convert` | déclenche | `run_marker()` (background) |
| `run_marker()` | utilise | `marker_single` CLI |
| `run_marker()` | utilise (optionnel) | `format_for_obsidian()` |
| `run_marker()` | persiste dans | `stats.json` via `record_conversion()` |
| `format_for_obsidian()` | appelle | OpenRouter API `/chat/completions` |
| `format_for_obsidian()` | retourne résultat à | `run_marker()` (tokens + markdown) |
| `run_marker()` | persiste dans | `stats.json` via `record_llm_call()` |
| `GET /api/status` | lit | `jobs` dict (in-memory) |
| `GET /api/download` | lit | `/app/outputs/{job_id}/*.zip` |
| `GET /api/stats` | appelle | `get_stats()` → lit `stats.json` |
| `DELETE /api/job` | supprime | `/app/outputs/{job_id}/` + `jobs` entry |
| `get_pdf_page_count()` | utilise | `pdfinfo` CLI (poppler-utils) |
| `app.js:uploadFile()` | appelle | `POST /api/convert` |
| `app.js:startPolling()` | appelle | `GET /api/status/{job_id}` (2s) |
| `app.js:downloadResult()` | appelle | `GET /api/download/{job_id}` |
| `app.js:downloadResult()` | déclenche (5s delay) | `DELETE /api/job/{job_id}` |
| `app.js:loadModels()` | appelle | `GET /api/models` |
| `app.js:loadStats()` | appelle | `GET /api/stats` |
| `obsidianToggle.onChange` | déclenche | `modelRow` visibility toggle |
| `Dockerfile pre-warm` | persiste dans | `/root/.cache/datalab/` |
| `stats.py:_save()` | persiste dans | `/app/data/stats.json` |

---

## 3. Fichiers critiques par fonctionnalité

| Fonctionnalité | Fichiers impliqués |
|---|---|
| Conversion PDF → MD | `main.py` (run_marker), `Dockerfile` (marker_single install + pre-warm) |
| Formatage Obsidian | `services/obsidian_formatter.py`, `main.py` (run_marker étape 2) |
| Stats & coûts | `services/stats.py`, `main.py` (/api/stats endpoint) |
| Upload & validation | `main.py` (/api/convert), `static/app.js` (handleFile, uploadFile) |
| Polling & timer | `static/app.js` (startPolling, startElapsedTimer), `main.py` (/api/status) |
| Estimation durée | `main.py` (get_pdf_page_count), `static/app.js` (estimatedSeconds) |
| Sélecteur modèle | `main.py` (AVAILABLE_MODELS, /api/models), `static/app.js` (loadModels), `static/index.html` |
| Download | `main.py` (/api/download), `static/app.js` (downloadResult) |
| Cleanup | `main.py` (DELETE /api/job), `static/app.js` (setTimeout 5s) |
| Persistance stats | `services/stats.py`, volume Docker `/app/data/` |
| Cold start perf | `Dockerfile` (create_model_dict pre-warm), `/root/.cache/datalab/` |
| Design système | `static/style.css` (:root CSS variables) |

---

## 4. État & persistance

| Donnée | Stockage | Scope | Survit au restart |
|---|---|---|---|
| Jobs en cours | `jobs` dict (main.py) | Runtime | ❌ Non |
| Fichiers convertis | `/app/outputs/{job_id}/` | Job | ❌ Nettoyé après download |
| Stats d'usage | `/app/data/stats.json` | App | ✅ Oui (si volume monté) |
| Modèles Marker | `/root/.cache/datalab/` | Docker layer | ✅ Dans l'image |

> **Important :** Pour que les stats survivent aux redéploiements Coolify, monter un volume sur `/app/data`.

---

## 5. Points de vigilance (impact analysis)

| Si tu modifies... | Impact sur... |
|---|---|
| `run_marker()` dans main.py | Conversion entière, stats, formatage Obsidian |
| `obsidian_formatter.py` | Signature retour `(str, int, int)` → mettre à jour main.py |
| `AVAILABLE_MODELS` dans main.py | UI dropdown (sync automatique via /api/models) |
| `DEFAULT_STATS` dans stats.py | Risque de corruption si stats.json existant incompatible |
| `MODEL_PRICING` dans stats.py | Coûts affichés dans UI |
| CSS variables `:root` dans style.css | Tout le design système |
| Port Dockerfile (8000) | Variable PORT dans Coolify |
| `/app/data/` path | stats.py `STATS_FILE`, Dockerfile `mkdir` |
