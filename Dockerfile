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
# ~79MB'lık indirme ara sıra takılıyor (ölçüldü: aynı adım bir denemede çöktü,
# diğerinde geçti). Tek deneme HF gibi bir build sunucusunda build'i kırabilir —
# 5 kez deneyip hepsi başarısız olursa build'i bilerek fail ettir.
RUN for i in 1 2 3 4 5; do \
      if python -c "import chromadb.utils.embedding_functions as ef; ef.DefaultEmbeddingFunction()(['warmup'])"; then exit 0; fi; \
      echo "ONNX model indirme denemesi $i basarisiz, 5sn sonra tekrar..." >&2; sleep 5; \
    done; \
    echo "ONNX model 5 denemede de inmedi" >&2; exit 1

# Sadece api/ image'a giriyor (frontend Vercel'e, ingestion dev-only). Gizli anahtar
# ve gereksiz dosyalar .dockerignore ile dışarıda tutuluyor — özellikle
# api/firebase-key.json ASLA image katmanına girmemeli.
COPY api/ .

EXPOSE 8080

# Portu ortamdan al: Render (ve çoğu PaaS) dinlenecek portu $PORT ile bildiriyor.
# Yerelde $PORT tanımlı değil → 8080'e düşüyor, docker-compose eskisi gibi çalışıyor.
# sh -c + exec: değişken genişlesin ama uvicorn PID 1 kalsın (düzgün kapanma/sinyal).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
