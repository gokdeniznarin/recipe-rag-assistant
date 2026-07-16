FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# torch'u önce CPU-only kur — aksi halde sentence-transformers ~2GB'lık gereksiz
# NVIDIA/CUDA tekerleklerini çeker (container'da GPU yok). --timeout/--retries
# dengesiz bağlantıda kopan indirmeleri toparlar.
RUN pip install --no-cache-dir --timeout 120 --retries 10 \
    torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]