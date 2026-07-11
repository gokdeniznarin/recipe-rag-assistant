# Recipe RAG Assistant — Project Context

## Proje Özeti
Üniversite stajı kapsamında geliştirilen, RAG (Retrieval-Augmented Generation) tabanlı bir yemek tarifi öneri web uygulaması. Kullanıcı metin ile ("glutensiz ve hızlı bir tavuk yemeği") ya da kamera ile (dolap/malzeme fotoğrafı çekerek) arama yapabiliyor, sistem uygun tarifleri LLM aracılığıyla önerip gerekçelendiriyor.

## Teknoloji Kararları
- **Backend:** Python, FastAPI
- **Veritabanı:** Sadece ChromaDB (tek veritabanı kararı — hem semantic search hem metadata filtreleme aynı yerde yapılıyor, MongoDB kullanılmıyor)
- **Embedding modeli:** sentence-transformers (İngilizce arayüz kararı verildiği için çok dilli model şart değil)
- **LLM:** Google Gemini API (gemini-2.5-flash, `google-genai` kütüphanesi kullanılıyor — eski `google-generativeai` deprecated olduğu için güncel kütüphaneye geçildi)
- **Kimlik doğrulama:** JWT (kayıt/giriş sistemi)
- **Kamera:** Tarayıcı `getUserMedia` API'si ile fotoğraf çekme, backend'e gönderip Claude vision ile malzeme tanıma
- **Konteynerleştirme:** Docker + Docker Compose
- **Dil:** Arayüz İngilizce (dataset de İngilizce, tutarlılık için)
- **Git:** Conventional commits, İngilizce mesajlar, scope kullanımı (örn. `feat(data): ...`, `fix(auth): ...`)

## Dataset
- **Kaynak:** Kaggle "Food.com - Recipes and Reviews" (522,517 tarif, 28 kolon)
- **Kullanılan alt küme:** Rastgele seçilmiş 5000 tarif (`random_state=42`), temizlik sonrası ~4886 tarif kaldı
- **Kullanılan kolonlar:** RecipeId, Name, RecipeCategory, CookTime/PrepTime/TotalTime (ISO 8601 format, dakikaya çevrildi), RecipeIngredientParts (R vector formatında, regex ile parse edildi), 9 makro besin kolonu (Calories, FatContent, SaturatedFatContent, CholesterolContent, SodiumContent, CarbohydrateContent, FiberContent, SugarContent, ProteinContent — hepsi %0 eksik veri)

## Veri Temizleme Mantığı (`ingestion/clean_data.py`)
- HTML kaçış karakterleri temizleniyor (`&ldquo;` → `"`)
- Malzeme listesi R format'tan (`c("a", "b")`) Python listesine çevriliyor
- Süreler ISO 8601'den (`PT24H45M`) dakikaya çevriliyor
- **Diyet etiketleri** (`gluten_free`, `dairy_free`, `nut_free`, `vegetarian`, `pescatarian`, `vegan`) malzeme listesinden VE kategori bilgisinden kural bazlı çıkarılıyor — kategori, malzeme eksikliğine karşı "güvenlik ağı" olarak kullanılıyor (örn. kategori "Poultry" ise malzemede "turkey" geçmese bile et var sayılıyor)
- Bu etiketler %100 doğru değil, "otomatik tahmin" olarak sunum ve arayüzde belirtilecek
- `validate_tags.py` scripti ile tutarlılık kontrolleri yapıldı (et-vejetaryen, süt-dairy_free, ekmek-gluten_free, kuruyemiş-nut_free çelişkileri, süre tutarlılığı, malzeme sayısı anomalisi) — şu an tüm kontroller 0 çelişki veriyor
- 2'den az malzemeli tarifler filtreleniyor (embedding kalitesi için)
- Her tarif için embedding'e verilecek zengin açıklama metni (`description_for_embedding`) oluşturuluyor: isim + kategori + malzemeler + süre + diyet etiketleri

