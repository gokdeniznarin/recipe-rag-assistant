# Backend (FastAPI) image. Repo kökünden build edilir — hem docker-compose hem de
# Hugging Face Spaces bu tek Dockerfile'ı kullanır (HF, kökteki Dockerfile'ı arar).
# Build context repo kökü olduğu için yollar api/ ile başlıyor.
FROM python:3.13-slim

WORKDIR /app

COPY api/requirements.txt .
# --timeout/--retries dengesiz bağlantıda kopan indirmeleri toparlar.
RUN pip install --no-cache-dir --timeout 120 --retries 10 -r requirements.txt

# Embedding modelini (all-MiniLM-L6-v2, ONNX) build sırasında indirip image'a göm.
# Yoksa ChromaDB bunu ilk istekte indiriyor (~79MB, ölçüldü: ~70sn) ve canlıda
# her taze container başlangıcı o kadar gecikir.
RUN python -c "import chromadb.utils.embedding_functions as ef; ef.DefaultEmbeddingFunction()(['warmup'])"

# Sadece api/ image'a giriyor (frontend Vercel'e, ingestion dev-only). Gizli anahtar
# ve gereksiz dosyalar .dockerignore ile dışarıda tutuluyor — özellikle
# api/firebase-key.json ASLA image katmanına girmemeli.
COPY api/ .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
