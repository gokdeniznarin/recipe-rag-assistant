# Recipe RAG Assistant — Project Context

## Proje Özeti
Üniversite stajı kapsamında geliştirilen, RAG (Retrieval-Augmented Generation) tabanlı bir yemek tarifi öneri web uygulaması. Kullanıcı metin ile ("glutensiz ve hızlı bir tavuk yemeği") ya da kamera ile (dolap/malzeme fotoğrafı çekerek) arama yapabiliyor, sistem uygun tarifleri LLM aracılığıyla önerip gerekçelendiriyor.

## Teknoloji Kararları
- **Backend:** Python, FastAPI
- **Veritabanı:** İki yer, ama **rolleri kesin ayrı** (Faz 8–9'da netleşti): **ChromaDB** yalnızca tarifler için — semantic search + metadata filtreleme aynı yerde yapılıyor (MongoDB kullanılmadı), veri salt-okunur ve image'a gömülü, ortada sunucu yok. **Firestore** ise çalışma anında değişen tek veri olan favoriler için. Eski "sadece ChromaDB" kararı favorileri de oraya koyuyordu; bu yanlıştı — her favori kaydına sahte bir `[[0.0] * 384]` embedding yazılıyordu, yani vektör veritabanı anahtar-değer deposu gibi kullanılıyordu. Ayrıca kalıcı disk ihtiyacının tek sebebi buydu ve deploy'u kilitliyordu.
- **Embedding modeli:** `all-MiniLM-L6-v2` (İngilizce arayüz kararı verildiği için çok dilli model şart değil). Model **ChromaDB'nin kendi varsayılan embedding fonksiyonu** (`DefaultEmbeddingFunction`) üzerinden, **ONNX** motoruyla çalışıyor — `sentence-transformers` + `torch` kurulumu kaldırıldı (bkz. Faz 7). Kod artık embedding'i elle üretmiyor: `collection.query(query_texts=[...])` ile metni doğrudan ChromaDB'ye veriyor, embedding'i o üretiyor.
- **LLM:** Google Gemini API, model **`gemini-2.5-flash`**, `google-genai` kütüphanesi (eski `google-generativeai` deprecated olduğu için güncel kütüphaneye geçildi). Model seçimi iki kez değişti: önce `gemini-2.5-flash` → `gemini-flash-latest` (ikinci API key'in projesinde 2.5'e erişim kapalıydı + alias deprecation'a karşı güvenliydi), sonra **geri `gemini-2.5-flash`'a** — çünkü alias'ın işaret ettiği model free tier'da sürekli **503 (overloaded)** veriyordu, SDK retry'ları her aramayı ~20sn'ye çıkarıyordu. Ölçüm: alias 20.1sn, `gemini-2.5-flash` ort. 3.5sn (**~6x**). Ödünleşim kabul edildi: sabit sürüm ileride deprecate olabilir, o zaman güncel sürüme taşınır (hata mesajı net gelir).
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
- **Hafta 9 (şu an buradayız) — performans:** Faz 11 ✅ — arama LLM'i beklemiyor (8.87sn → 0.32sn), favoriler N+1 kalktı, favori sırası düzeldi. Kalan: `main`'e merge, README/sunum hazırlığı.

## Şu Ana Kadar Tamamlanan Dosyalar (güncel)
### Backend
- `ingestion/explore_data.py` — dataset keşfi
- `ingestion/clean_data.py` — temizleme pipeline'ı, recipes_cleaned.csv üretiyor (instructions_clean dahil)
- `ingestion/validate_tags.py` — diyet etiketi ve veri kalitesi doğrulama scripti
- `ingestion/load_to_chromadb.py` — ChromaDB'ye yükleme. Embedding'i artık elle üretmiyor: `collection.add()`'e sadece `documents` veriliyor, ChromaDB kendi varsayılan fonksiyonuyla (ONNX) embed ediyor. `PersistentClient` ile `api/chroma_data/` klasörüne yazıyor (sunucuya değil). **Linux'ta çalıştırılmalı** — bkz. Faz 8'deki Windows/HNSW bulgusu.
- `ingestion/test_search.py` — arama testleri. Gömülü veritabanını okuyor (sunucu yok). `CHROMA_PATH` env var'ıyla image'daki kopyaya yöneltilebilir — **repodaki `api/chroma_data`'ya yöneltirsen commit'li dosyayı kirletir** (bkz. Faz 8 notları).
- `api/main.py` — FastAPI backend + CORS middleware (Faz 10'dan beri kendi origin'lerimizle sınırlı): /api/recipes/search, /api/recipes/from-image, **/api/recipes/commentary** (Faz 11), /api/recipes/{recipe_id}, /api/favorites/* endpoint'leri. Tarifleri image'a gömülü `chroma_data/` klasöründen `PersistentClient` ile okuyor (Faz 8). Arama endpoint'leri LLM'i beklemiyor (Faz 11).
- `api/chroma_data/` — **git'e commit edilmiş** gömülü tarif veritabanı (35MB: `chroma.sqlite3` + HNSW indeks dosyaları). `load_to_chromadb.py` üretiyor, Dockerfile `COPY . .` ile image'a alıyor.
- `api/auth.py` — tek iş: Firebase Admin SDK ile `verify_id_token()` → e-posta. `get_current_user_email` dependency'si korumalı endpoint'lerde kullanılıyor. (Eskiden JWT + bcrypt + kullanıcı kayıt/giriş vardı; Firebase geçişiyle ~140 satırdan ~30 satıra düştü.)
- `api/llm.py` — Gemini API ile LLM cevap üretimi + fotoğraftan malzeme tanıma (`gemini-2.5-flash`)
- `api/filters.py` — kullanıcı sorgusundan diyet/süre/kalori filtresi çıkarımı
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
- `frontend/js/config.js` — `window.API_BASE`'i ortama göre kuruyor (yerel/LAN → `localhost:8080`, canlı → Render). `api.js`'ten önce yüklenir (Faz 10).
- `frontend/js/api.js` — ortak API katmanı (backend adresini `window.API_BASE`'den alır; Firebase ID token'ı header'a ekleyen fetch wrapper, `authReady` tabanlı auth guard, 401'de otomatik logout, kullanıcı menüsü/email + dropdown sign out, doğrulanmamış e-posta için hatırlatma bandı)
- `frontend/js/auth.js` — giriş/kayıt formu mantığı + Google girişi (Firebase `signInWithPopup`), hesap bağlama (`linkWithCredential`), kayıtta `sendEmailVerification()`
- `frontend/js/search.js` — arama sayfası, mode tabs, kamera stream (`getUserMedia`), sesli arama (`SpeechRecognition`), sonuç render. AI yorumunu ayrı istekle çekiyor (`loadCommentary`, iskelet animasyonu + `commentarySeq` yarış koruması; Faz 11)
- `frontend/js/recipe.js` — detay sayfası, `parseInstructions()` (R vector kalıntılarını filtreliyor)
- `frontend/js/favorites.js` — favorileri tarif bilgileriyle **tek istekte** çekiyor (`?include_details=true`; Faz 11 öncesi her ID için ayrı istek atıyordu)
- `frontend/Dockerfile` — `nginx:alpine`, statik dosyaları doğrudan sunuyor

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
- **`nut_free` etiketinde açık var** (Faz 7'de tesadüfen fark edildi): "nut free cookies for kids" araması `Pine Nut and Almond Cookies` ve `wheat free peanut butter cookies` döndürüyor — ikisi de `nut_free: True` etiketli, yani yanlış. `validate_tags.py` nut kontrolünde 0 çelişki verdiği için doğrulama scriptinin de gözden kaçırdığı bir durum var (muhtemelen "pine nut"/"peanut butter" gibi bileşik adlar kural listesine takılmıyor). Sunumda sorulabilecek türden; `clean_data.py` + `validate_tags.py` birlikte gözden geçirilmeli.

## Şu An Üzerinde Çalışılıyor
- **`firebase-auth` branch'i** (`main`'e henüz merge edilmedi). Faz 6–11'in tamamı bu branch'te. `main` el değmemiş durumda. **Canlı deploy `firebase-auth` dalından yapılıyor** (hem Render hem Vercel bu dalı izliyor), dolayısıyla merge sonrası deploy dalını `main`'e çevirmek gerekecek.
- Repo **GitHub'da**: `github.com/Gokdeniz-hub/recipe-rag-assistant` (Private). Sırlar (`firebase-key.json`, `.env`) gitignored, repoda yok — Render'da env var olarak duruyor.

## Güncel Durum: Faz 11 (Faz 10 TAMAMLANDI ✅)

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

**Gemini kota limiti — Google artık YAYINLAMIYOR.** Resmi rate-limits sayfası somut RPM/RPD vermiyor, "AI Studio'da bakın" diyor. Üçüncü taraf kaynaklar çelişiyor (1.500/gün, 250/gün, 20/gün hepsi geçiyor) — **hiçbirine güvenilmemeli**. Tek doğru kaynak: <https://aistudio.google.com/rate-limit> (kendi API key'iyle). Async LLM değişikliği bu belirsizliği zararsız hâle getirdi: kota dolsa bile arama çalışıyor, sadece yorum kutusu gelmiyor.

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