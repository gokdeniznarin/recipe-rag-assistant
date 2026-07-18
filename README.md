# Recipe RAG Assistant — API

RAG tabanlı yemek tarifi öneri uygulamasının backend'i (FastAPI). Kullanıcı metin
ya da fotoğrafla arama yapıyor; sistem uygun tarifleri semantic search + metadata
filtreleme ile bulup Google Gemini ile gerekçelendiriyor.

Bu repo **API**'yi barındırıyor. Frontend ayrı olarak (Vercel) sunuluyor.

## Mimari
- **FastAPI** + `uvicorn`
- **Tarifler:** image'a gömülü ChromaDB (`api/chroma_data/`, salt-okunur, ONNX embedding)
- **Favoriler:** Firestore
- **Kimlik:** Firebase Auth (ID token doğrulama)
- **LLM:** Google Gemini (`gemini-2.5-flash`)

Backend stateless — kalıcı disk gerektirmez, tek Docker container olarak çalışır.

## Deploy
Kökteki `Dockerfile` build ediliyor; uygulama `$PORT` (yoksa 8080) portunu dinliyor.
Docker destekleyen herhangi bir platforma (ör. Render) konabilir. Gereken iki
environment variable:

- `GEMINI_API_KEY` — Google Gemini API anahtarı
- `FIREBASE_CREDENTIALS_JSON` — Firebase service-account JSON'ının **tam içeriği**
  (dosya değil, metin olarak yapıştırılır)

## Yerel geliştirme
`docker compose up -d --build` — API `localhost:8080`'de. Yerelde anahtarlar
`.env` (Gemini) ve `api/firebase-key.json` (Firebase) üzerinden okunuyor; ikisi de
`.gitignore`'da, repoya girmez.
