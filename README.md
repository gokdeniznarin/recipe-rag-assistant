---
title: Recipe RAG Assistant API
emoji: 🍳
colorFrom: green
colorTo: orange
sdk: docker
app_port: 8080
pinned: false
---

# Recipe RAG Assistant — API

RAG tabanlı yemek tarifi öneri uygulamasının backend'i (FastAPI). Kullanıcı metin
ya da fotoğrafla arama yapıyor; sistem uygun tarifleri semantic search + metadata
filtreleme ile bulup Google Gemini ile gerekçelendiriyor.

Bu Space yalnızca **API**'yi barındırıyor. Frontend ayrı olarak (Vercel) sunuluyor.

## Mimari
- **FastAPI** + `uvicorn`, port 8080
- **Tarifler:** image'a gömülü ChromaDB (`api/chroma_data/`, salt-okunur, ONNX embedding)
- **Favoriler:** Firestore
- **Kimlik:** Firebase Auth (ID token doğrulama)
- **LLM:** Google Gemini (`gemini-2.5-flash`)

Backend stateless — kalıcı disk gerektirmez.

## Gerekli Secrets (HF Spaces → Settings → Secrets)
- `GEMINI_API_KEY` — Google Gemini API anahtarı
- `FIREBASE_CREDENTIALS_JSON` — Firebase service-account JSON'ının **tam içeriği**
  (dosya değil, metin olarak yapıştırılır)

## Yerel geliştirme
`docker compose up -d --build` — API `localhost:8080`'de. Yerelde anahtarlar
`.env` (Gemini) ve `api/firebase-key.json` (Firebase) üzerinden okunuyor; ikisi de
`.gitignore`'da, repoya girmez.
