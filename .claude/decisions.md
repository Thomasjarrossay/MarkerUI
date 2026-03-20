# Decisions — MarkerUI
> Journal des décisions techniques. Ajouter une entrée après chaque choix structurant.
> Ne jamais écraser — toujours append.

---

## 2026-03-20 — Déploiement : Nixpacks → Dockerfile

**Contexte :** Coolify utilise Nixpacks par défaut pour détecter et builder l'environnement Python.

**Tentatives :**
- Nixpacks auto-détection → `pip: command not found` (Python Nix sans pip dans PATH)
- `python3 -m pip install` → `No module named pip` (Python Nix ne l'inclut pas)

**Décision :** Remplacement de `nixpacks.toml` par un `Dockerfile` complet avec `python:3.12-slim`. Donne un contrôle total sur l'environnement, pip disponible par défaut.

**À ne plus retenter :** Utiliser Nixpacks pour ce projet — Python Nix est incompatible avec pip standard.

---

## 2026-03-20 — Vector DB : Qdrant → Chroma embarqué

**Contexte :** GeminiRAG utilisait Qdrant. Après déploiement Coolify, connexion refusée (`[Errno 111] Connection refused`) sur `https://qdrant.jrs-ops.fr`.

**Tentatives :**
- Qdrant self-hosted sur même serveur Coolify → réseau Docker non configuré
- URL publique depuis container → loopback non résolu

**Décision :** Migration vers Chroma embarqué (`chromadb.PersistentClient`). Tourne dans le container, aucun service externe, persistance via volume Docker. Confirmé par deux articles (classé 1er/2e des alternatives vectorielles).

**À ne plus retenter :** Connecter Qdrant self-hosted sans configurer explicitement le réseau Docker partagé dans Coolify. Si Qdrant requis → utiliser Qdrant Cloud gratuit.

---

## 2026-03-20 — Conversion synchrone → Background jobs + polling

**Contexte :** `POST /api/convert` attendait la fin de `marker_single` avant de retourner → NetworkError browser (connection dropped) + 504 Gateway Timeout Nginx (timeout 60s < durée conversion).

**Tentatives :**
- Conversion synchrone dans l'endpoint → timeout garanti sur gros PDFs
- Augmentation timeout Nginx → contournement, pas une solution

**Décision :** Architecture background jobs : `POST /api/convert` retourne `job_id` immédiatement, `run_marker()` tourne en `BackgroundTask`, frontend poll `GET /api/status/{job_id}` toutes les 2s. Découple complètement la durée de conversion du timeout HTTP.

**À ne plus retenter :** Traitement synchrone de marker_single dans un endpoint HTTP — incompatible avec tout proxy (Nginx, Traefik) ayant un timeout < 3-5 min.

---

## 2026-03-20 — Optimisation cold start : pre-warm modèles au build

**Contexte :** Premier appel à `marker_single` déclenchait le téléchargement de 1.35 GB de modèles → 1m48s bloquant, job échouait avec returncode != 0.

**Tentatives :**
- Laisser le download au runtime → timeout systématique au premier PDF
- `marker_single --help` au build → ne déclenche pas le download des modèles

**Décision :** `python3 -c "from marker.models import create_model_dict; create_model_dict()"` dans le Dockerfile. Les modèles sont cachés dans `/root/.cache/datalab/` dans l'image. Build plus long une fois, runtime instantané. Avec `|| echo` pour que le build ne bloque pas si l'API change.

**À ne plus retenter :** Lancer un PDF test dans le Dockerfile pour pre-warm — nécessite un vrai PDF, fragile. L'import Python direct est plus fiable.