## Mimari Prensipler
- Basit tutulmaya çalışılıyor — design pattern'ler zorlanmıyor, sadece gerçekten ihtiyaç olduğunda (örn. Repository Pattern, iki veritabanı olsaydı gerekecekti ama artık tek DB olduğu için bile gerekmeyebilir)
- FastAPI'de tek ana endpoint mantığı: `/api/recipes/search` (metin), `/api/recipes/from-image` (fotoğraf)
- Hybrid search: kullanıcı sorgusundan kural bazlı ya da LLM ile filtre (diyet, süre) çıkarılıp ChromaDB'nin `where` parametresiyle metadata filtreleme + semantic search birlikte yapılıyor

## Proje Planı (1 aylık, 4 hafta)
- **Hafta 1 (şu an buradayız):** Veri hazırlama — TAMAMLANDI (dataset indirme, temizleme, diyet etiketleme, doğrulama). Sıradaki adım: ChromaDB'yi Docker ile kurup temiz veriyi embedding'e çevirip yüklemek.
- **Hafta 2:** FastAPI backend, filtre çıkarımı, LLM entegrasyonu, arama endpoint'i
- **Hafta 3:** JWT (kayıt/giriş), fotoğraftan malzeme tanıma endpoint'i
- **Hafta 4:** Frontend (metin + kamera sekmeleri), responsive tasarım, Docker Compose ile tam entegrasyon, test, README

## Şu Ana Kadar Tamamlanan Dosyalar (güncel)
- `ingestion/explore_data.py` — dataset keşfi
- `ingestion/clean_data.py` — temizleme pipeline'ı, recipes_cleaned.csv üretiyor
- `ingestion/validate_tags.py` — diyet etiketi ve veri kalitesi doğrulama scripti
- `ingestion/load_to_chromadb.py` — embedding üretme ve ChromaDB'ye yükleme
- `ingestion/test_search.py` — ChromaDB arama testleri
- `api/main.py` — FastAPI backend, /api/recipes/search endpoint'i
- `api/filters.py` — kullanıcı sorgusundan diyet/süre/kalori filtresi çıkarımı
- `api/llm.py` — Gemini API ile LLM cevap üretimi (yeni ekleniyor)
- `docker-compose.yml` — ChromaDB servisi

## Henüz Yapılmadı
- ChromaDB Docker kurulumu ve veri yükleme
- FastAPI backend
- JWT auth
- Kamera/vision entegrasyonu
- Frontend
- GitHub'a bağlama (Faz 1 bitince yapılacak — henüz sadece lokal Git kullanılıyor)

## Güncel Durum (Faz 3 devam ediyor)
- 3.1 Kayıt endpoint'i tamamlandı
- 3.2 Giriş endpoint'i tamamlandı (JWT token üretimi çalışıyor)
- Sıradaki adım: 3.3 - arama endpoint'ini JWT ile koruma

## Arama Akışı Kararı (Faz 3/4)
Üç bağımsız kullanım senaryosu:
1. Sadece metin → /api/recipes/search
2. Sadece fotoğraf (metin boş) → /api/recipes/from-image
3. Fotoğraf + opsiyonel ek metin → /api/recipes/from-image (additional_text dolu)
Fotoğraftan tanınan malzemeler asla otomatik olarak text kutusuna yazılmaz, 
ayrı bir "Detected: ..." alanında gösterilir. Text kutusu her zaman kullanıcının 
kontrolünde, bağımsız kalır.


## Bilinen Sınırlama: Swagger UI + Custom Header
POST /api/recipes/search endpoint'i JWT korumalı (Header parametresi kullanıyor). 
Swagger UI'nin "Try it out" arayüzü bu header'ı isteğe eklemede sorun yaşıyor 
(muhtemelen FastAPI/Swagger versiyon uyumsuzluğu). Backend'in kendisi doğru 
çalışıyor - PowerShell Invoke-RestMethod ile doğrulandı. Gerçek testler için 
Swagger UI yerine PowerShell/curl.exe veya ileride yazılacak frontend kullanılmalı.