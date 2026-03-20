FROM python:3.12-slim

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y \
    libgomp1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Dépendances app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY . .

RUN mkdir -p uploads_temp outputs

# Pré-télécharge les modèles Marker au build (évite le cold start à chaque conversion)
# Les modèles sont cachés dans /root/.cache/datalab/ et réutilisés au runtime.
RUN python3 -c "from marker.models import create_model_dict; create_model_dict(); print('Marker models ready')" \
    || echo "Model pre-warming failed — will download on first use"

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
