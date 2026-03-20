FROM python:3.12-slim

WORKDIR /app

# Dépendances système (poppler pour PDF, libgomp pour PyTorch)
RUN apt-get update && apt-get install -y \
    libgomp1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only (évite de télécharger 2GB de CUDA inutile sur VPS)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Dépendances app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY . .

RUN mkdir -p uploads_temp outputs

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
