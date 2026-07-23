# Recipe RAG Assistant — Project Context

## Proje Özeti
Üniversite stajı kapsamında geliştirilen, RAG (Retrieval-Augmented Generation) tabanlı bir yemek tarifi öneri web uygulaması. Kullanıcı metin ile ("glutensiz ve hızlı bir tavuk yemeği") ya da kamera ile (dolap/malzeme fotoğrafı çekerek) arama yapabiliyor, sistem uygun tarifleri LLM aracılığıyla önerip gerekçelendiriyor.

## Teknoloji Kararları
- **Backend:** Python, FastAPI
- **Veritabanı:** İki yer, ama **rolleri kesin ayrı** (Faz 8–9'da netleşti): **ChromaDB** yalnızca tarifler için — semantic search + metadata filtreleme aynı yerde yapılıyor (MongoDB kullanılmadı), veri salt-okunur ve image'a gömülü, ortada sunucu yok. **Firestore** ise çalışma anında değişen tek veri olan favoriler için. Eski "sadece ChromaDB" kararı favorileri de oraya koyuyordu; bu yanlıştı — her favori kaydına sahte bir `[[0.0] * 384]` embedding yazılıyordu, yani vektör veritabanı anahtar-değer deposu gibi kullanılıyordu. Ayrıca kalıcı disk ihtiyacının tek sebebi buydu ve deploy'u kilitliyordu.
- **Embedding modeli:** `all-MiniLM-L6-v2` (İngilizce arayüz kararı verildiği için çok dilli model şart değil). Model **ChromaDB'nin kendi varsayılan embedding fonksiyonu** (`DefaultEmbeddingFunction`) üzerinden, **ONNX** motoruyla çalışıyor — `sentence-transformers` + `torch` kurulumu kaldırıldı (bkz. Faz 7). Kod artık embedding'i elle üretmiyor: `collection.query(query_texts=[...])` ile metni doğrudan ChromaDB'ye veriyor, embedding'i o üretiyor.
- **LLM:** Google Gemini API, **çoklu model** (Faz 11b — kota model başına olduğu için sırayla denenen liste; **Faz 14'te 5 modele çıkarıldı ve vision sırası düzeltildi**; bkz. `llm.py` `COMMENTARY_MODELS` / `VISION_MODELS`), `google-genai` kütüphanesi (eski `google-generativeai` deprecated olduğu için güncel kütüphaneye geçildi). Model seçimi iki kez değişti: önce `gemini-2.5-flash` → `gemini-flash-latest` (ikinci API key'in projesinde 2.5'e erişim kapalıydı + alias deprecation'a karşı güvenliydi), sonra **geri `gemini-2.5-flash`'a** — çünkü alias'ın işaret ettiği model free tier'da sürekli **503 (overloaded)** veriyordu, SDK retry'ları her aramayı ~20sn'ye çıkarıyordu. Ölçüm: alias 20.1sn, `gemini-2.5-flash` ort. 3.5sn (**~6x**). Ödünleşim kabul edildi: sabit sürüm ileride deprecate olabilir, o zaman güncel sürüme taşınır (hata mesajı net gelir).
- **Frontend:** Sade HTML/CSS/JS (React/Next.js tercih edilmedi — React öğrenme eğrisi kalan sürede risk yaratıyordu, projenin asıl değeri backend RAG pipeline'ında). Sayfa başına ayrı HTML dosyaları, ortak CSS tek dosyada, her sayfanın kendi JS dosyası. Sayfa yönlendirme klasik `<a href>` ile — SPA değil, MPA. Vercel'e statik site olarak deploy edilebilir yapıda.
- **Frontend tasarım:** Koyu zeytin yeşili (`#2D3B2D`) + krem (`#F5F0E8`) + sıcak turuncu aksan (`#E8824A`) paleti, Playfair Display (serif başlıklar, yemek dergisi hissi) + Inter (UI). Merkezi CSS tokens ile tutarlı stil.
- **Kimlik doğrulama:** **Firebase Auth** (email/şifre + Google). Önceki custom JWT + bcrypt + manuel Google doğrulama kurulumundan tamamen geçildi (bkz. Faz 6). Şifre bizim sunucumuza hiç ulaşmıyor: tarayıcı doğrudan Firebase ile konuşuyor, `getIdToken()` ile alınan ID token her istekte `Authorization: Bearer` header'ına konuyor ve süresi dolunca SDK sessizce yeniliyor. Backend (`api/auth.py`) yalnızca Admin SDK ile `verify_id_token()` yapıp e-postayı çıkarıyor — başka hiçbir kimlik mantığı yok. Frontend Firebase JS SDK'nın **compat** build'ini kullanıyor (mevcut global-script/MPA mimarisini korumak için; modüler SDK sayfalar arası global paylaşımı bozardı). Kullanıcılar artık ChromaDB'de değil Firebase'de. Favoriler e-posta anahtarlı olduğu için migrasyondan hiç etkilenmedi.
- **Kamera:** Tarayıcı `getUserMedia` API'si ile fotoğraf çekme, base64 olarak backend'e gönderilip Gemini vision ile malzeme tanıma (aynı Gemini modeli hem metin üretimi hem vision için kullanılıyor)
- **Sesli arama:** Web Speech API (`SpeechRecognition`/`webkitSpeechRecognition`), `search.js` içinde mikrofon butonuna bağlı. Tarayıcı desteklemiyorsa (polyfill yok) buton feature-detection ile gizleniyor. Tanınan metin doğrudan arama kutusuna yazılıyor (kamera akışındaki "asla otomatik yazma" kararından farklı — burada kullanıcı zaten sesle metin girmek istiyor).
- **Konteynerleştirme:** Docker + Docker Compose — **2 servis** (Faz 9'a kadar 3'tü, `chromadb` kalktı): `api` (`python:3.13-slim`, `uvicorn`, `.env` dosyası `env_file` ile aktarılıyor, tarifleri image'a gömülü `chroma_data/`'dan okuyor, favoriler Firestore'da — **stateless**), `frontend` (`nginx:alpine`, sade HTML/CSS/JS olduğu için build adımı yok). Firebase geçişiyle gelen eklemeler: yerelde `api` servisine service-account anahtarı salt-okunur mount ediliyor (`GOOGLE_APPLICATION_CREDENTIALS` ile gösteriliyor; canlıda ise dosya yok, `FIREBASE_CREDENTIALS_JSON` env var'ı kullanılıyor), `frontend` klasörü bind-mount edildiği için JS/HTML değişikliği rebuild istemiyor (sadece `docker restart recipe_frontend` — nginx bu mount'ta dosyayı önbelleğe alabiliyor).
  **Dockerfile repo KÖKÜNDE, tek tane** (Faz 10; önceden `api/Dockerfile`'dı): hem `docker-compose` hem Render aynı dosyayı kullanıyor — "yerelde build ettiğim = canlıya giden" garantisi. İki ayrı Dockerfile tutulmadı çünkü kaçınılmaz olarak birbirinden ayrışırlar. Build context kök, ama image'a **sadece `api/`** kopyalanıyor (`COPY api/ .`).
  **Kökteki `.dockerignore` kritik güvenlik görevi görüyor:** `api/firebase-key.json` ve `.env`'i image dışında tutuyor (doğrulandı: build edilen image'da anahtar dosyası yok). Ayrıca `frontend/`, `ingestion/`, `*.csv` dışarıda — build context şişmesin.
  Faz 7'de torch kaldırıldı; Dockerfile ne CPU-only torch kuruyor ne `build-essential` istiyor. ONNX embedding modelini **build sırasında** indirip image'a gömüyor (yoksa ChromaDB ilk istekte indiriyor: ~79MB, ölçüldü ~70sn, her taze container başlangıcı o kadar gecikirdi). Bu indirme **5 denemelik retry** ile sarılı (Faz 10): sıfırdan build'de aynı adım bir denemede çöküp diğerinde geçti — geçici ağ titrekliği. Tek deneme olsaydı, Render/başka bir build sunucusundaki kötü bir an deploy'u sebepsiz kırardı. 5 deneme de başarısız olursa build bilerek fail eder (modelsiz image çıkmasın).
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
- **Diyet etiketleri** (`gluten_free`, `dairy_free`, `nut_free`, `vegetarian`, `pescatarian`, `vegan`) malzeme listesinden, kategori bilgisinden VE tarif adından kural bazlı çıkarılıyor — kategori ve tarif adı, malzeme eksikliğine karşı "güvenlik ağı" olarak kullanılıyor (örn. kategori "Poultry" ise malzemede "turkey" geçmese bile et var sayılıyor; adı "Chicken Salad" olup malzemesinde chicken geçmeyen tarif de et sayılıyor). Tarif adı kontrolünde bir istisna var: ad içinde bitki bazlı bir sinyal (`vegan`, `vegetarian`, `plant-based`, `meatless`, `veggie` vb.) varsa addaki et kelimeleri taklit ürün sayılıp yok sayılıyor (örn. "Vegan Chicken Nuggets" yanlışlıkla et olarak işaretlenmiyor)
- Bu etiketler %100 doğru değil, "otomatik tahmin" olarak sunum ve arayüzde belirtilecek
- `validate_tags.py` scripti ile tutarlılık kontrolleri yapıldı (et-vejetaryen, süt-dairy_free, ekmek-gluten_free, kuruyemiş-nut_free çelişkileri, süre tutarlılığı, malzeme sayısı anomalisi) — şu an tüm kontroller 0 çelişki veriyor
- 2'den az malzemeli tarifler filtreleniyor (embedding kalitesi için)
- Her tarif için embedding'e verilecek zengin açıklama metni (`description_for_embedding`) oluşturuluyor: isim + kategori + malzemeler + süre + diyet etiketleri

## Mimari Prensipler
- Basit tutulmaya çalışılıyor — design pattern'ler zorlanmıyor, sadece gerçekten ihtiyaç olduğunda (örn. Repository Pattern, iki veritabanı olsaydı gerekecekti ama artık tek DB olduğu için bile gerekmeyebilir)
- FastAPI'de tek ana endpoint mantığı: `/api/recipes/search` (metin), `/api/recipes/from-image` (fotoğraf)
- Hybrid search: kullanıcı sorgusundan kural bazlı ya da LLM ile filtre (diyet, süre) çıkarılıp ChromaDB'nin `where` parametresiyle metadata filtreleme + semantic search birlikte yapılıyor

## Proje Planı (1 aylık, 4+ hafta)
- **Hafta 1:** Veri hazırlama ✅ (dataset indirme, temizleme, diyet etiketleme, doğrulama, ChromaDB yükleme)
- **Hafta 2:** FastAPI backend ✅ (filtre çıkarımı, LLM entegrasyonu, arama endpoint'i)
- **Hafta 3:** JWT (kayıt/giriş) ✅ *(Hafta 6'da Firebase Auth ile değiştirildi)*, fotoğraftan malzeme tanıma endpoint'i ✅, favoriler sistemi ✅
- **Hafta 4:** Frontend ✅ (tüm sayfalar, tüm akışlar, tutarlı tasarım)
- **Hafta 5:** Google OAuth ✅, mikrofon (Web Speech API) ✅, kullanıcı menüsü ✅, Docker Compose'a frontend ekleme ✅
- **Hafta 6:** Firebase Auth migrasyonu ✅ (`firebase-auth` branch'inde, 8 senaryo canlı doğrulandı)
- **Hafta 7 — deploy hazırlığı:** torch'un kaldırılması ✅ (Faz 7), `recipes`'in image'a gömülmesi ✅ (Faz 8), favorites → Firestore + `chromadb` servisinin kaldırılması ✅ (Faz 9). Backend **stateless** hâle geldi.
- **Hafta 8 — CANLI:** Backend → Render, frontend → Vercel ✅ (Faz 10). 4 blocker'ın 3'ü çözüldü, in-app tarayıcı Google girişi (④) bilinçli ertelendi.
- **Hafta 9 — performans:** Faz 11 ✅ — arama LLM'i beklemiyor (8.87sn → 0.32sn), favoriler N+1 kalktı, favori sırası düzeldi.
- **Hafta 10 (şu an buradayız) — kalite:** Faz 13 logging ✅, Faz 14 model güncellemesi ✅, **Faz 15 test altyapısı + girdi doğrulama ✅** (ilk otomatik testler: 126 test). Kalan: Katman 2 testleri, `main`'e merge, README/sunum hazırlığı.

## Şu Ana Kadar Tamamlanan Dosyalar (güncel)
### Backend
- `ingestion/explore_data.py` — dataset keşfi
- `ingestion/clean_data.py` — temizleme pipeline'ı, recipes_cleaned.csv üretiyor (instructions_clean dahil)
- `ingestion/validate_tags.py` — diyet etiketi ve veri kalitesi doğrulama scripti
- `ingestion/load_to_chromadb.py` — ChromaDB'ye yükleme. Embedding'i artık elle üretmiyor: `collection.add()`'e sadece `documents` veriliyor, ChromaDB kendi varsayılan fonksiyonuyla (ONNX) embed ediyor. `PersistentClient` ile `api/chroma_data/` klasörüne yazıyor (sunucuya değil). **Linux'ta çalıştırılmalı** — bkz. Faz 8'deki Windows/HNSW bulgusu.
- `ingestion/test_search.py` — arama testleri. Gömülü veritabanını okuyor (sunucu yok). `CHROMA_PATH` env var'ıyla image'daki kopyaya yöneltilebilir — **repodaki `api/chroma_data`'ya yöneltirsen commit'li dosyayı kirletir** (bkz. Faz 8 notları).
- `api/main.py` — FastAPI backend + CORS middleware (Faz 10'dan beri kendi origin'lerimizle sınırlı): /api/recipes/search, /api/recipes/from-image, **/api/recipes/commentary** (Faz 11), /api/recipes/{recipe_id}, /api/favorites/* endpoint'leri. Tarifleri image'a gömülü `chroma_data/` klasöründen `PersistentClient` ile okuyor (Faz 8). Arama endpoint'leri LLM'i beklemiyor (Faz 11).
- `api/chroma_data/` — **git'e commit edilmiş** gömülü tarif veritabanı (35MB: `chroma.sqlite3` + HNSW indeks dosyaları). `load_to_chromadb.py` üretiyor, Dockerfile `COPY . .` ile image'a alıyor.
- `api/logger.py` — **merkezi logging + süre ölçümü** (Faz 13). Renkli seviye formatter'ı (`ColorFormatter`), `@timed` decorator'ı ve `timed_block` context manager'ı. Uygulamada `print` kalmadı. `python api/logger.py` ile seviyeleri/renkleri tek başına gösteren bir demo bloğu var.
- `api/auth.py` — tek iş: Firebase Admin SDK ile `verify_id_token()` → e-posta. `get_current_user_email` dependency'si korumalı endpoint'lerde kullanılıyor. (Eskiden JWT + bcrypt + kullanıcı kayıt/giriş vardı; Firebase geçişiyle ~140 satırdan ~30 satıra düştü.)
- `api/llm.py` — Gemini API ile LLM cevap üretimi + fotoğraftan malzeme tanıma (`gemini-2.5-flash`)
- `api/filters.py` — kullanıcı sorgusundan diyet/süre/kalori filtresi çıkarımı
- `api/validation.py` — **girdi doğrulama** (Faz 15). İki saf fonksiyon: `validate_query()` sorgu kullanılabilir değilse kullanıcıya gösterilecek mesajı döner (kurallar dizginin **biçimine** bakıyor — harf var mı, uzunluk, tek harf tekrarı); `is_weak_match()` ChromaDB'nin zaten hesapladığı mesafeye bakıp en yakın sonucun uzak olup olmadığını söyler (`COMMENTARY_MAX_DISTANCE = 1.3`). Biri hiç iş yapılmadan reddediyor, diğeri sonuçları göstermeye devam edip yalnızca AI yorumunu kesiyor. Bkz. Faz 15c ve 15e.
- `api/favorites.py` — favoriler sistemi (Repository Pattern'den esinlenmiş, kendi veri deposunu kendi yönetiyor). **Firestore** kullanıyor (Faz 9; öncesinde ChromaDB'ydi). `get_favorites` en son ekleneni üstte döner (Faz 11; sıralama bellekte — bkz. Faz 11 notu). Faz 6'daki Firebase Auth migrasyonunda **tek satır değişmemişti** — favoriler e-posta anahtarlı ve e-posta her iki auth sisteminde de aynı kimlik. Faz 9'da bunun tersi oldu: favoriler baştan yazıldı ama `main.py` hiç değişmedi (aynı fonksiyon imzaları, aynı `ValueError`'lar).
- `Dockerfile` (**repo kökünde**, Faz 10'da `api/`'den taşındı) — `python:3.13-slim`, `uvicorn` `$PORT`'u (yoksa 8080) dinliyor. ONNX modelini build sırasında retry'lı indirip gömüyor, image'a sadece `api/` kopyalanıyor. Hem `docker-compose` hem Render bunu kullanıyor. Image **1.2GB** (Faz 7 öncesi 2.83GB → Faz 7 sonrası 1.14GB → Faz 8'de +35MB tarif verisi).
- `.dockerignore` (**repo kökünde**) — `api/firebase-key.json` ve `.env`'i image dışında tutuyor (güvenlik), ayrıca `frontend/`, `ingestion/`, `*.csv`.
- `docker-compose.yml` — **2 servis**: `api`, `frontend` (Faz 9'da `chromadb` kaldırıldı). `api` kökteki Dockerfile'ı context=kök ile build ediyor.
- `README.md` (**repo kökünde**) — proje/deploy özeti; gereken iki env var burada yazılı.

### Frontend
- `frontend/index.html` — giriş/kayıt sayfası (Sign in / Create account sekmeleri, "Continue with Google" butonu). Firebase compat SDK script'leri + `firebase.js`, diğer JS'lerden önce yükleniyor (sıra önemli).
- `frontend/search.html` — ana arama sayfası (Text search / Camera search sekmeleri, mikrofon butonu)
- `frontend/recipe.html` — tarif detay sayfası (instructions + kalp butonu ile favori toggle)
- `frontend/favorites.html` — kayıtlı tariflerin listesi (boş durum ekranı ile)
- `frontend/css/style.css` — tüm sayfalar için ortak CSS (design tokens, layout, components, user menu dropdown)
- `frontend/js/firebase.js` — Firebase init + `authReady` promise'i (oturum durumu **kesinleşene** kadar bekler). Her sayfada compat SDK script'lerinden sonra, diğer JS'lerden önce yüklenir.
- `frontend/js/logger.js` — **frontend logging + süre ölçümü** (Faz 13). `api/logger.py`'nin tarayıcı tarafındaki eşi: aynı satır biçimi, aynı seviyeler, aynı "yavaşsa sarı" kuralı. `Logger.get(scope)`, `Logger.timed(fn, ...)` (decorator'ın JS'teki higher-order function karşılığı), `Logger.duration(...)`. Ayarlar `localStorage` üzerinden (`log_level`, `slow_ms`) — tarayıcıda ortam değişkeni yok. Her sayfada, kendisini kullanan dosyalardan önce yüklenir.
- `frontend/js/config.js` — `window.API_BASE`'i ortama göre kuruyor (yerel/LAN → `localhost:8080`, canlı → Render). `api.js`'ten önce yüklenir (Faz 10).
- `frontend/js/api.js` — ortak API katmanı (backend adresini `window.API_BASE`'den alır; Firebase ID token'ı header'a ekleyen fetch wrapper, `authReady` tabanlı auth guard, 401'de otomatik logout, kullanıcı menüsü/email + dropdown sign out, doğrulanmamış e-posta için hatırlatma bandı)
- `frontend/js/auth.js` — giriş/kayıt formu mantığı + Google girişi (Firebase `signInWithPopup`), hesap bağlama (`linkWithCredential`), kayıtta `sendEmailVerification()`, şifre sıfırlama (`sendPasswordResetEmail`; Faz 12)
- `frontend/js/search.js` — arama sayfası, mode tabs, kamera stream (`getUserMedia`), sesli arama (`SpeechRecognition`), sonuç render. AI yorumunu ayrı istekle çekiyor (`loadCommentary`, iskelet animasyonu + `commentarySeq` yarış koruması; Faz 11)
- `frontend/js/recipe.js` — detay sayfası, `parseInstructions()` (R vector kalıntılarını filtreliyor)
- `frontend/js/favorites.js` — favorileri tarif bilgileriyle **tek istekte** çekiyor (`?include_details=true`; Faz 11 öncesi her ID için ayrı istek atıyordu)
- `frontend/Dockerfile` — `nginx:alpine`, statik dosyaları doğrudan sunuyor

### Testler (Faz 15)
- `pytest.ini` (**repo kökünde**) — `pythonpath = api ingestion` (importlar çıplak: `from filters import ...`) ve `testpaths = api/tests ingestion/tests`. **`testpaths` opsiyonel değil**, gerekçesi Faz 15a'da.
- `api/requirements-dev.txt` — sadece `pytest`; image'a **kurulmuyor**.
- `api/tests/test_filters.py` — 34 test, `extract_filters` (mock yok)
- `api/tests/test_validation.py` — 59 test, `validate_query` (mock yok)
- `ingestion/tests/test_clean_data.py` — 33 test + 1 `xfail`, temizleme fonksiyonları (mock yok)
- Çalıştırma: `python -m pytest` (tümü ~0.5 sn) · `-v` test adlarını gösterir · `--lf` sadece son kırılanları çalıştırır.
- Windows notu: konsol cp1254 olduğu için Türkçe karakterli mesajlar bozuk görünür (çökme değil). `$env:PYTHONIOENCODING = "utf-8"` düzeltiyor.

## Henüz Yapılmadı (güncel — Faz 10 sonrası kalanların TAMAMI, hepsi opsiyonel)

Proje **canlıda ve çalışıyor**. Aşağıdakiler cila/temizlik; hiçbiri uygulamayı engellemiyor.

1. **`firebase-auth` → `main` merge** — Faz 6–10'un tamamı `firebase-auth`'ta, `main` el değmemiş. Deploy şu an **feature branch'inden** yapılıyor (hem Render hem Vercel bu dalı izliyor). Merge edilirse **Render ve Vercel'in izlediği dalı `main`'e çevirmek gerekir**, yoksa canlı eski dalda kalır.
2. **README + sunum hazırlığı** — kökte bir `README.md` var (deploy odaklı); sunum/anlatım materyali yok.
3. **④ In-app tarayıcılarda Google girişi** (`signInWithRedirect`) — bilinçli ertelendi, gerekçe "Deploy blocker'ları" bölümünde. **Not: normal mobil tarayıcıda (Chrome/Safari) giriş çalışıyor — kullanıcı gerçek telefonda doğruladı (2026-07-19).** Kalan risk yalnızca uygulama içi tarayıcılar.
4. **`nut_free` etiket açığı** — aşağıdaki "Ertelenen küçük iyileştirmeler"e bakınız; sunumda sorulabilecek türden gerçek bir veri hatası.
5. **Diğer küçük iyileştirmeler** — LLM cevabındaki `**bold**` render'ı, instructions'daki `\` kalıntıları, `filters.py` geliştirmeleri.
6. **Render uykusu** — ücretsiz katmanda 15dk sessizlikten sonra ilk istek 30-60sn. Faz 11 bunu ÇÖZMEZ (uygulama kodu değil, platform). Sunum öncesi bir kez uyandır.

### ✅ Artık YAPILDI (eski "yapılmadı" maddeleri)
- ~~GitHub'a bağlama~~ → `github.com/Gokdeniz-hub/recipe-rag-assistant` (Private), `firebase-auth` dalı push'lu.
- ~~Deploy~~ → **Faz 10**: backend Render'da, frontend Vercel'de, canlıda çalışıyor.
- **Platform araştırması (tarihsel — Faz 10'da Render seçildi).** Backend Faz 9'dan beri stateless tek container, mimari engel yok; ihtiyaç sadece "512 MB+ RAM veren bir Docker platformu" (uygulama ~180 MB boşta, ONNX ısınınca ~310 MB). **Vercel API'yi kaldıramaz** (image 1.2 GB, serverless limiti 250 MB) — o kapı kapalı, frontend için kullanılıyor. Değerlendirilenler (2026 Temmuz): **Render** ✅ seçildi (kartsız, yönetilen, 512 MB/0.1 vCPU, uyur); **Cloud Run** (teknik olarak en iyi, ~1 sn soğuk başlangıç, Google ekosistemi — ama kart zorunlu); **Koyeb** (kartsız olabilir, uyumaz, bölge/RAM belirsizliği); **Oracle** (12-24 GB, uyumaz, sonsuza dek bedava — ama kart + ham VM + ARM build + kapasite derdi); **HF Spaces** (Docker ücretli oldu); **Fly.io/Heroku** (ücretsiz katman öldü); **Back4app** (256 MB — bize dar).
- **"Şekil sorunu" — ✅ ÇÖZÜLDÜ (Faz 8–9).** *Bulut container'ları öldürülüp yeniden başlatılabilir olmalı; diske yazdığın her şey kaybolur, kalıcı disk kiralamak ücretsiz katmanların vermediği şeydir. Backend'in iki ChromaDB koleksiyonu vardı ve doğaları çok farklıydı:*
  - `recipes` — ✅ **Faz 8**. Ingestion ile **bir kez** yazılıyor, sonra sadece okunuyor (`query`/`get`); kalıcı disk isteyen bir veritabanı değil, salt-okunur bir dosya. Artık `api/chroma_data/` klasöründe duruyor ve image'a gömülüyor, `main.py` `PersistentClient` ile doğrudan okuyor.
  - `favorites` — ✅ **Faz 9**. Çalışma anında değişen tek veriydi; kalıcı disk ihtiyacının ve `chromadb` servisinin tek sebebi buydu. **Firestore'a taşındı.**

  **Sonuç: backend artık tek, stateless container.** 3 servis → 2 (`api` + `frontend`), kalıcı disk → 0. Bu sayede **Faz 10'da canlıya çıktı** (backend → Render, frontend → Vercel).

### Deploy blocker'ları (Faz 10'da çözüldü)
- ✅ **`api.js`'deki `API` sabiti** — `frontend/js/config.js`'e taşındı; ortama göre seçiyor (yerel/LAN → `localhost:8080`, canlı → Render). Bkz. Faz 10.
- ✅ **Firebase Authorized domains** — `recipe-rag-assistant.vercel.app` Firebase Console'a eklendi (kullanıcı adımı). `localhost` da listede kaldı.
- ✅ **CORS** — `main.py`'de artık `allow_origins=["*"]` değil: Vercel production domain'i + `allow_origin_regex` (Vercel preview'ları + localhost/127/LAN, herhangi port). Canlıda doğrulandı (izinli origin yansıyor, `evil.com` ve suffix-spoof reddediliyor).
- ⏳ **Google girişinde `signInWithPopup` → in-app tarayıcılarda sorunlu** (BİLİNÇLİ ERTELENDİ). **Kapsam düzeltmesi (2026-07-19, gerçek telefonda doğrulandı): mobilde giriş ÇALIŞIYOR.** Bu madde önceden "mobilde Google girişi bozuk" gibi okunuyordu; doğrusu değil:
  - **Masaüstü tarayıcı** → popup çalışıyor.
  - **Normal mobil tarayıcı (Chrome/Safari)** → ✅ çalışıyor, kullanıcı doğruladı. Firebase popup'ı yeni sekmede açıyor.
  - **In-app tarayıcılar** (Instagram, Facebook, LinkedIn vb. içinden açılan link) → kalan gerçek risk. Popup engelleniyor ya da açılıyor ama `window.opener` köprüsü kurulamadığı için giriş sonucu ana sayfaya dönmüyor; kullanıcı giriş sayfasında kalıyor.
  - **iOS Safari + "Cross-Site Tracking'i Engelle"** → sınırda; popup akışı `firebaseapp.com` üzerinden third-party storage'a dayandığı için bazı sürümlerde sessizce başarısız olabilir (bu senaryo test EDİLMEDİ).

  Firebase'in bu durum için önerisi **`signInWithRedirect`** (cihaza göre seçim). **Ertelendi** çünkü: (1) çalışan masaüstü girişini + hesap bağlama akışını (`auth.js:137`) yeniden kurmayı gerektiriyor — redirect'te hata `catch` bloğuna değil, sayfa yeniden yüklendikten sonra `getRedirectResult()`'a düşer, dolayısıyla `pendingGoogleCredential` sayfa yenilendiği için sıfırlanır ve mantık olduğu gibi çalışmaz; (2) `firebase.js`'teki `authReady` ile `getRedirectResult()`'ın sırası doğru kurulmazsa Faz 6'da çözülen **giriş↔search sonsuz yönlendirme döngüsü** geri gelebilir. Mevcut kapsam (masaüstü + normal mobil tarayıcı çalışıyor) sunum için fazlasıyla yeterli.

### Ertelenen küçük iyileştirmeler
- LLM cevabındaki `**bold**` markdown karakterlerinin HTML render'ı (şu an ham metin görünüyor)
- Instructions'daki bazı adımların sonundaki tekil `\` backslash temizliği (dataset veri kalitesi kalıntısı)
- `filters.py` iyileştirmeleri (malzeme çıkarımı, sayısal ifadeler "under 30 minutes", olumsuz ifadeler)
- **`nut_free` etiketinde açık var** (Faz 7'de tesadüfen fark edildi): "nut free cookies for kids" araması `Pine Nut and Almond Cookies` ve `wheat free peanut butter cookies` döndürüyor — ikisi de `nut_free: True` etiketli, yani yanlış. **KÖK SEBEP FAZ 15'TE BULUNDU** (eski tahmin "bileşik adlar kural listesine takılmıyor" YANLIŞTI) — ayrıntı için Faz 15b. Hata henüz **düzeltilmedi**; `xfail(strict=True)` testi olarak kayıtlı (`ingestion/tests/test_clean_data.py`), düzeltilince test XPASS verip suite'i kırar ve işaretin kaldırılmasını zorlar.

## Şu An Üzerinde Çalışılıyor
- **`firebase-auth` branch'i** (`main`'e henüz merge edilmedi). Faz 6–11'in tamamı bu branch'te. `main` el değmemiş durumda. **Canlı deploy `firebase-auth` dalından yapılıyor** (hem Render hem Vercel bu dalı izliyor), dolayısıyla merge sonrası deploy dalını `main`'e çevirmek gerekecek.
- Repo **GitHub'da**: `github.com/Gokdeniz-hub/recipe-rag-assistant` (Private). Sırlar (`firebase-key.json`, `.env`) gitignored, repoda yok — Render'da env var olarak duruyor.

## Güncel Durum: Faz 15 (Test altyapısı + girdi doğrulama) ✅

### Faz 15a — İlk otomatik testler (Katman 1) ✅
**Öncesi:** projede **hiç otomatik test yoktu**. `filters.py`, `llm.py`, `logger.py` içindeki `if __name__ == "__main__"` blokları demo — çıktıyı insan okuyor, hiçbir şey assert etmiyor. CLAUDE.md'deki onlarca "doğrulandı" ifadesinin tamamı elle yapılmış ve tekrarlanabilir değildi.

**Test edilebilirliğin önündeki engel — import anındaki yan etkiler.** Bu, test stratejisinin tamamını belirledi:

| Dosya | Import anında ne oluyor |
|---|---|
| `auth.py:19` | `firebase_admin.initialize_app()` — kimlik dosyası arıyor |
| `favorites.py:18` | `firestore.client()` |
| `llm.py:13` | `genai.Client(api_key=...)` |
| `main.py:36` | 35MB ChromaDB açılıyor + `get_collection("recipes")` |

Yani `import main` = Firebase kimliği + veritabanı + Gemini istemcisi. Bu yüzden testler katmanlara ayrıldı: **saf fonksiyonlar (mock gerekmez) önce**, HTTP sözleşme testleri (mock gerekir) sonraya bırakıldı.

**`testpaths` neden opsiyonel değil:** sınırlanmazsa pytest `ingestion/test_search.py`'yi de toplar. O dosya test değil, elle çalıştırılan bir script ve **import anında `PersistentClient` açıyor** — ChromaDB bir klasörü açarken bile `chroma.sqlite3`'e yazdığı için commit'li 35MB'lık veritabanı kirlenir ve git'te sahte bir değişiklik çıkar. (Doğrulandı: test çalıştırmalarından sonra `api/chroma_data/` temiz kaldı.)

**`clean_data.py` refactor'ü zorunluydu:** pipeline modül seviyesindeydi, yani `import clean_data` demek 522k satır okuyup `recipes_cleaned.csv`'yi **üzerine yazmak** demekti. `main()` içine alınıp `if __name__ == "__main__"` guard'ı eklendi (`filters.py` ve `llm.py`'de bu guard zaten vardı). Çalıştırma şekli değişmedi — `pd.read_csv` tuzaklanarak script yolunun hâlâ `main()`'i çağırdığı doğrulandı. Bu arada satır 188'deki `✓` → `[OK]`: `load_to_chromadb.py`'de aynı karakter Windows'ta (cp1254) `UnicodeEncodeError` verip script'i tam bitmişken çöktürüyordu, burada aynı bomba duruyordu.

**Sonuç:** 126 test + 1 xfail, ~0.5 sn, container/ağ gerekmiyor.

### Faz 15b — `nut_free` açığının KÖK SEBEBİ ✅ (bulundu, düzeltilmedi)
Önceki tahmin — *"muhtemelen 'pine nut'/'peanut butter' gibi bileşik adlar kural listesine takılmıyor"* — **yanlıştı**.

Gerçek sebep: `extract_diet_tags` ada bakan güvenlik ağını **yalnızca ET için** kurmuş.
- `clean_data.py:77-80` → `name_has_land_meat`, `name_has_seafood` **var**
- `clean_data.py:121-122` → `has_nuts` sadece `ingredients_text` ve `category_lower`'a bakıyor, **tarif adı hiç kontrol edilmiyor**. Aynı açık `has_dairy` ve `has_gluten` için de geçerli.

Kanıt (fonksiyon izole edilip çalıştırıldı):
```
extract_diet_tags(['flour','sugar'], 'Cookie', 'Pine Nut and Almond Cookies')
  -> ['vegetarian','dairy_free','vegan','nut_free']   YANLIŞ (ad açıkça söylüyor)
extract_diet_tags(['lettuce','tomato'], 'Salad', 'Chicken Salad')
  -> vegetarian YOK                                    DOĞRU (et için ad kontrolü var)
```

**`validate_tags.py` neden "0 çelişki" diyordu:** Çelişki 4 (`validate_tags.py:48-51`) sadece `RecipeCategory`'ye bakıyor. "Pine Nut and Almond Cookies"in kategorisi `Cookie` — içinde nut kelimesi yok, o yüzden yakalanmıyor. **İki dosya aynı kör noktayı paylaşıyor**, dolayısıyla doğrulama scripti kendi ürettiği hatayı göremiyor.

Test `xfail(strict=True)` olarak yazıldı — düzeltilince XPASS verip suite'i kırar, işaretin kaldırılmasını zorlar. Sunumda anlatılabilir: *"test yazdım, bilinen bir hatanın gerçek sebebi tahmin edilenden farklı çıktı."*

### Faz 15c — Girdi doğrulama (`api/validation.py`) ✅
**Tetikleyici (kullanıcı sorusu):** *"search bar'a 1235533443 girilirse boşuna AI kotası yenip boşuna veritabanına bakılmıyor mu?"* — evet, ama mekanizma dolaylı.

**Zincir:** arama Gemini'yi çağırmıyor (Faz 11'de ayrılmıştı). `search.js:172` sonuçlar gelir gelmez `loadCommentary`'yi tetikliyor; oradaki tek koruma `recipes.length === 0` (`search.js:73`). **Vektör araması her zaman 5 komşu döndürdüğü için bu koruma saçma sorguda hiç devreye girmiyor** → `/api/recipes/commentary` çağrılıyor → kota yanıyor.

Saçma bir sorgunun canlıdaki maliyeti: token doğrulama ~150 ms + ChromaDB **~5.4 sn** (Render 0.1 vCPU, Faz 13c ölçümü) + ikinci token doğrulaması + Gemini 0.7–2.8 sn + **günlük 100 hakkın 1'i**. Kullanıcı karşılığında 5 alakasız tarif görüyordu.

**Asıl mesele:** vektör araması **"eşleşme yok" DİYEMEZ** — eşleşme kalitesine bakmadan her zaman en yakın *n* komşuyu döndürür. Sistemde "sonuç yok" diye bir durum yok (tek istisna: metadata filtresi her şeyi elerse).

#### Mesafe eşiği denendi ve ÖLÇÜMLE ELENDİ
ChromaDB `distances`'ı zaten döndürüyor, `main.py:96` onu okumadan atıyordu — yani eşik ek hesap maliyeti getirmezdi. 55 sorgulu kalibrasyon (L2; koleksiyonda `hnsw:space` ayarlı değil → ChromaDB varsayılanı):

| grup | n | min | medyan | max |
|---|---:|---:|---:|---:|
| anlamlı | 30 | 0.336 | 0.605 | 0.958 |
| saçma | 15 | 1.240 | 1.597 | 1.732 |
| konu dışı | 10 | 1.230 | 1.625 | 1.792 |

İlk 12 sorgulu ölçümde boşluk temiz görünmüştü (0.892 → 1.566) ve eşik 1.3 önerilmişti. **Örneklem genişletilince çöktü** — "anlamlı" sorgular elle yazılmıştı ve hepsi çok kelimeli, dataset'in güçlü olduğu şeylerdi. Gerçek kullanıcı sorguları eklenince:

| sorgu | mesafe | eşik 1.1'de |
|---|---:|---|
| `dinner` | 1.185 | ❌ reddedilir |
| `food` | 1.157 | ❌ reddedilir |
| `borscht` | 1.141 | ❌ reddedilir |
| `pad kee mao` | 1.177 | ❌ reddedilir |
| `pierogi ruskie` | 1.315 | ❌ reddedilir |
| `zxcvbnm` (klavye ezmesi) | 1.240 | meşrulardan **daha yakın** |

İki sebep: **(1) en yakın komşu mesafesi genelliği cezalandırıyor** — `dinner` kümenin merkezine yakın ama hiçbir *tekil* tarife yakın değil; **(2) yazım/ad farkları mesafeyi şişiriyor.** İkisi de kullanıcı hatası değil.

**`borscht` bunun en çarpıcı örneği ve mesafenin neden sonuç gizlemek için kullanılamayacağının kanıtı:** mesafe 1.141 (eşiğin üstünde sayılacak kadar yüksek) ama en yakın sonuç **tam doğru tarif** — `Ukrainian Borsch With Pyrizhky (Pyrohy) (Piroshki)`. Veri setinde borscht **var**; mesafe sadece yazım farkı (`borscht` vs `Borsch`) ve uzun parantezli ad yüzünden yüksek. Eşik sonuçları gizleseydi kullanıcıdan **tam isabeti** saklamış olurduk. (Daha önce bu belgede "dataset'te karşılığı zayıf" yazıyordu — yanlıştı, ölçümle düzeltildi.)

**Sonuç: hiçbir eşik iki sınıfı temiz ayıramıyor; mesafe hard-reject olarak kullanılamaz.** (Yazım hataları sorun değil: `chiken dinner` 0.986, `vegitarian pasta` 0.804 — embedding tolere ediyor.)

#### Uygulanan çözüm: biçimsel kurallar
`validate_query(text) -> str | None` — saf fonksiyon (`filters.py` deseni), sorun varsa kullanıcıya gösterilecek mesajı döner.

| kural | öldürdüğü | neden yanlış red riski yok |
|---|---|---|
| `len < 2` | `""`, `"a"` | tek harfli tarif sorgusu yok |
| harf içermiyor | `1235533443`, `!!!???...`, `-----`, `12 34 56 78` | her tarif sorgusunda kelime vardır |
| tek farklı harf | `aaaaaaaaaa` | — |
| `len > 200` | kopyala-yapıştır metin | ayrıca commentary prompt'unu sınırlıyor |

`str.isalpha()` Unicode farkında → `börek`, `crème brûlée` geçer. Çağrı `extract_filters`'tan **önce**, yani embedding ve ChromaDB hiç çalışmıyor.

**Neden 422 değil, 200 + `{"error": ...}`:** `api.js:151` 401 dışındaki durumlarda gövdeyi olduğu gibi döndürüyor ve `search.js:168` zaten `data.error`'ı `showError`'a veriyor — Faz 11b'de kurulan kalıp. **Frontend'de tek satır değişmedi.**

**Aynı aileden ek sınırlar:** `n_results` → `Field(5, ge=1, le=20)` (öncesinde sınırsızdı, istemci 100000 isteyebilirdi); `CommentaryRequest.query` → `max_length=500` (bu metin doğrudan Gemini prompt'una giriyor — `main.py:138`'deki *"tarif bilgisi ID'lerden okunuyor"* koruması `query` alanını **kapsamıyordu**); `recipe_ids` → `max_length=50`; `additional_text` → `max_length=200`.

**`from-image`'a `validate_query` UYGULANMADI** (bilinçli): alan opsiyonel, asıl sorguyu fotoğraftan tanınan malzemeler taşıyor ve vision çağrısı bu noktada zaten yapılmış — erken reddetmenin tasarruf ettireceği bir şey yok. Yalnızca uzunluk sınırlandı.

**Doğrulama:** 126 test geçiyor. Ayrıca **gerçek `search_recipes` fonksiyonu** çağrıldı (dış servisler `sys.modules` üzerinden sahtelendi): reddedilen 5 sorguda `collection.query` **çağrı sayısı 0** — ChromaDB'ye hiç gidilmiyor, endpoint 0.1 ms'de dönüyor; `dinner` / `borscht` / `up` geçiyor ve sorgu ChromaDB'ye ulaşıyor. Pydantic kısıtları sınır değerleriyle ayrıca doğrulandı (n_results 20 ✓ / 21 ✗, query 500 ✓ / 501 ✗, 50 id ✓ / 51 ✗).

**Log tutarlılığı:** `Text search:` INFO satırı artık sorguyu `[:100]` ile kırpıyor — uzunluk kontrolü o noktada henüz yapılmadığı için 200+ karakterlik bir sorguyu olduğu gibi basabilirdi. `%r` (log injection) koruması korundu.

### Faz 15e — B′ (zayıf eşleşme kapısı) + `IRRELEVANT` kuralı ✅
**Tetikleyici:** kullanıcı canlıda `lkjhgfdsa` tipi bir sorgu denedi. A katmanı bunu **tasarım gereği** geçirdi (harf var, 2'den fazla farklı harf var), sonuçta Swedish Glögg + Fried Shallots döndü **ve bir Gemini çağrısı harcandı**. İlginç ayrıntı: model saçmalığı kendisi teşhis etti — *"It looks like your previous message was a random string of letters"*.

**A genişletilerek çözülemezdi.** Klavye ezmesini biçimden tanıma denemesi aynı duvara çarpıyor:

| | `asdkjfhaskjdfh` | `borscht` |
|---|---:|---:|
| sesli harf oranı | 2/14 = %14 | 1/7 = %14 |
| en uzun sessiz dizisi | 6 | 5 |

İstatistiksel olarak ayırt edilemiyorlar.

**Ölçüm — 12 klavye ezmesinin hepsi 1.304–1.612 aralığında** (`qweqweqwe` 1.304, `lkjhgfdsa` 1.421, `asdkjfhaskjdfh` 1.566, `asdf asdf` 1.612). Eşik 1.3 hepsini yakalıyor.

**MESAFE TEK BAŞINA YETMEDİ — ikinci sinyal eklendi.** İlk sürüm yalnızca mesafeye bakıyordu ve kullanıcı testinde çöktü: `easy` yazınca yorum kesiliyordu, **ama dönen tarifin adı "Easy Pizza Sauce"**. Not (*"tam eşleşme olmayabilir"*) düpedüz yanlış oluyordu. Üstelik `quick` (1.419) yorumsuz kalırken eşanlamlısı `fast` (1.277) yorum alıyordu.

**Kök sebep:** nearest-neighbour mesafesi isabeti değil **özgüllüğü** ölçüyor. `easy` yüzlerce tarifin adında geçtiği için hepsine *orta* uzaklıkta, hiçbirine *çok* yakın değil — mesafe bunu "alakasız" diye okuyor. `lkjhgfdsa` gerçekten alakasız. İkisi aynı sayıya düşüyor.

**Ayırt edici ikinci soru: sorgudaki kelime dönen tariflerde geçiyor mu?** Bu bilgi de bedava (dokümanlar zaten yanıtta).

| kural | yanlış red | kaçan |
|---|---:|---:|
| sadece mesafe | **6/16** | 1/13 |
| mesafe **VE** sözcüksel örtüşme yok | **2/16** | **1/13** |

Ödünleşim yok, katıksız kazanç. Geri kazanılanlar: `easy`, `quick`, `something good` **ve `pierogi ruskie`** (bu sonuncusu ilk sürümde "bilinen maliyet" olarak kaydedilmişti, artık yok). Kalan iki yanlış red: `simple` (1.766) ve `cheap` (1.702) — kelimeleri sonuçlarda geçmiyor (dönenler "Easy Appetizer Meatballs" gibi eşanlamlılar).

**İki ölçülmüş ayrıntı:**
- **Tam kelime sınırı (`\b...\b`) şart.** Önek eşleşmesinde `japan` sorgusu "Japanese Curry"ye takılıyor ve `what is the capital of Japan` kaçıyordu.
- **Kaç dokümana bakılacağı:** 1 doküman `pierogi ruskie`'yi kaçırıyor (eşleşme 2. sırada, "Buffalo Pierogies"in malzemesinde); 5 doküman `best gaming laptop 2026`'yı içeri alıyor ("best" tarif adlarında çok geçiyor). **3 seçildi.**

**Uygulanan:**
- `validation.is_weak_match(distances, query, documents)` — saf fonksiyon, `COMMENTARY_MAX_DISTANCE = 1.3`. **İki sinyal birden** gerekiyor: en yakın sonuç uzak OLACAK **ve** sorgudaki hiçbir kelime bulunan tariflerde geçmeyecek. Mesafe/sonuç yoksa `False` (şüphede kullanıcının aleyhine davranma). 4 harften kısa kelimelerden oluşan sorgularda (`can you fix my car`) örtüşme iddia edilemez, mesafe tek karar verici kalır.
- `main.py` her iki arama endpoint'ine `weak_match: bool` alanı ekliyor. **Alan adı bilinçli olarak politika değil olgu bildiriyor** (`commentary_eligible` değil): istemci hem yorumu atlıyor hem not gösteriyor, ileride politika değişirse alan anlamını koruyor.
- `search.js` → `loadCommentary(query, results, weakMatch)`; kontrol **fonksiyonun içinde**, iki çağıranda kopyalanmasın diye. Zayıfsa **istek hiç kurulmuyor** — ağ turu + token doğrulaması + Gemini çağrısı birlikte gidiyor.
- `search.html` + `style.css` → sonuçların üstünde not: *"These may not be a close match..."*. Uyarı değil bilgi olduğu için `--error` değil `--text-muted`.

**Sonuçlar GİZLENMİYOR.** Ölçüm bunu yasaklıyor: meşru sorgular 1.566'ya kadar çıkıyor (`easy` 1.566, `something good` 1.503), yani sonuçları kesecek güvenli bir ikinci eşik yok.

**Bilinen maliyet (teste yazıldı):** `simple` (1.766) ve `cheap` (1.702) meşru ama yorumsuz kalıyor — kelimeleri dönen tariflerde geçmiyor. Sonuçlarını yine görüyorlar.

**Eşikle kovalanamayacak sınıf:** `what is the capital of Turkey` → **1.052**. "turkey" hem ülke hem hindi olduğu için sorgu yemek kümesinin tam içine düşüyor ve roast turkey tarifleri dönüyor. Aynı cümle kalıbı ülkeye göre 1.052 (Turkey) / 1.265 (switzerland) / 1.314 (France) / 1.520 (Japan) veriyor — tek belirleyici, ülke adının bir yemek kelimesiyle çakışıp çakışmaması. Bunları yakalamak için eşiği indirmek `borscht`/`dinner`/`food` dahil yarım listeyi keserdi. **Bu sınıf `IRRELEVANT` kuralının işi**, mesafenin değil.

**`IRRELEVANT` kuralı (`llm.py`):** prompt'a *"gerçek bir yemek isteği değilse yalnızca IRRELEVANT yaz"* eklendi; `generate_answer` artık `str | None` dönüyor. Eşiğin **hemen altında** kalan saçma sorgular için ikinci savunma hattı. **Ek maliyeti yok** — aynı çağrının içinde, ek gecikme/token getirmiyor. Modelin bu yargıyı zaten yaptığı canlıda görülmüştü; tek eksik onu yapılandırılmış biçimde istemekti.

**Neden LLM'i "kapı" olarak KULLANMADIK** (değerlendirildi, elendi): kotayı korumak için Gemini'ye sormak döngüsel. Meşru sorguda tüketim **2 çağrıya** çıkardı (kapı + yorum), yani günlük kapasite 100 → 50. Saçma sorguda ise bugüne göre tasarruf **sıfır** (B′ 0 çağrı harcıyor, LLM kapısı 1). Ayrıca Faz 11'in tüm kazancını geri alırdı: LLM aramanın **önüne** girer, kullanıcı sonuçları daha da geç görürdü. Üstüne Gemini'ye sert bağımlılık gelirdi (bugün Gemini çökse arama çalışıyor). Ölçüm bunu net gösteriyor: canlıda `commentary` 787–999 ms, `search` 5.8–7 sn — **Gemini bizim embedding'imizden 6 kat hızlı**, çünkü o Google'ın donanımında, bizimki 0.1 vCPU'da.

**Doğrulama:** 159 test geçiyor. **Gerçek `search_recipes`, gerçek veritabanı kopyasıyla** uçtan uca çalıştırıldı (mock'lu değil — `chromadb.PersistentClient` yamalanıp scratchpad'deki kopyaya yönlendirildi, repo kirlenmedi):

| sorgu | mesafe | weak | ilk sonuç |
|---|---:|---|---|
| `gluten free quick chicken dinner` | 0.573 | False | Quick Chicken Parmesan |
| `borscht` | 1.141 | False | Ukrainian Borsch With Pyrizhky |
| `dinner` | 1.185 | False | A Bowlful of Dinner |
| `pierogi ruskie` | 1.315 | False | Ukrainian Borsch… |
| `quick` | 1.419 | False | Quick Meat Sauce from a Jar |
| `something good` | 1.503 | False | A Few (Really) Good Men |
| `easy` | 1.566 | False | Easy Pizza Sauce |
| `lkjhgfdsa` | 1.421 | **True** | Dk's Swedish Glögg |
| `what is the capital of Japan` | 1.520 | **True** | Taiyaki |
| `can you fix my car` | 1.698 | **True** | Carob Pinwheels |
| `cheap` | 1.702 | **True** | Quick and Easy Meatball Minestrone |
| `simple` | 1.766 | **True** | Easy Appetizer Meatballs |

Sınır durumları patlamıyor: sonuçsuz arama (`vegan pescatarian dish` → 0 sonuç, `weak_match=False`), `distances` alanının hiç gelmemesi, `documents=None`, A katmanı reddi.

#### Ayar düğmeleri ve geri alma (ileride değiştirilecekse)

Hepsi `api/validation.py`'de, hepsi tek sayı/liste:

| Sabit | Değer | Ne yapar | Artırılırsa | Azaltılırsa |
|---|---:|---|---|---|
| `COMMENTARY_MAX_DISTANCE` | `1.3` | uzaklık eşiği | daha az sorgu yakalanır (kaçan artar) | meşru sorgular yorumunu kaybeder |
| `OVERLAP_DOCS` | `3` | kaç tarifte kelime aranacak | daha çok tesadüfi eşleşme → kaçan artar (5'te `best gaming laptop` kaçıyor) | 1'de `pierogi ruskie` yanlış reddedilir |
| `MIN_TOKEN_LENGTH` | `4` | kaç harften uzun kelimeler aranacak | `easy`/`food` gibi 4 harfliler kontrol dışı kalır | `can`/`car`/`fix` gibi kısa kelimeler tesadüfi eşleşir |
| `_STOPWORDS` | 22 kelime | örtüşmede yok sayılanlar | — | `what`, `with` gibi kelimeler tesadüfen eşleşir |

**Yemek sıfatları (`easy`, `quick`, `good`, `best`) bilerek `_STOPWORDS`'te DEĞİL** — `easy` sorgusunun eşleşmesi gereken tek kelimesi o. `best` eklenirse `best gaming laptop 2026` da yakalanır ama bu tek örneğe göre ayar yapmak olur.

**Tamamen geri almak için** (davranış Faz 15c'ye, yani sadece A katmanına döner):
1. `main.py` → iki `weak = is_weak_match(...)` bloğunu ve yanıtlardaki `"weak_match": weak` alanını sil
2. `search.js` → `loadCommentary`'deki `|| weakMatch` koşulunu, üçüncü parametreyi ve `renderResults`'taki not bloğunu sil
3. `search.html` → `#weak-match-note` elemanını sil
4. `validation.py` → `is_weak_match` / `_has_lexical_overlap` ve sabitlerini sil
5. `test_validation.py` → `TestIsWeakMatch*` ile başlayan sınıfları sil

`IRRELEVANT` kuralı bağımsız — B′ kaldırılsa da çalışmaya devam eder (tek başına da anlamlı, çünkü ekrandaki saçma kutuyu engelliyor).

**Kalibrasyonu yeniden üretmek için:** scriptler repoda değil. Ölçüm `api/chroma_data`'nın bir **KOPYASI** üzerinde yapılmalı — repodaki klasör `PersistentClient` ile açılınca bile `chroma.sqlite3`'e yazılıyor ve commit'li 35MB'lık dosya kirleniyor. Yöntem: klasörü geçici bir yere kopyala, meşru/saçma sorgu listelerini `collection.query(query_texts=[q], n_results=5)` ile çalıştır, `distances[0][0]` dağılımına bak.

#### Yerelde test etme
- **Backend değişikliği** (`validation.py`, `main.py`, `llm.py`) → `api` servisi bind-mount **edilmiyor**, kaynak image'a `COPY` ediliyor. Rebuild şart: `docker compose up -d --build api`
- **Frontend değişikliği** (`search.js`, `search.html`, `style.css`) → `./frontend` bind-mount edildiği için rebuild gerekmiyor; nginx dosyayı önbelleğe alabildiğinden `docker restart recipe_frontend` + tarayıcıda `Ctrl+Shift+R`
- Doğrulama: `docker compose logs api --tail 50` içinde `WARNING | main | Weak match for '...' (best distance: ...)` satırı görünmeli

### Faz 15d — Değerlendirilip yapılmayanlar
- **Katman 2 (HTTP sözleşme testleri)** — `conftest.py` + `TestClient` + `dependency_overrides`. Yukarıdaki doğrulamada kullanılan `sys.modules` sahteleme yöntemi çalıştığı için yol açık. **`conftest.py` ChromaDB'yi de sahtelemeli**, yoksa her `pytest` çalıştırması commit'li `chroma.sqlite3`'ü kirletir.
- **Frontend'de aynı kuralların aynası** — anında geri bildirim verir ve bir ağ turu + token doğrulaması kurtarır, ama kuralların iki dilde kopyalanması drift riski taşıyor. Yapılmadı.
- Kalibrasyon scriptleri repoda **değil** (scratchpad'de üretildi). Sayılar bu belgede kayıtlı; tekrar gerekirse `api/chroma_data`'nın bir **kopyası** üzerinde çalıştırılmalı (repodaki klasör açılınca kirlenir).

## Faz 14 (Yeni Gemini modelleri + vision sırasının düzeltilmesi) ✅

**Tetikleyici:** Google'ın duyuru maili — `gemini-3.6-flash` ve `gemini-3.5-flash-lite` API'de kullanılabilir hâle geldi. Model adları **tahmin edilmedi**, `client.models.list()` ile doğrulandı (Faz 11b'de `gemini-2.5-flash-lite` 404 vermişti; API'ye sormak alışkanlık hâline geldi).

**Ölçüm (2026-07-22, 3'er/2'şer tekrar, medyan; görsel için projenin kendi `test_photo.jpg`'si):**

| Model | Yorum | Görsel | Not |
|---|---:|---:|---|
| `gemini-3.5-flash-lite` 🆕 | **742 ms** | **867 ms** | her iki işte de en hızlı |
| `gemini-3.1-flash-lite` | 762 ms | 1027 ms | |
| `gemini-2.5-flash` | 2771 ms | 2483 ms | |
| `gemini-3.6-flash` 🆕 | 5454 ms | 3057 ms | bu işler için yavaş, zincirin sonunda |
| `gemini-3.5-flash` | 12374 ms | 9483 ms | |

**Asıl bulgu — vision sıralaması tersti.** `VISION_MODELS`'in ilk sırasında `gemini-3.5-flash` vardı (9.5sn). Eski gerekçe: *"malzeme tanıma asıl görsel iş, daha güçlü model başta."* **Ölçüm bu varsayımı çürüttü:** beş model de aynı üç malzemeyi buluyor (eggplant, tomato, green chili), ama o model 11 kat yavaş. Varsayım hiç test edilmemişti. Kamera araması uçtan uca **1.41sn**'ye indi (vision 1.09sn + chromadb 322ms). *(Kalite kıyası tek fotoğrafa dayanıyor — "kalite eşit" demek için birkaç fotoğraf gerekir; ama "9.5sn gereksiz" sonucu tek fotoğrafla bile sağlam.)*

**Kota — "çapraz sıralama" gerekçesi düzeltildi.** Kota `PerProjectPerModel`, yani aynı anahtarla her modelin ayrı 20 hakkı var; 3 model → 5 model = 60 → 100 istek/gün. Ama iki listenin ilk sıralarının farklı olması **kapasiteyi artırmıyor** (zincir aşağı indikçe iki akış da aynı havuzlara ulaşıyor, toplam aynı). Kazandırdığı şey **boşa giden deneme**: aynı modelle başlasalardı, 20 yorumdan sonra kamera aramasının ilk denemesi 429 yiyip bir ağ turu kaybederdi. Çapraz başlayınca her akış taze havuzla başlıyor.

**Kod değişikliği sadece iki tuple** — `_generate`'deki Chain of Responsibility kaç model olursa olsun çalışıyor.

**Uyarı:** ücretsiz katmanda gecikmeler günden güne çok oynuyor (`gemini-3.5-flash` Faz 11b'de 5.17sn, bugün 12.4sn; `gemini-2.5-flash` 8.5sn'den 2.77sn'ye). Sıralama bugünün ölçümüne göre doğru, mutlak değerlere yaslanmamalı.

**Yan gözlem (kalite):** lite modeller yorumda bazen *"all three options are excellent"* deyip seçim yapmıyordu; büyük modeller gerçekten seçiyordu. Yeni sıralamayla yapılan testte `gemini-3.5-flash-lite` düzgün seçim yaptı (*"The **Quick India Chicken** ve **Mediterranean...**"*), ama bu tek gözlem. Sorun tekrarlarsa çözüm model değiştirmek değil prompt'u sıkılaştırmak.

**Doğrulama:** yorum ilk modelle 1.21sn; kamera araması gerçek fotoğrafla uçtan uca 1.41sn, 3 tarif döndü; fallback zinciri 5 modelle test edildi (ilk iki model 429 → 3.'ye düştü, cevap geldi; hepsi tükendiğinde `ERROR All models exhausted` + hata yukarı fırlatıldı).

## Faz 13 (Logging + süre ölçümü) ✅

**Neden:** Hocanın isteği — "search fonksiyonlarının çalışma sürelerini ölç", decorator + logging sistemi, seviyeler ve renkler, Render'ın log ekranında da görünsün. Aynı zamanda gerçek bir eksikti: Faz 7/11'deki tüm süre ölçümleri **tek seferlik test scriptleriyle** yapılmıştı, çalışan uygulamada hiç ölçüm yoktu; hata ayıklama `print` ile yapılıyordu (seviye yok, zaman damgası yok, filtrelenemiyor).

**`api/logger.py` (yeni, sadece standart kütüphane — yeni bağımlılık yok):**
- `ColorFormatter` — `HH:MM:SS | LEVEL | modül | mesaj`, seviyeye göre ANSI renk (DEBUG cyan, INFO yeşil, WARNING sarı, ERROR kırmızı). `LOG_COLOR=0` ile kapatılabilir (renk anlamayan bir log toplayıcıya yazılırsa).
- `setup_logging()` — root'a **tek** stdout handler bağlar, iki kez çağrılırsa hiçbir şey yapmaz (yoksa her satır iki kez basılır). Gürültülü kütüphaneler (`httpx`, `chromadb`, `google`, `grpc`) WARNING'e kısıldı. `LOG_LEVEL` env var'ıyla ayarlanıyor.
- `@timed` decorator — **fonksiyon gövdesine hiç dokunmadan** süre ölçer. `@timed`, `@timed(slow_ms=5000)`, `@timed(name=...)` kullanımlarının üçü de çalışır; sync ve async fonksiyonları ayrı ayrı destekler.
- `timed_block(...)` context manager — fonksiyonun tamamını değil **içindeki bir adımı** ölçmek için. Toplam süre "nerede yavaşlıyor?" sorusunu cevaplamıyor; asıl bilgi kırılımda (filtre ~0 ms, ChromaDB ~300 ms, Gemini saniyeler).

**Seviye seçimi ölçümün kendisinden çıkıyor** (levels'ı süsleme değil, karar mekanizması yapan kısım):
| durum | seviye | renk |
|---|---|---|
| süre < eşik | INFO | yeşil |
| süre ≥ eşik (`SLOW_MS`, varsayılan 1000 ms) | WARNING | sarı |
| fonksiyon hata fırlattı | ERROR | kırmızı (süre yine loglanır, hata **yutulmaz**) |

Eşik fonksiyon başına ayarlanabiliyor: Gemini'yi bekleyen endpoint'ler `slow_ms=5000` ile işaretlendi, yoksa normal çalışan her istek WARNING üretir ve uyarı anlamını yitirirdi.

**Nereye takıldı:** `search_recipes`, `search_recipes_from_image`, `recipe_commentary`, `get_recipe_detail`, favori endpoint'leri (`@timed`); içeride `extract_filters` + `chromadb query` + favorilerdeki toplu `chromadb get` (`timed_block`); `llm.py`'de `generate_answer` / `detect_ingredients_from_image` ve **her model denemesi ayrı ayrı** — hangi modelin ne kadar sürdüğü (0.65sn vs 8.5sn) artık log'dan okunuyor; `favorites.py`'de `get_favorites`.

**Seviyeler için gerçek kullanım yerleri** (uydurma değil, mevcut kod yollarından geldi): sonuçsuz arama → WARNING, fotoğrafta malzeme bulunamaması → WARNING, model kota dolup sonrakine geçiş → WARNING, zaten favoride olan tarif → WARNING, LLM/vision hatası → ERROR, tüm modellerin tükenmesi → ERROR.

**İki incelik:**
- **Decorator `@app.post(...)`'un ALTINA yazılmalı** — önce sarmala, sonra route'a kaydet. Üstte olsaydı FastAPI sarmalanmamış fonksiyonu kaydeder, ölçüm hiç çalışmazdı. `functools.wraps` `__wrapped__` alanını da kopyaladığı için FastAPI orijinal imzayı görmeye devam ediyor; `Depends(...)` ve Pydantic gövde doğrulaması etkilenmiyor (TestClient ile doğrulandı: 200 / 422 / 500 yolları, `Depends` değeri ve gövde doğrulaması bozulmadan çalışıyor).
- **`_generate`'deki model denemeleri `timed_block` ile ölçülmüyor**, elle ölçülüyor — çünkü `timed_block` başarısızlığı ERROR sayardı, oysa 429 alıp sonraki modele geçmek hata değil planlanmış davranış. Aynı ölçüm `log_duration()` ile loglanıyor.

**Token doğrulaması da ölçülüyor (`auth.py`) — ve `expected` parametresi.** `get_current_user_email` korumalı **her** istekte çalışıyor ama endpoint'in `@timed` ölçümü onu kapsamıyor: FastAPI dependency'leri endpoint fonksiyonundan **önce** çalışır. Faz 11'de "her istek ayrıca `verify_id_token()` çalıştırıyor" denmişti ama hiç ölçülmemişti; artık ölçülüyor.
Bunun için `timed`'a **`expected`** parametresi eklendi: orada listelenen istisnalar ERROR yerine WARNING sayılıyor. Gerekçe: **her istisna arıza değildir** — süresi dolmuş bir token'ın 401 alması sistemin doğru çalıştığının işaretidir, kırmızı yanması yanıltıcı olurdu (aynı ayrım `llm.py`'deki 429 fallback'inde de yapılmıştı). Hangi istisnaların beklenen olduğunu **çağıran** bildiriyor (`@timed(expected=(HTTPException,))`), böylece `logger.py` FastAPI'ye bağımlı kalmıyor.
**Doğrulama:** başarılı doğrulama → `INFO verify token took 150.2 ms`; süresi dolmuş token ve bozuk header → `WARNING verify token failed ... 401` (ERROR değil). Dependency imzası korundu: header'sız istek hâlâ **422**, sahte token **401**, OpenAPI'de `authorization` header'ı hâlâ zorunlu görünüyor.

**Log injection'a karşı `%r`:** kullanıcıdan gelen değerler log satırına `%s` ile konursa içindeki satır sonu (URL'de `%0A`) aynen basılır ve saldırgan log'a **sahte bir satır uydurabilir** — örn. `Recipe not found: 17450` satırının altına gerçekmiş gibi görünen ikinci bir satır. `%r` (repr) satır sonunu `\n` olarak kaçırdığı için tek satırda kalıyor. Sorgular zaten `%r` kullanıyordu; `recipe_id`'ler ve LLM'den gelen malzeme metni de `%r`'ye çevrildi (canlı denendi: uydurma satır tek satır hâlinde kaçırılmış olarak göründü).

**Test sırasında çıkan bulgu — `google_genai` gürültüsü:** gürültülü kütüphane listesinde `"google"` vardı ama Gemini SDK'sının logger adı `google_genai.models`, yani **alt çizgili — `google` logger'ının çocuğu değil**, dolayısıyla kısılma ona uygulanmıyordu ve her Gemini çağrısında bir `AFC is enabled with max remote calls: 10` satırı sızıyordu. Listeye ayrıca eklendi. (Logger hiyerarşisi nokta ile kurulur: `google.auth` çocuktur, `google_genai` değildir.)

**Saat dilimi (`docker-compose.yml` → `TZ=Europe/Istanbul`):** container varsayılan olarak UTC kullanıyor, log saatleri kendi saatimizden 3 saat geride görünüyordu — testte "loglar akmıyor" sanılmasına yol açtı (aslında akıyordu, saat eski görünüyordu). Sadece yerel geliştirme kolaylığı; canlıda (Render) UTC kalması normal.

**Render:** platform log akışını stdout'tan okuduğu için ek bir şey gerekmiyor; Dockerfile'a `ENV PYTHONUNBUFFERED=1` eklendi — yoksa Python satırları tamponda bekletir ve loglar gecikmeli (bazen hiç) görünür.

### Faz 13b (frontend logging) ✅
Backend logu `search_recipes took 572 ms` diyor ama **kullanıcının beklediği süre bu değil**: token alma, ağ gecikmesi, JSON parse ve render onun dışında; Render uykudaysa o 30-60 saniye backend logunda hiç görünmez (Python henüz çalışmıyor). `frontend/js/logger.js` bu boşluğu kapatıyor.

- **Neden ayrı dosya:** `logger.py` Python, container'da çalışıyor; bu kod kullanıcının tarayıcısında. İki farklı çalışma ortamı, hatta iki farklı makine — modül paylaşılamaz. Ortak olan **tasarım**: aynı `HH:MM:SS | LEVEL | scope | mesaj` biçimi, aynı seviyeler, aynı eşik kuralı (varsayılan 1000 ms), böylece iki tarafın logları yan yana okunabiliyor. Renkler ANSI yerine `console.log`'un `%c` biçimlendiricisiyle.
- **Ayar `localStorage` ile** (tarayıcıda ortam değişkeni yok): `localStorage.setItem('log_level','debug')`, `localStorage.setItem('slow_ms','500')`.
- **Decorator'ın JS karşılığı `Logger.timed(fn, label, scope)`** — sade tarayıcı JS'inde decorator sözdizimi yok (standart değil, derleyici ister), ama **fikir aynı**: fonksiyonu zarfla sarmalayıp ölçümü dışarıda tutmak. Yani higher-order function; decorator, bunun sözdizimsel şekeri. Sunumda "aynı desen, iki dilde" olarak anlatılabilir.
- **Asıl ölçüm `apiRequest()` içinde** (`api.js`): bütün istekler oradan geçtiği için tek yere yazılan ölçüm hepsini kapsıyor — çağıran hiçbir dosya değişmedi. Backend'de aynı işi `@timed` yapıyordu.
- **Giriş/çıkış ARTIK ÖLÇÜLÜYOR** — ve yalnızca burada ölçülebilirdi: Faz 6'dan beri giriş tarayıcı ile Firebase arasında geçiyor, sunucumuza hiç uğramıyor, backend logunda izi yok. `sign in (password)`, `create account`, `sign in (Google popup)`, `sign out` ölçülüyor. Google popup'ının eşiği bilerek 10 sn: ölçülen süre kullanıcının hesap seçme süresini de içeriyor, sistem yavaşlığı değil.
- **`Logger.timed` gerçekten kullanılıyor:** `search.js`'teki `renderResults` onunla sarmalandı (eşik 100 ms). Gözden geçirmede fark edildi ki fonksiyon yazılmış ama hiçbir yerde çağrılmıyordu — decorator'ı anlatan bir projede ölü kod olarak durması zayıflıktı. Üstelik ölçtüğü şey tam da "backend'in göremediği maliyet": yanıt geldikten sonra kullanıcı sonuçları ancak DOM'a çizim bitince görüyor. Fonksiyon bildirimi `const renderResults = Logger.timed(function (data) {...})` hâline geldi; çağrı yerlerinin ikisi de olay işleyicilerinin içinde olduğu için hoisting sorunu yok.
- **"Yavaş" eşiği frontend'de de uç nokta başına** (`SLOW_THRESHOLDS`, `api.js`): tarayıcı testinde ortaya çıktı ki tek genel eşik (1 sn) `commentary` ve `from-image`'i sürekli sarı yakıyordu — oysa backend'de bu uçların eşiği 5 sn olduğu için **aynı istek backend'de yeşil, frontend'de sarı** görünüyordu. `commentary` 5 sn, `from-image` 8 sn (base64 fotoğraf yüklemesi frontend ölçümüne dahil, backend ölçümü istek geldikten sonra başlıyor), diğerleri varsayılan.
- **Firebase oturum beklemesi ayrıca loglanıyor — ve MPA'nın bedelini ölçüyor.** `apiRequest`'in ölçümü `await authReady`'yi de kapsıyor; sayfa açıldıktan sonraki **ilk** istekte bu bekleme yerelde ~450 ms, canlıda ~975 ms sürebiliyor. Loglanmasaydı konsolda "istek 1.47 s sürdü" yazarken backend "1.4 ms" diyecekti ve aradaki fark açıklamasız kalacaktı. Bekleme 100 ms'yi aşınca INFO olarak yazılıyor (`waited ... for Firebase auth state (first request on this page)`). **Bu bedel her sayfa geçişinde yeniden ödeniyor** — SPA'da bir kez ödenirdi; Faz 1'deki "React değil MPA" kararının ölçülmüş maliyeti bu.
- **Yalnızca frontend'in görebildiği durumlar:** `fetch` hiç dönmezse (sunucu kapalı, DNS, CORS reddi) backend'de hiçbir kayıt olmaz — bu ERROR sadece tarayıcıda görünür. `getToken` 100 ms'yi aşarsa uyarı (SDK önbellekten vermeyip Firebase'e gitmiş demektir). Sayfa yükleme süresi Navigation Timing API ile.
- Dağınık 3 `console.warn` (mikrofon, kamera, doğrulama maili) sisteme bağlandı; frontend'de artık başıboş `console.*` yok.
- **Script sırası:** `logger.js` kendisini kullanan her dosyadan önce yükleniyor (4 sayfada da). Tarayıcıda klasik `<script>`'lerin top-level `const`'ları paylaşılır — `firebase.js`'in `const auth`/`const authReady`'si zaten bu şekilde çalışıyordu, `const Logger` da aynı desende.
**Gözden geçirmede çıkan 4 kusur (hepsi düzeltildi):**
1. **`localStorage` erişimi uygulamayı düşürebilirdi (en ciddisi).** Safari gizli modda / site verileri engellendiğinde `localStorage.getItem` **okurken bile** `SecurityError` fırlatıyor. Bu çağrı modül kurulumunda olduğu için `Logger` hiç tanımlanmaz, onu ilk satırında kullanan `api.js` komple çökerdi — auth guard, `apiRequest`, kullanıcı menüsü hepsi ölürdü. Yani log sistemi uygulamayı düşürürdü. `setting()` yardımcısı try/catch ile sarıldı, ayar okunamazsa varsayılana dönüyor.
2. **Sayfa yükleme süresi her zaman `0.0 ms` basardı.** `PerformanceNavigationTiming.duration` = `loadEventEnd - startTime`, ve `loadEventEnd` **`load` olayı tamamlandıktan sonra** yazılıyor; handler'ın içinde okununca henüz 0. `setTimeout(..., 0)` ile bir tik bekleniyor, yine boşsa `performance.now()`'a düşülüyor. Sessiz bir hataydı — yanlış değer basar, hata vermezdi.
3. **`getToken` yanlış alarm verecekti.** Ölçüm `await authReady`'yi de kapsıyordu; sayfa ilk açılışında oturumun geri yüklenmesi yüzlerce ms sürebildiği için **her sayfa yüklemesinde** sahte bir "yavaş" uyarısı çıkardı. İkisi ayrıldı: oturum bekleme → DEBUG, gerçek token yenileme → INFO.
4. **Biçim backend ile uyuşmuyordu** ("aynı satır biçimi" iddiası yanlış oluyordu): seviye adı `WARN` idi (backend `WARNING`), scope alanı 9 karakter idi (backend 10). İkisi de hizalandı — iki tarafın logları yan yana konduğunda sütunlar birebir örtüşüyor.

Ayrıca `res.json()` başarısız olursa (sunucu/proxy JSON olmayan bir hata sayfası döndüğünde) istek ölçümü hiç loglanmadan kayboluyordu; artık ERROR olarak yazılıyor.

**Bilinen sınır:** DevTools'ta **"Preserve log" açık olmalı**. Bu bir MPA — giriş yapınca sayfa `search.html`'e gidiyor ve konsol varsayılan olarak temizleniyor, yani `sign in took ...` satırı basılıyor ama görülemiyor. `logger.js` başlığına da not düşüldü.

- **Doğrulama:** 8 JS dosyası `node --check`'ten geçti; `Logger` Node'da sahte bir tarayıcı ortamında çalıştırılıp davranışı test edildi — seviye filtresi, eşik (812 ms → INFO, 1.24 s → WARNING), `localStorage` ayarları, `timed()`'ın senkron/async/hata yolları (hata ERROR yazılıp yukarı fırlatılıyor), süre biçimi. nginx yeni dosyaları sunuyor (`js/logger.js` 200).

### Faz 13c (yerel ↔ canlı karşılaştırması) ✅
Ölçüm altyapısının ilk gerçek getirisi: canlıdaki yavaşlığın **ne kadarı ağ, ne kadarı sunucu** sorusu artık cevaplanabiliyor. Aynı sorgu (`gluten free quick chicken dinner`) iki ortamda çalıştırılıp her iki uçtan da ölçüldü.

| Ölçüm | Yerel | Canlı (Render/Vercel) |
|---|---:|---:|
| Tarif detayı — **backend** | 3.0 ms | **2.8 ms** |
| Arama — **backend** | 300–440 ms | **~5.4 s** |
| Ağ (bağlantı kurulmuşken) | ~5–10 ms | **~227 ms** |
| Ağ (sayfanın ilk isteği, TLS dahil) | ~0 ms | ~490 ms |
| Firebase oturum beklemesi | ~450 ms | ~975 ms |
| `renderResults` | 0.6 ms | 0.2 ms |

**Ayrıştırma yöntemi:** tarif detayı endpoint'i sunucuda neredeyse hiç iş yapmıyor, dolayısıyla canlıdaki süresi neredeyse tamamen ağ. Aramadaki fazlalıktan bu ağ payı düşülünce geriye **sunucudaki hesap farkı** kalıyor.

**Sonuçlar:**
- **Tarif detayı iki ortamda da ~3 ms** → sunucu aynı işi aynı hızda yapıyor; oradaki fark tamamen taşıma.
- **Arama backend'i 0.3 s → 5.4 s (12–18x)** → bu **ağ değil, CPU**. Render ücretsiz katman **0.1 vCPU** veriyor ve sorgu embedding'i (ONNX) CPU'ya bağlı. Render Logs'ta `chromadb query took ~5 s` satırı bunu doğruluyor; Metrics sekmesindeki CPU grafiği ikinci bağımsız kanıt.
- **`renderResults` iki ortamda da aynı** → o kod kullanıcının tarayıcısında çalışıyor, sunucudan bağımsız. Ölçümün doğru şeyi ölçtüğünün kontrolü: ortamdan bağımsız olması gereken tek şey gerçekten bağımsız çıktı.
- **AI yorumu için net sonuç YOK:** yerel 835 ms–1.15 s, canlı 818–960 ms — aralıklar çakışıyor. Gemini gecikmesi zaten değişken; "canlı daha hızlı" demek için tekrarlı ölçüm gerekir.

**Yöntem notu:** ölçüm bir ara `scripts/benchmark.py` ile otomatikleştirilmişti (commit `a72f3af`), sonra kaldırıldı (`3c8034b`) — karşılaştırma elle yapılıyor: yerelde `docker compose logs -f api`, canlıda Render → Logs, iki tarafta da tarayıcı konsolu. Script geri istenirse `git checkout a72f3af -- scripts/`.

**Dosya adı `logger.py`, `logging.py` DEĞİL** — ikincisi standart kütüphanenin `logging` modülünü gölgeleyip her şeyi kırardı (`api/` düz bir klasör, importlar çıplak).

**Doğrulama (yerel Docker, yeniden build edilmiş image, gerçek endpoint'ler):**
- Metin araması referansla **birebir aynı** sonuçları döndürüyor (17450/37913/306021) — ölçüm kodu davranışı değiştirmiyor. Kırılım: `extract_filters` 0.2 ms, `chromadb query` 482 ms, toplam 484 ms.
- Gerçek HTTP yolu (route + CORS middleware + `@timed`, `dependency_overrides` ile token atlanarak): **200 + doğru CORS header'ı**; eksik gövde alanı hâlâ **422**; sahte/bozuk token hâlâ **401**. OpenAPI şemasında `SearchRequest` gövdesi ve `authorization` header parametresi yerinde → `functools.wraps` imzayı koruyor.
- WARNING yolları: sonuçsuz arama, olmayan tarif, zaten favoride olan tarif, olmayan favorinin silinmesi, eşiği aşan süre.
- ERROR yolları: bozuk base64 ile vision hatası (`llm` ERROR → `main` ERROR → endpoint yine **200 + anlamlı mesaj** döndü, yani Faz 11b'nin "500 verme" kuralı bozulmadı).
- Kota simülasyonu (ilk model 429 fırlatacak şekilde monkeypatch): `WARNING Model gemini-3.1-flash-lite unavailable, falling back` → `INFO gemini gemini-3.5-flash took 2.28 s`; hepsi tükendiğinde `ERROR All models exhausted` + hata yukarı fırlatılıyor.
- Favoriler (gerçek Firestore): ekleme / duplike reddi / detaylı listeleme / silme / olmayanı silme — hepsi eskisiyle aynı, ölçüm satırlarıyla birlikte. Test kaydı silindi.
- `LOG_LEVEL`, `LOG_COLOR`, `SLOW_MS` container içinde ayrı ayrı doğrulandı; startup satırları `docker compose logs`'ta anında ve **tek kez** görünüyor (handler mükerrer eklenmiyor).

## Faz 12 (Faz 11 TAMAMLANDI ✅)

### Faz 12 (Giriş/kayıt akışının olgunlaştırılması) ✅
**Soru neydi:** "E-posta doğrulamayı zorunlu kılsak Google girişi işlevsiz kalır mı?"

**Cevap: hayır, tam tersi.** Google ile giren kullanıcılar Firebase'e **doğrulanmış olarak** geliyor (`emailVerified: true`) — Google e-postanın sahipliğini zaten kanıtlamış. Projedeki gerçek kullanıcılarla doğrulandı: `google.com` sağlayıcılı hesapların hepsi `emailVerified: true`. Yani doğrulama zorunluluğu yalnızca şifreyle kayıt olanları etkiler; Google girişi "mail beklemeden gir" kısayolu hâline gelir. `api.js` bunu zaten biliyor, banner'ı Google kullanıcılarına hiç göstermiyor.

**Zorunlu doğrulama (sert kapı) BİLEREK YAPILMADI:** doğrulama mailleri spam'e düşüyor (gönderen `noreply@<proje>.firebaseapp.com`, SPF/DKIM yok — Faz 6'da tespit edildi, kendi domain'imiz olmadan çözümü yok). Sunum sırasında yeni bir hesap açılıp mail spam'e düşerse giriş kilitlenir; bu risk, zorunlu doğrulamanın kazandıracağından pahalı. Sunumdan sonra düşünülebilir.

**Yapılanlar:**
- **Şifre sıfırlama (yeni — gerçek bir eksikti).** `sendPasswordResetEmail` hiçbir yerde yoktu, yani şifresini unutan kullanıcının hesabına dönüş yolu yoktu. Giriş formuna "Forgot your password?" eklendi (`.link-btn` — `<a>` değil `<button>`, çünkü bir yere gitmiyor eylem tetikliyor). Maili ve şifre değiştirme sayfasını Firebase sunuyor.
  - **Hesap varlığı açıklanmıyor:** "bu e-posta kayıtlı değil" demek, saldırgana sistemdeki adresleri tek tek sorgulatır. Mesaj her durumda aynı: *"If an account exists for X, a reset link is on its way."*
  - Firebase tarafında etkin olduğu Admin SDK ile doğrulandı (üç hesap için de `generate_password_reset_link` çalıştı).
- **Doğrulama banner'ı tamamlandı.** "Resend email" zaten vardı; eklenen **"I've verified"** butonu `user.reload()` ile sunucudan taze durumu çekip banner'ı kaldırıyor. Bu olmadan kullanıcı maildeki linke tıklasa bile banner sayfa elle yenilenene kadar duruyordu — doğrulama başka sekmede yapılıyor, bu sekmedeki kullanıcı nesnesi eskimiş kalıyor. Mesaja spam klasörü uyarısı da eklendi.

**Doğrulama:** tarayıcıda kullanıcı test etti, şifre sıfırlama çalışıyor.

**Değerlendirilip yapılmayanlar:** yumuşak kapı (doğrulanmadan favori eklenememesi) — savunulabilir bir tasarım kararı, sunumda anlatılabilir; Google butonunu görsel olarak öne çıkarma — zorunlu doğrulama gelirse şart olur.

## Faz 11 (Faz 10 TAMAMLANDI ✅)

### Faz 11 (Performans — algılanan hız) ✅
Canlıya çıktıktan sonra kullanıcı üç yavaşlık bildirdi: arama bazen 10sn, favoriler yavaş, AI bazen hiç cevap vermiyor. Üçü de ayrı sebeplerdi.

- **Arama artık LLM'i BEKLEMİYOR (en büyük kazanç).** `search_recipes` ve `search_recipes_from_image` `generate_answer`'ı senkron çağırıyordu; tarifler ChromaDB'den ~0.3sn'de hazır oluyor ama endpoint Gemini bitene kadar dönmüyordu. Ölçüm (yerel Docker, gerçek endpoint fonksiyonları): **arama 0.32sn, Gemini 8.55sn, eski toplam 8.87sn**. Yani kullanıcı elde hazır duran sonuçları 8.5sn boyunca göremiyordu. Faz 6'da "asıl iyileştirme" diye ertelenen iş buydu.
  - Yeni endpoint: **`POST /api/recipes/commentary`** (`{query, recipe_ids}` → `{answer}`). Arama yanıtından **`answer` alanı kaldırıldı**.
  - **Tarif bilgisi istemciden değil ID'lerden okunuyor.** İstemcinin gönderdiği metinle prompt kurmak LLM'e keyfi içerik enjekte etmeye kapı açardı; `recipe_ids` ile ChromaDB'den okunuyor, 10 ID ile sınırlı.
  - Frontend: sonuçlar anında basılıyor, AI kutusu **iskelet + shimmer** animasyonuyla bekliyor (`.llm-skeleton`, `prefers-reduced-motion` destekli), cevap gelince yerini alıyor. **Cevap gelmezse kutu sessizce gizleniyor** — kota dolduğunda sayfa çalışmaya devam ediyor, eskiden "AI commentary is temporarily unavailable" metni basılıyordu.
  - Arka arkaya aramada eski yorumun yenisinin üstüne düşmemesi için `commentarySeq` sıra koruması var (yorum isteği yavaş olduğu için gerçek bir yarış).
- **Favoriler N+1 → tek istek.** `favorites.js` önce listeyi çekip **her favori için ayrı** `/api/recipes/{id}` isteği atıyordu (N favori = N+1 istek), her biri ayrıca `verify_id_token()` çalıştırıyordu ve Render'ın **0.1 vCPU**'sunda sıraya giriyordu. `/api/favorites` artık **`include_details=true`** parametresiyle tarif bilgilerini de dönüyor; ChromaDB `get` zaten ID listesi aldığı için hepsi tek çağrıda okunuyor. Varsayılan (`false`) eski şekli koruyor — `recipe.js`'in "bu tarif favoride mi" kontrolü tarif detayını gereksiz indirmesin diye.
- **Favoriler sırası: en son eklenen üstte.** Öncesinde `get_favorites` hiç sıralamıyordu, Firestore doküman ID sırasıyla dönüyordu — ID `{email}_{recipe_id}` olduğu için favoriler *tarif ID'sine göre* diziliyordu, kullanıcı açısından rastgele. Sıralama **Firestore'da değil bellekte** yapılıyor: `where` + `order_by` birlikte kullanılınca Firestore bileşik indeks istiyor (elle kurulacak altyapı adımı), favori sayısı küçük olduğu için buna değmez.
- **Tekrar eden kart kodu birleşti:** aynı 15 satırlık sözlük 3 yerde kopyaydı → `_recipe_card()` + `_cards_from_query()`.

**Gemini kota limiti — Google yayınlamıyor ama 429 HATASI SÖYLÜYOR.** Resmi rate-limits sayfası somut RPM/RPD vermiyor ("AI Studio'da bakın"), üçüncü taraf kaynaklar çelişiyor (1.500/250/20). **Kesin cevap kotayı doldurunca hata gövdesinden geldi:**
```
quotaId:    GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: 20        model: gemini-2.5-flash
```
Yani **model başına günde 20 istek**. Kritik ayrıntı `PerModel`: kota model başına ayrı — bu, aşağıdaki çoklu-model çözümünün dayanağı.

### Faz 11b (kamera aramasının çökmesi — kök sebep) ✅
**Belirti:** Canlıda kamera araması `Could not reach the server.` veriyordu; tarayıcı konsolunda `blocked by CORS policy: No 'Access-Control-Allow-Origin'` yazıyordu. **CORS yapılandırması suçlu değildi** (metin araması aynı origin'den sorunsuz çalışıyordu).

**Zincir:** `detect_ingredients_from_image` hata yakalamadan çağrılıyordu → Gemini 429 → endpoint 500 → **500 yanıtı CORS middleware'ine uğramadan çıkıyor** (Starlette'in hata katmanı en dışta, `add_middleware` ile eklenen CORS onun içinde kalıyor) → header eksik → tarayıcı gerçek sebebi gizleyip CORS hatası gösteriyor. TestClient ile birebir üretildi: normal istek `200 + header`, hata fırlatan istek `500 + header yok`.

**İki katmanlı çözüm:**
1. **Kök sebep — çoklu model (`llm.py`).** Kota model başına olduğu için tek modele bağlı kalmak, o modelin 20 isteği bitince kamera aramasının tamamen ölmesi demekti. Artık sırayla denenen listeler var; 429/404 alınca sonrakine geçiliyor (başka hata türlerinde geçilmiyor — bozuk istekte denemeye devam etmek yanıltıcı olurdu). Pratikte 3 ayrı kota havuzu.
   - `COMMENTARY_MODELS = (gemini-3.1-flash-lite, gemini-3.5-flash, gemini-2.5-flash)`
   - `VISION_MODELS = (gemini-3.5-flash, gemini-3.1-flash-lite, gemini-2.5-flash)`
   - Sıralar bilerek farklı: biri diğerinin kotasını tüketmesin. Yorum hafif iş → en hızlı model başta; malzeme tanıma asıl görsel iş → daha güçlü model başta.
   - **Ölçüm (aynı prompt):** `gemini-3.1-flash-lite` **0.65sn**, `gemini-3.5-flash` 5.17sn, `gemini-2.5-flash` ~8.5sn. Yorum süresi 8.55sn → **0.68sn** (~12x). Elenenler: `gemini-2.5-flash-lite` (404, "no longer available to new users"), `gemini-2.0-flash-lite` (429, ayrı havuz değil).
2. **Belirti — anlamlı hata (`main.py`).** Vision çağrısı `try/except` ile sarıldı; hata olursa 500 yerine `{"error": ...}` dönüyor (200 olduğu için CORS header'ı da yerinde). Kota hatası ayrı mesaj alıyor: *"Daily AI quota reached, so photo search is unavailable right now. Text search still works."*

**Doğrulama (`gemini-2.5-flash` kotası DOLU iken):** yorum 0.68sn'de geldi, vision 1.24sn'de çalıştı, kamera endpoint'i `200 + CORS header + anlamlı mesaj` döndü. Yani geçiş mekanizması gerçek bir kota tükenmesinde test edildi, simüle edilmedi.

**Ders:** FastAPI'de yakalanmamış bir istisna → 500 → CORS header'ı yok → tarayıcıda hata CORS gibi görünür. Konsolda beklenmedik bir CORS hatası görünce önce sunucunun 500 verip vermediğine bakılmalı.

**Doğrulama (yerel Docker, gerçek endpoint fonksiyonları):** boş sonuç yolu (`ids: [[]]`) patlamıyor; yorum boş/olmayan ID'de Gemini'yi hiç çağırmadan `None` dönüyor; favorilerde silinmiş tarif `recipe: None` oluyor, diğerleri sağlam; kart↔favori eşleşmesi doğru (ChromaDB sıra garantisi vermediği için map kullanıldı); `include_details=false` eski şekli koruyor; arama sonuçları referansla birebir aynı (17450/37913/306021). **Tarayıcıda kullanıcı doğruladı:** arama sonuçları anında geliyor, AI yorumu animasyonla yükleniyor, kamera aramasında da aynı, kalp butonu ekleme/çıkarma doğru çalışıyor.

**Bilinen sınır:** Render ve Vercel ayrı ayrı deploy oluyor, atomik değil. Push sonrası kısa bir pencerede eski/yeni karışabilir; iki yön de zarif bozuluyor (eski frontend → "No suggestion available."; eski backend → `/commentary` 404 → kutu gizlenir), çökme yok. Deploy sonrası `Ctrl+Shift+R` iyi olur.

## Faz 10 (Faz 9 TAMAMLANDI ✅)

### Faz 10 (Canlıya çıkış — Render + Vercel) ✅
- **Backend → Render** (`https://recipe-rag-assistant-api-7g6a.onrender.com`). Ücretsiz katman (512 MB / 0.1 vCPU, kartsız), Frankfurt. Docker'ı kökteki `Dockerfile`'dan build ediyor. Sırlar env var olarak: `GEMINI_API_KEY`, `FIREBASE_CREDENTIALS_JSON`. Her push'ta otomatik yeniden deploy.
- **Frontend → Vercel** (`https://recipe-rag-assistant.vercel.app`). Root Directory = `frontend`, statik site (build yok). `firebase-auth` dalını izliyor.
- **Platform seçim hikâyesi:** Önce HF Spaces seçildi ve kod ona göre hazırlandı — ama HF, **Docker SDK'sını ücretli-only yaptı** (2026 Temmuz ortası, duyurusuz; WebSearch ile doğrulandı). Kod HF'e özel değildi (kök Dockerfile, env-var sırlar, stateless), o yüzden Render'a geçiş sorunsuz oldu; tek HF izi README metadata'sıydı, o da temizlendi. Cloud Run (kart gerekli) ve Oracle (kart + ham VM + ARM) elendi; Render kartsız + yönetilen olduğu için seçildi.
- **Faz 10'da yapılan kod değişiklikleri:**
  - `frontend/js/config.js` (yeni) — `window.API_BASE`'i ortama göre kuruyor; `api.js` bunu kullanıyor. `config.js`, `api.js`'ten önce yükleniyor (3 sayfada: search/recipe/favorites).
  - `Dockerfile` `CMD` artık `$PORT`'u dinliyor (`${PORT:-8080}`, `sh -c exec` ile) — Render portu kendi veriyor. Yerelde 8080'e düşüyor.
  - `main.py` CORS: `["*"]` → Vercel domain + `allow_origin_regex` (preview + localhost/LAN).
  - `auth.py` (Faz 9'da eklenmişti): `FIREBASE_CREDENTIALS_JSON` env var'ından kimlik okuyabiliyor — Render'da dosya yok, JSON metni env var olarak veriliyor.
- **Deploy döngüsü:** yerelde değiştir → `docker compose` ile test → `git push origin firebase-auth` → Render (backend) ve Vercel (frontend) otomatik yeniden deploy. Yerel image = canlı image (tek Dockerfile), o yüzden "yerelde çalışıyor" güçlü garanti.
- **Render uykusu:** ücretsiz katman 15 dk sessizlikten sonra uyur, ilk istek ~30-60 sn. Sunum öncesi bir kez uyandır. (Cloud Run'da bu ~1 sn olurdu — kartsızlığın bedeli.)
- **Doğrulama:** canlı backend 200/422/401, CORS canlıda doğru (Vercel izinli, evil.com red), Vercel sitesi 200 ve doğru `config.js`'i sunuyor (Render'ı gösteriyor). Giriş + arama masaüstünde uçtan uca çalışıyor (kullanıcı doğruladı).

## Faz 9 (Faz 8 TAMAMLANDI ✅)

### Faz 9 (favorites → Firestore, `chromadb` servisinin kaldırılması) ✅
- **Neden:** Favoriler çalışma anında değişen tek veriydi, dolayısıyla kalıcı disk ve ayrı veritabanı servisi ihtiyacının **tek** sebebiydi. Ayrıca ChromaDB bu iş için yanlış aletti: her kayda sahte bir `[[0.0] * 384]` embedding yazılıyordu — vektör veritabanı anahtar-değer deposu gibi kullanılıyordu. Firestore zaten "ödenmiş" bir maliyetti: `firebase-admin` ve service-account anahtarı Faz 6'da Auth için kurulmuştu.
- **Ne yapıldı:** `favorites.py` Firestore'a geçti (`firestore.client()`, `favorites` koleksiyonu, doküman ID'si yine bileşik: `{email}_{recipe_id}` — duplike engelleme aynı şekilde çalışıyor). `docker-compose.yml`'den `chromadb` servisi ve `chroma_data` volume tanımı kaldırıldı, `CHROMA_HOST` ve `depends_on` çıktı.
- **`main.py` HİÇ DEĞİŞMEDİ:** `favorites.py` aynı üç fonksiyonu aynı imzalarla ve aynı `ValueError`'larla veriyor. Faz 6'nın aynadaki görüntüsü — orada favoriler auth değişiminden etkilenmemişti, burada da main favoriler değişiminden etkilenmedi.
- **Doğrulama (chromadb container'ı tamamen kaldırılmış hâlde):** arama aynı sonuçları döndürüyor (17450/37913/306021), tarif detayı çalışıyor, favorilerde ekleme / listeleme / duplike reddi / silme / olmayanı silme reddi — hepsi eskisiyle aynı davranıyor, hata mesajları dahil.
- **Yan kazanç:** `firestore.client()` **tembel**, ağ bağlantısını import anında kurmuyor. ChromaDB `HttpClient` kuruyordu ve bu yüzden servis kapalıyken API hiç açılmıyordu (Faz 8'de canlı görüldü). Artık veri deposu erişilemese bile API açılır, sadece favori istekleri hata verir.
- **Firestore kurulumu:** Native mode, konum kalıcı olarak seçildi. Güvenlik kuralları "production mode" (kilitli) — doğrusu bu, çünkü backend **Admin SDK** ile bağlanıyor ve Admin SDK güvenlik kurallarını atlıyor; frontend Firestore'a hiç doğrudan dokunmuyor, her şey API'den geçiyor.
- **Eski favoriler taşınmadı** (bilinçli karar, Faz 6'daki `users` kararıyla tutarlı). `recipe-rag-assistant_chroma_data` volume'ü **silinmedi** — eski kayıtlar geri dönüş için duruyor.

**Son durum:** 2 container (`api` ~180MB RAM + `frontend`), image 1.2GB, kalıcı disk yok, yazılan hiçbir yerel veri yok.

## Faz 8 (Faz 7 TAMAMLANDI ✅)

### Faz 8 (`recipes` koleksiyonunun image'a gömülmesi) ✅
- **Ne yapıldı:** `load_to_chromadb.py` artık `HttpClient` yerine `PersistentClient` ile `api/chroma_data/` klasörüne yazıyor; `main.py` bu klasörü doğrudan açıyor (`PersistentClient(path=.../chroma_data)`). Yol `__file__`'a göre hesaplanıyor — lokalde `api/chroma_data`, container'da `/app/chroma_data`, aynı kod ikisinde de çalışıyor. Arama artık ChromaDB sunucusuna bağlı değil.
- **Doğrulama:** gömülü veriyle dönen sonuçlar sunucudakiyle **birebir aynı** — "gluten free quick chicken dinner" → 17450/37913/306021 (filtre `gluten_free` + `total_time<=30` dahil), "vegan pasta with mushrooms" → 182637/457871/535596. Detay endpoint'i ve favoriler de çalışıyor. Image 1.14GB → **1.2GB** (+35MB veri).
- **`chromadb` servisi HÂLÂ GEREKLİ:** `favorites.py` ona bağlı. Dahası `favorites.py:6` bağlantıyı **import anında** kuruyor, yani servis kapalıyken API hiç açılmıyor (canlı denendi: `ValueError: Could not connect to a Chroma server`). Faz 9'da favoriler Firestore'a taşınınca servis tamamen kalkacak.

### Faz 8 sırasında karşılaşılan/çözülen konular
- **⚠️ ChromaDB `PersistentClient` Windows'ta HNSW indeksini diske YAZMIYOR** (en önemli bulgu, canlı doğrulandı): chromadb 1.5.9 ile Windows'ta ingestion çalışıyor, script kendi içinde `count: 4886` diyor, ama **yeni bir process** aynı klasörü açtığında `count`/`query`/`get` hepsi patlıyor: `InternalError: ... Error loading hnsw index`. Sebep: indeks klasörüne sadece `index_metadata.pickle` yazılıyor, asıl vektör dosyaları (`data_level0.bin`, `header.bin`, `length.bin`, `link_lists.bin`) hiç oluşmuyor. Aynı script **Linux container'da** çalıştırıldığında dosyaların hepsi yazılıyor ve yeni process sorunsuz okuyor (minimal repro ile ayrıca doğrulandı). Sqlite'ta 4886 embedding duruyor, yani veri kaybı değil — sadece indeks materyalize olmuyor.
  **Sınır düzeltmesi (Faz 9'da öğrenildi):** sorun **yazmada**, okumada değil — Windows, Linux'un ürettiği indeksi sorunsuz **okuyabiliyor** (`count: 4886` döndüğü görüldü). Yani kural "ingestion Linux'ta çalışmalı"; okuma her yerde çalışır.
  **Sonuç: ingestion artık Linux'ta çalıştırılmalı** (hedef ortam zaten Linux, dolayısıyla doğru olan da bu):
  ```
  docker run --rm -v "$PWD:/work" recipe-rag-assistant-api \
    sh -c "pip install pandas && python /work/ingestion/load_to_chromadb.py"
  ```
  (`pandas` API image'ında yok — ingestion'ın bağımlılığı, API'nin değil.)
- **`PersistentClient` bir klasörü AÇARKEN BİLE `chroma.sqlite3`'e yazıyor** (işletim sisteminden bağımsız): `-v ...:/data:ro` ile denendiğinde doğrudan `attempt to write a readonly database` veriyor. İki sonucu var:
  - Image'a `COPY` edilen veri container'ın **yazılabilir katmanında** olduğu için sorun çıkmıyor. Ama veri ileride read-only bir volume'dan mount edilmek istenirse bu duvara çarpılır.
  - **Repodaki `api/chroma_data`'ya script yöneltmek, commit edilmiş 28MB'lık dosyayı kirletiyor** — git'te sahte bir değişiklik çıkıyor (veri bozulmuyor, `git checkout api/chroma_data/chroma.sqlite3` ile geri alınıyor). Bu yüzden `test_search.py` `CHROMA_PATH` env değişkeniyle image'daki kopyaya yöneltilebiliyor; doğru kullanım o.
- **`load_to_chromadb.py`'deki `✓` karakteri Windows'ta script'i çöktürüyordu** (`UnicodeEncodeError`, cp1254 konsol kodlaması). Veri yüklendikten sonraki son `print`'te patlıyordu; düz metne çevrildi. İlk teşhiste bu çökmenin indeks sorununun sebebi sanıldı — değilmiş, iki ayrı sorun.
- **35MB veri git'e commit edildi:** `recipes_cleaned.csv` `.gitignore`'da (`*.csv`), dolayısıyla repodan build alan bir platform (HF Spaces gibi) veriyi yeniden üretemez — gömülü verinin repoda olması şart. Repo 831KB → `.git` 19MB. **Not:** ileride her yeniden ingestion git geçmişine ~35MB'lık yeni bir blob ekler.


### Faz 7 (Deploy hazırlığı — torch'un kaldırılması) ✅
- **Neden:** Deploy için yer aranırken image'ın **2.83GB** olduğu görüldü; `site-packages` tek başına 1.7GB, bunun 750MB'ı `torch`. Ücretsiz platformların çoğuna sığmıyordu (Vercel serverless 250MB, Render free 512MB RAM → torch açılışta OOM).
- **Bulgu:** `pip show torch` → `Required-by: sentence-transformers`. Torch'u **tek** isteyen paket `sentence-transformers`'dı, o da tek bir satır içindi (`SentenceTransformer('all-MiniLM-L6-v2')`). `transformers`, `scipy`, `scikit-learn`, `sympy` de aynı kuyruktan geliyordu. Bu sırada fark edildi ki `onnxruntime` **zaten kurulu** (ChromaDB bağımlılığı) ve ChromaDB'nin varsayılan embedding fonksiyonu **birebir aynı modeli** (`all-MiniLM-L6-v2`) ONNX motoruyla çalıştırıyor. Yani aynı model image'da iki kez, iki farklı motorla taşınıyordu.
- **Kalite kanıtı (değişiklikten ÖNCE ölçüldü):** 12 sorguda torch ve ONNX'in döndürdüğü **top-5 tarif ve sıralama birebir aynı (12/12)**; iki vektör arasındaki en büyük sayısal fark **2.35e-07** (float32 yuvarlama gürültüsü, model farkı değil). Ayrıca `query_texts` ile elle embed etmenin aynı sonucu verdiği doğrulandı (4/4) — `get_collection()` sonrası aktif EF `DefaultEmbeddingFunction`.
- **Sonuç:** `sentence-transformers` requirements'tan çıktı, `main.py` ve `load_to_chromadb.py` embedding'i elle üretmeyi bıraktı (`query_texts` / sadece `documents`), Dockerfile'dan CPU-only torch kurulumu **ve** `build-essential` kalktı (build onlarsız test edildi, geçiyor). Net: 4 dosya, 27 satır silindi / 14 eklendi.

| | Önce | Sonra |
|---|---|---|
| Image | 2.83 GB | **1.14 GB** |
| site-packages | 1.7 GB | 522 MB |
| RAM (açılışta) | 568 MB | **123 MB** |
| Embedding modeli hazır | 5.2 sn | **0.70 sn** |
| Bir sorguyu encode | 175 ms | 244 ms |
| Arama sonuçları | — | **birebir aynı** |

- **RAM nüansı:** 123MB açılış değeri. Torch `main.py` import edilirken **eager** yükleniyordu; ONNX ise ilk aramada **tembel** yükleniyor, sonrasında ~310MB'a çıkıyor. Yine de eskisinin yarısı ve ilk yükleme 0.70sn.
- **Encode 70ms yavaşladı** — bilinçli kabul: aramanın ~3.5 saniyesini Gemini yiyor, bu fark ölçüm gürültüsü. Karşılığında model yükleme 5.2sn → 0.70sn, ki bu doğrudan soğuk başlangıç süresi.
- **Yeniden ingestion GEREKMEDİ:** vektörler aynı olduğu için mevcut 4886 embedding geçerli kaldı; koleksiyon yeniden yüklenmeden çalıştığı doğrulandı.
- **Tuzak (çözüldü):** ChromaDB ONNX modelini çalışma anında indiriyor (~79MB, ölçüldü **~70sn**). Dockerfile'a build zamanında indiren `RUN` adımı eklendi; image'da 167MB olarak duruyor, çalışma anında indirme olmadığı doğrulandı. Atlanırsa kazanılan 5sn, 70sn olarak geri verilir.
- **Beklenti düzeltmesi:** 1.14GB hâlâ Vercel'in 250MB limitinin üstünde — **API Vercel'e taşınamaz**, o kapı kapalı. Kazanç: ücretsiz Docker platformlarına rahat sığan bir boyut.
- **Doğrulama:** gerçek `search_recipes` endpoint fonksiyonu çağrıldı (testler değil, asıl kod yolu) — filtre çıkarımı, ChromaDB araması ve Gemini cevabı çalışıyor, koleksiyon 4886 tarifle ayakta. Ardından **tarayıcıdan uçtan uca doğrulandı**: gizli sekmede (önbelleğe takılmamak için) yapılan arama, değişiklik öncesiyle **aynı tarifleri** döndürdü. Faz 7 kapandı.

### Faz 6 (Firebase Auth Migrasyonu) ✅ — `firebase-auth` branch'inde
- **Neden:** Kendi JWT'mizi imzalamak, bcrypt ile şifre hash'lemek ve Google ID token'ını elle doğrulamak bakım yükü ve güvenlik sorumluluğu getiriyordu. Firebase bunların hepsini üstleniyor.
- **Backend:** `auth.py` sadece `verify_id_token()` yapıyor. `/api/auth/register`, `/api/auth/login`, `/api/auth/google` endpoint'leri **silindi** (Firebase client-side hallediyor), `/api/auth/me` kaldı. `passlib`, `bcrypt`, `python-jose`, `google-auth` bağımlılıkları çıktı; `firebase-admin` girdi. Net: 185 satır silindi, 23 eklendi.
- **Frontend:** `localStorage`'daki `recipe_token` mekanizması tamamen kalktı; token artık `getIdToken()`'dan geliyor ve otomatik yenileniyor. Google butonu Google'ın kendi widget'ından kendi butonumuza döndü (`signInWithPopup` + `prompt: 'select_account'` — yoksa tarayıcıdaki tek oturumu otomatik seçip hesap seçtirmiyor).
- **Eski kullanıcılar taşınmadı** (bilinçli karar): ChromaDB'deki `users` koleksiyonu silinmedi ama artık okunmuyor — geri dönüş için duruyor, çünkü kod `git` ile geri alınabilir, veritabanı verisi alınamaz. Eski şifreli hesaplar Firebase'de yok; sahipleri yeniden kayıt olmalı. Eski Google kullanıcıları ise Firebase ilk girişte otomatik hesap açtığı için sorunsuz devam ediyor.
- **Favoriler kendiliğinden taşındı:** e-posta anahtarlı oldukları için auth sistemi değişse de eşleşmeye devam ettiler.
- **Doğrulanmış senaryolar (8/8):** kayıt, şifreyle giriş, Google ilk kayıt, Google ile giriş, doğrulanmamış şifre→Google (şifre silinir), doğrulanmış şifre→Google (bağlanır, ikisi de çalışır), Google'lıya şifreyle giriş (reddedilir), Google'lıya şifreyle kayıt (engellenir).

### Faz 6 sırasında karşılaşılan/çözülen konular
- **Firebase doğrulanmamış şifreyi siliyor** (en önemli bulgu, canlı gözlemlendi): Şifreyle kayıt olup e-postasını **doğrulamadan** aynı adresin Google hesabıyla giren kullanıcının şifresi Firebase tarafından **sessizce yok ediliyor** — hesap `['password']` iken `['google.com']` oluyor. Hata fırlatmıyor, otomatik yapıyor. Sebebi hesap ele geçirme savunması: saldırgan sahibi olmadığı bir adresle şifreli hesap açmış olabilir; gerçek sahip Google ile girip sahipliğini kanıtlayınca doğrulanmamış şifre imha ediliyor. **Çözüm e-posta doğrulaması:** doğrulanmış adreste Firebase şifreye güvenip Google'ı *yanına* ekliyor (`['password', 'google.com']`) ve ikisi de çalışıyor. Bu yüzden kayıtta `sendEmailVerification()` çağrılıyor ve doğrulamamış kullanıcılara `api.js`'de hatırlatma bandı gösteriliyor. "Şifre doğrulama olmadan hayatta kalsın" seçeneği **yok**, Firebase bunu bilerek engelliyor.
- **Giriş↔search sonsuz yönlendirme döngüsü**: `authReady` başta `onAuthStateChanged`'in **ilk** tetiklenişini kullanıyordu. Bu ilk değer, oturum kalıcılıktan geri yüklenmeden önce geçici bir `null` olabiliyor — search sayfası bunu "giriş yok" sanıp index'e atıyor, index gerçek kullanıcıyı görüp geri gönderiyordu. `authStateReady()`'ye geçilerek çözüldü. (Ara adımda şüphelenilen `setPersistence(LOCAL)` çağrısı da kaldırıldı: web'de varsayılan zaten LOCAL, gereksizdi.)
- **Account linking otomatik değil**: Firebase "her email için tek hesap" ile dedup'ı otomatik yapıyor ama iki kimliği **bağlama** adımını bilerek geliştiriciye bırakıyor (güvenlik). `auth.js`'de `account-exists-with-different-credential` yakalanıp kullanıcıdan şifresi isteniyor, sonra `linkWithCredential` ile bağlanıyor. Not: doğrulanmamış şifre senaryosunda Firebase bu hatayı hiç fırlatmadan otomatik ezdiği için bu kod yolu tetiklenmiyor — asıl çözüm yine e-posta doğrulaması.
- **nginx bind-mount önbelleği**: Windows/WSL2'de `./frontend` mount'unda nginx dosyayı önbelleğe alıp disk değişikliklerini sunmuyor. Kod değişti ama tarayıcı eskisini görüyorsa `docker restart recipe_frontend` gerekiyor (tarayıcı önbelleği için de `Ctrl+Shift+R`). Gerekirse nginx'e `sendfile off` eklenebilir.
- **Doğrulama mailleri spam'e düşüyor**: Gönderici `noreply@<proje>.firebaseapp.com`, bizim kontrolümüzde olmadığı için SPF/DKIM yok. Kendi domain'in olmadan çözümü yok; geliştirme aşamasında kabul edilmiş sınır. Test sırasında Admin SDK'nın `generate_email_verification_link()` fonksiyonuyla link doğrudan üretilip maili beklemeden doğrulama yapılabiliyor.
- **Gmail `+alias` Google girişinde çalışmaz**: `x+test@gmail.com` sadece bir mail teslimat takma adı, **Google hesabı değil**. Şifre↔Google etkileşimini test ederken e-posta, gerçekten giriş yapılabilen bir Google hesabı olmalı; aksi halde senaryo hiç tetiklenmez.
- **`prompt: 'select_account'` şart**: Yoksa Firebase tarayıcıdaki tek Google oturumunu otomatik seçip hesap seçme ekranını hiç göstermiyor, farklı hesapla giriş imkânsız hale geliyor.

### Faz 5 (Google OAuth + Sesli Arama + Kullanıcı Menüsü + Docker) ✅
> ⚠️ Bu fazdaki **Google OAuth** işi Faz 6'da tamamen Firebase'e devredildi — aşağıdaki iki madde artık tarihsel kayıt, kodda karşılığı yok (`verify_google_token()`, `create_or_get_google_user()`, `POST /api/auth/google`, `GOOGLE_CLIENT_ID` ve `recipe_token`'ın hepsi silindi).
- **Google OAuth (ARTIK YOK)**: `auth.py::verify_google_token()` Google Identity Services'ten gelen ID token'ı `google-auth` kütüphanesiyle doğruluyordu, `create_or_get_google_user()` kullanıcıyı oluşturuyor ya da mevcut şifreli hesabı `both`'a yükseltiyordu. Endpoint: `POST /api/auth/google`.
- **Google sign-in butonu (ARTIK YOK)**: Google'ın kendi buton widget'ı kullanılıyordu, callback JWT'ye çevrilip `recipe_token` akışına giriyordu. Yerini Firebase `signInWithPopup` ve kendi butonumuz aldı.
- **Sesli arama**: `search.js`'de Web Speech API ile mikrofon butonu, `continuous: true` + `interimResults: true` ile konuşma bitene kadar canlı transkript arama kutusuna yazılıyor. Tarayıcı desteklemiyorsa buton otomatik gizleniyor.
- **Kullanıcı menüsü**: `api.js` her sayfada kullanıcının emailini header'da gösteriyor ve dropdown içinde sign out seçeneği sunuyor. (Faz 6 notu: e-posta artık `/api/auth/me` çağrısıyla değil, doğrudan `auth.currentUser.email`'den okunuyor — ekstra istek gerekmiyor.)
- **Docker Compose**: `chromadb` + `api` + `frontend` üç servis olarak tek `docker-compose.yml`'de. `api/Dockerfile` ve `frontend/Dockerfile` eklendi, `requirements.txt` container build'i için genişletildi.

### Faz 4 TAMAMLANDI ✅ (önceki durum)

### Faz 3 (Backend + Auth + Favoriler) ✅
> ⚠️ 3.1–3.3'teki auth işleri **Faz 6'da Firebase'e devredildi** — tarihsel kayıt. Kayıt/giriş endpoint'leri silindi, JWT üretimi kalktı. Korumalı endpoint mantığı (`get_current_user_email` dependency'si) aynı kaldı, sadece içi Firebase doğrulamasına döndü.
- 3.1 Kayıt endpoint'i ✅ *(artık yok — Firebase client-side)*
- 3.2 Giriş endpoint'i ✅ *(artık yok — Firebase client-side)*
- 3.3 Arama endpoint'i token ile korundu ✅ *(artık Firebase ID token)*
- 3.4 Fotoğraftan malzeme tanıma ✅ (Gemini vision)
- 3.5 Fotoğraf endpoint'i ✅ (/api/recipes/from-image)
- 3.6 Favoriler sistemi ✅ (/api/favorites/add, /api/favorites, /api/favorites/{recipe_id})

### Faz 4 (Frontend) ✅
- 4.1 Giriş/kayıt sayfası ✅ (index.html, "What's in your kitchen?" hero, sekmeli form)
- 4.2 Arama sayfası ✅ (search.html, text + camera sekmeleri, sonuç kartları, LLM cevabı kutusu)
- 4.3 Tarif detay sayfası ✅ (recipe.html, 5 sütunlu bilgi çubuğu, numaralı adım kartları, kalp favori butonu)
- 4.4 Favoriler listesi sayfası ✅ (favorites.html, boş durum ekranı ile)
- 4.5 Ortak API katmanı ✅ (api.js, token yönetimi + fetch wrapper + otomatik logout)

### Faz 3 sırasında eklenen ek işler
- **Tarif detay endpoint'i** (`GET /api/recipes/{recipe_id}`): Kullanıcı arama sonuçlarından bir tarife tıkladığında instructions dahil tüm detayları getirir. Hem text hem image search sonuçlarından çağrılabilir, arama yöntemine bağımlı değil.
- **Instructions veri temizliği düzeltmesi**: `RecipeInstructions` kolonu R vector formatında (`c("adım1", "adım2")`) ChromaDB'ye ham haliyle yükleniyordu. `clean_data.py`'ye `parse_instructions()` fonksiyonu eklendi, `instructions_clean` kolonu üretiliyor ve numaralı adımlara çevriliyor (`"1. ... 2. ..."`). ChromaDB yeniden yüklendi.
- **Favoriler mimarisi**: `favorites.py`, `auth.py` ile aynı desende — kendi ChromaDB koleksiyonunu (`favorites`) kendi yönetiyor. Bileşik ID (`{user_email}_{recipe_id}`) ile duplike kayıt engelleniyor. `main.py` sadece `add_favorite()`, `get_favorites()`, `remove_favorite()` fonksiyonlarını çağırıyor, ChromaDB detaylarını bilmiyor.

### Faz 4 sırasında karşılaşılan/çözülen konular
- **CORS**: Frontend (Live Server, `127.0.0.1:XXXXX`) ile backend (FastAPI, `localhost:8080`) farklı origin'ler. `main.py`'ye `CORSMiddleware` eklendi, `allow_origins=["*"]` (geliştirme için, production'da kısıtlanacak).
- **Gemini model deprecation**: İkinci Gemini API key alındığında yeni Google Cloud projesinde `gemini-2.5-flash` "no longer available to new users" hatası verdi. `llm.py`'de model adı `gemini-flash-latest` alias'ına çevrildi — Google bu alias'ı her zaman en güncel flash modeline yönlendiriyor, gelecek deprecation'lardan korumalı. **Sonrası (Faz 6):** bu karar geri alındı, alias'ın işaret ettiği model 503 verdiği için `gemini-2.5-flash`'a dönüldü (bkz. aşağıdaki "Arama yavaşlığı" maddesi). 2.5'e erişim bu arada açılmış.
- **Arama yavaşlığı — suçlu LLM değil, alias'tı** (Faz 6'da ölçüldü): Arama ~20sn sürüyordu. Adım adım ölçüm: embedding 0.04sn, filtre 0.00sn, ChromaDB 0.27sn, **Gemini 20.14sn** (toplamın %98.5'i). Yani **tarifler 0.3sn'de hazırdı**, kod sadece LLM'i bekliyordu. Sebep araştırması: thinking kapatmak fayda etmedi (21.8sn), 5 token'lık "say hi" bile 20.3sn sürdü, TCP+TLS el sıkışma 0.16sn (ağ sağlam). Ham HTTP isteği **503 UNAVAILABLE** döndürdü → `gemini-flash-latest`'in işaret ettiği model free tier'da aşırı yüklü, SDK 503'ü görüp retry ediyor ve süre 20sn'ye çıkıyordu. `gemini-2.5-flash` aynı istekte ort. **3.5sn** (~6x). **"Asıl iyileştirme" olarak not edilen iş Faz 11'de YAPILDI:** tarifler artık LLM beklenmeden dönüyor, AI yorumu ayrı istekle geliyor (8.87sn → 0.32sn).
- **Gemini free tier kota limiti**: Yoğun test günlerinde takılıyor. **Kesin rakam bilinmiyor — Google artık yayınlamıyor** (Faz 11'de araştırıldı: resmi rate-limits sayfası "AI Studio'da bakın" diyor, üçüncü taraf kaynaklar 1.500/250/20 gibi çelişen rakamlar veriyor). Kendi limitini görmek için: <https://aistudio.google.com/rate-limit>. Faz 11'den beri kota dolması zararsız: arama LLM'den bağımsız çalışıyor, sadece yorum kutusu gelmiyor.
- **Diyet tag sıralaması**: `search.js` ve `recipe.js`'de aktif diyet tag'leri `[vegan, vegetarian, pescatarian, gluten_free, dairy_free, nut_free]` sırasıyla gösteriliyor — yemek türü bilgisi allergen-free bilgisinden önce görünüyor.
- **Instructions parse edge case**: Bazı tariflerin ham verisinde R vector'daki boş elementler `,` veya `\` gibi anlamsız karakterlere çevrilmiş, bu da 17 tane sahte adım oluşturuyordu. `recipe.js`'deki `parseInstructions()` fonksiyonu 3 karakterden kısa ve sadece noktalama içeren parçaları filtreliyor. Sağlıklı tarifleri etkilemiyor.
- **Live Server + `file://` protokolü**: `getUserMedia` API'si `file://` üzerinde çalışmıyor, HTTP sunucusu şart. VS Code Live Server extension kullanılıyor.

## Veri Nerede Duruyor (güncel — Faz 9 sonrası)

**Image'a gömülü ChromaDB (`api/chroma_data/`, sunucu yok):**
- `recipes` — 4886 tarif (bkz. yukarıdaki alanlar). Salt-okunur; `main.py` `PersistentClient` ile okuyor.

**Firestore (`favorites` koleksiyonu):**
- Kullanıcı favorileri (user_email, recipe_id, added_at). Doküman ID'si bileşik: `{email}_{recipe_id}`.

**Firebase Auth:** kullanıcılar (Faz 6'dan beri).

**Ölü veri — `recipe-rag-assistant_chroma_data` volume'ünde (servis kaldırıldı, volume geri dönüş için duruyor):**
- `favorites` — Faz 9 öncesi favoriler. Taşınmadı (bilinçli karar).
- `users` — Faz 6 öncesi kullanıcılar (email, hashed_password, auth_provider, created_at).
- `recipes` — servisteki eski kopya; Faz 8'den beri okunmuyor.

## Arama Akışı Kararı (Faz 3/4)
Üç bağımsız kullanım senaryosu:
1. Sadece metin → /api/recipes/search
2. Sadece fotoğraf (metin boş) → /api/recipes/from-image
3. Fotoğraf + opsiyonel ek metin → /api/recipes/from-image (additional_text dolu)
Fotoğraftan tanınan malzemeler asla otomatik olarak text kutusuna yazılmaz, 
ayrı bir "Detected: ..." alanında gösterilir. Text kutusu her zaman kullanıcının 
kontrolünde, bağımsız kalır.

**Detay sayfası akışı:** Her iki arama yönteminden dönen sonuçlarda `id` alanı var.
Kullanıcı sonuç listesinden bir tarife tıkladığında `GET /api/recipes/{recipe_id}` 
çağrılır (instructions dahil tüm detayları döner). Bu endpoint arama yönteminden 
bağımsız, tek bir ortak detay sayfası mantığı.

## Frontend Mimari Akışları (Faz 4)

**Sayfa akışı:**
- `index.html` → giriş/kayıt → başarılı olunca `search.html`'e yönlendirme (`window.location`)
- `search.html` → arama sonuçları → tarif kartına tıklayınca `recipe.html?id=XXX`
- `recipe.html` → detay + favori butonu → "Back to search" ile geri, ya da header'daki "Favorites" ile favoriler listesine
- `favorites.html` → favori kartlar → detay sayfasına

**Token yönetimi (Faz 6'da Firebase'e geçti):**
- `localStorage`'daki `recipe_token` **yok** — oturumu Firebase SDK kendi kalıcı deposunda yönetiyor
- `firebase.js` `authReady` promise'ini üretir: `authStateReady()` ile oturum durumunun **kesinleşmesini** bekler
- Auth guard `authReady` üzerinden çalışır: korumalı sayfada kullanıcı yoksa `index.html`'e, giriş sayfasında kullanıcı varsa `search.html`'e yönlendirir
- `apiRequest()` wrapper'ı her istekte `getIdToken()` ile taze token alıp `Authorization: Bearer` header'ına koyar (SDK süresi dolan token'ı otomatik yeniler)
- Backend 401 dönerse `signOut()` + `index.html`'e yönlendirme
- Sign out butonu tüm sayfalarda header'daki kullanıcı menüsünde

**Kamera akışı (`search.js`):**
- Start camera → `navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}})`
- Take photo → `<canvas>`'a çizip `canvas.toDataURL('image/jpeg', 0.85)` ile base64
- Search with photo → base64 backend'e, `stream.getTracks().forEach(t => t.stop())` ile kamera serbest
- Sekme değişirse veya sayfa kapanırsa kamera stop
- Detected ingredients ayrı bir kutuda (asla input'a yazılmıyor — Faz 3 kararı korundu)

**Favori butonu (`recipe.js`):**
- Sayfa yüklendiğinde `GET /api/favorites` çağrılıp bu tarif listede mi kontrol
- Kalp boşsa (`♡`) POST `/api/favorites/add`, doluysa (`♥`) DELETE `/api/favorites/{id}`
- Debounce yok, buton disabled durumu ile double-click önleniyor


## Bilinen Sınırlama: Swagger UI + Custom Header
POST /api/recipes/search endpoint'i token korumalı (Header parametresi kullanıyor; Faz 6'dan beri Firebase ID token). 
Swagger UI'nin "Try it out" arayüzü bu header'ı isteğe eklemede sorun yaşıyor 
(muhtemelen FastAPI/Swagger versiyon uyumsuzluğu). Backend'in kendisi doğru 
çalışıyor - PowerShell Invoke-RestMethod ve frontend ile doğrulandı. Faz 4 
sonrasında frontend tam çalıştığı için bu artık kritik bir problem değil.