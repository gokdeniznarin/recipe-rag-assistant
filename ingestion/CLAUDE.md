# Recipe RAG Assistant — Project Context

## Proje Özeti
Üniversite stajı kapsamında geliştirilen, RAG (Retrieval-Augmented Generation) tabanlı bir yemek tarifi öneri web uygulaması. Kullanıcı metin ile ("glutensiz ve hızlı bir tavuk yemeği") ya da kamera ile (dolap/malzeme fotoğrafı çekerek) arama yapabiliyor, sistem uygun tarifleri LLM aracılığıyla önerip gerekçelendiriyor.

## Teknoloji Kararları
- **Backend:** Python, FastAPI
- **Veritabanı:** Sadece ChromaDB (tek veritabanı kararı — hem semantic search hem metadata filtreleme aynı yerde yapılıyor, MongoDB kullanılmıyor)
- **Embedding modeli:** `all-MiniLM-L6-v2` (İngilizce arayüz kararı verildiği için çok dilli model şart değil). Model **ChromaDB'nin kendi varsayılan embedding fonksiyonu** (`DefaultEmbeddingFunction`) üzerinden, **ONNX** motoruyla çalışıyor — `sentence-transformers` + `torch` kurulumu kaldırıldı (bkz. Faz 7). Kod artık embedding'i elle üretmiyor: `collection.query(query_texts=[...])` ile metni doğrudan ChromaDB'ye veriyor, embedding'i o üretiyor.
- **LLM:** Google Gemini API, model **`gemini-2.5-flash`**, `google-genai` kütüphanesi (eski `google-generativeai` deprecated olduğu için güncel kütüphaneye geçildi). Model seçimi iki kez değişti: önce `gemini-2.5-flash` → `gemini-flash-latest` (ikinci API key'in projesinde 2.5'e erişim kapalıydı + alias deprecation'a karşı güvenliydi), sonra **geri `gemini-2.5-flash`'a** — çünkü alias'ın işaret ettiği model free tier'da sürekli **503 (overloaded)** veriyordu, SDK retry'ları her aramayı ~20sn'ye çıkarıyordu. Ölçüm: alias 20.1sn, `gemini-2.5-flash` ort. 3.5sn (**~6x**). Ödünleşim kabul edildi: sabit sürüm ileride deprecate olabilir, o zaman güncel sürüme taşınır (hata mesajı net gelir).
- **Frontend:** Sade HTML/CSS/JS (React/Next.js tercih edilmedi — React öğrenme eğrisi kalan sürede risk yaratıyordu, projenin asıl değeri backend RAG pipeline'ında). Sayfa başına ayrı HTML dosyaları, ortak CSS tek dosyada, her sayfanın kendi JS dosyası. Sayfa yönlendirme klasik `<a href>` ile — SPA değil, MPA. Vercel'e statik site olarak deploy edilebilir yapıda.
- **Frontend tasarım:** Koyu zeytin yeşili (`#2D3B2D`) + krem (`#F5F0E8`) + sıcak turuncu aksan (`#E8824A`) paleti, Playfair Display (serif başlıklar, yemek dergisi hissi) + Inter (UI). Merkezi CSS tokens ile tutarlı stil.
- **Kimlik doğrulama:** **Firebase Auth** (email/şifre + Google). Önceki custom JWT + bcrypt + manuel Google doğrulama kurulumundan tamamen geçildi (bkz. Faz 6). Şifre bizim sunucumuza hiç ulaşmıyor: tarayıcı doğrudan Firebase ile konuşuyor, `getIdToken()` ile alınan ID token her istekte `Authorization: Bearer` header'ına konuyor ve süresi dolunca SDK sessizce yeniliyor. Backend (`api/auth.py`) yalnızca Admin SDK ile `verify_id_token()` yapıp e-postayı çıkarıyor — başka hiçbir kimlik mantığı yok. Frontend Firebase JS SDK'nın **compat** build'ini kullanıyor (mevcut global-script/MPA mimarisini korumak için; modüler SDK sayfalar arası global paylaşımı bozardı). Kullanıcılar artık ChromaDB'de değil Firebase'de. Favoriler e-posta anahtarlı olduğu için migrasyondan hiç etkilenmedi.
- **Kamera:** Tarayıcı `getUserMedia` API'si ile fotoğraf çekme, base64 olarak backend'e gönderilip Gemini vision ile malzeme tanıma (aynı Gemini modeli hem metin üretimi hem vision için kullanılıyor)
- **Sesli arama:** Web Speech API (`SpeechRecognition`/`webkitSpeechRecognition`), `search.js` içinde mikrofon butonuna bağlı. Tarayıcı desteklemiyorsa (polyfill yok) buton feature-detection ile gizleniyor. Tanınan metin doğrudan arama kutusuna yazılıyor (kamera akışındaki "asla otomatik yazma" kararından farklı — burada kullanıcı zaten sesle metin girmek istiyor).
- **Konteynerleştirme:** Docker + Docker Compose — 3 servis: `chromadb` (resmi `chromadb/chroma` image, volume ile kalıcı veri), `api` (`python:3.13-slim`, `uvicorn`, `.env` dosyası `env_file` ile aktarılıyor, `CHROMA_HOST=chromadb` ile servis adı üzerinden bağlanıyor), `frontend` (`nginx:alpine`, sade HTML/CSS/JS olduğu için build adımı yok). Firebase geçişiyle gelen eklemeler: `api` servisine service-account anahtarı salt-okunur mount ediliyor (`GOOGLE_APPLICATION_CREDENTIALS` ile gösteriliyor; anahtar hem `.gitignore` hem `api/.dockerignore` ile korunuyor, ne commit'e ne image katmanına girer), `frontend` klasörü bind-mount edildiği için JS/HTML değişikliği rebuild istemiyor (sadece `docker restart recipe_frontend` — nginx bu mount'ta dosyayı önbelleğe alabiliyor). Faz 7'de torch tamamen kaldırıldı: `api/Dockerfile` artık ne CPU-only torch kuruyor ne de `build-essential` istiyor; onun yerine ONNX embedding modelini **build sırasında** indirip image'a gömüyor (yoksa ChromaDB modeli ilk istekte indiriyor: ~79MB, ölçüldü ~70sn, yani her taze container başlangıcı o kadar gecikirdi).
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
- **Hafta 7 (şu an buradayız) — deploy hazırlığı:** torch'un kaldırılması ✅ (Faz 7) — kalan: şekil sorunu (recipes'i image'a gömme + favorites → Firestore), 4 deploy blocker'ı, `main`'e merge, README, sunum hazırlığı, GitHub'a bağlama

## Şu Ana Kadar Tamamlanan Dosyalar (güncel)
### Backend
- `ingestion/explore_data.py` — dataset keşfi
- `ingestion/clean_data.py` — temizleme pipeline'ı, recipes_cleaned.csv üretiyor (instructions_clean dahil)
- `ingestion/validate_tags.py` — diyet etiketi ve veri kalitesi doğrulama scripti
- `ingestion/load_to_chromadb.py` — ChromaDB'ye yükleme. Embedding'i artık elle üretmiyor: `collection.add()`'e sadece `documents` veriliyor, ChromaDB kendi varsayılan fonksiyonuyla (ONNX) embed ediyor.
- `ingestion/test_search.py` — ChromaDB arama testleri
- `api/main.py` — FastAPI backend + CORS middleware (tüm origin'lere açık, geliştirme için): /api/recipes/search, /api/recipes/from-image, /api/recipes/{recipe_id}, /api/favorites/* endpoint'leri
- `api/auth.py` — tek iş: Firebase Admin SDK ile `verify_id_token()` → e-posta. `get_current_user_email` dependency'si korumalı endpoint'lerde kullanılıyor. (Eskiden JWT + bcrypt + kullanıcı kayıt/giriş vardı; Firebase geçişiyle ~140 satırdan ~30 satıra düştü.)
- `api/llm.py` — Gemini API ile LLM cevap üretimi + fotoğraftan malzeme tanıma (`gemini-2.5-flash`)
- `api/filters.py` — kullanıcı sorgusundan diyet/süre/kalori filtresi çıkarımı
- `api/favorites.py` — favoriler sistemi (Repository Pattern'den esinlenmiş, kendi ChromaDB koleksiyonunu kendi yönetiyor). Firebase migrasyonunda **tek satır değişmedi** — favoriler e-posta anahtarlı ve e-posta her iki auth sisteminde de aynı kimlik.
- `api/Dockerfile` — `python:3.13-slim` tabanlı, `uvicorn` ile 8080 portunda çalıştırıyor. ONNX embedding modelini build sırasında indirip image'a gömüyor. Faz 7'den sonra image **1.14GB** (önceden 2.83GB).
- `docker-compose.yml` — 3 servis: `chromadb`, `api`, `frontend`

### Frontend
- `frontend/index.html` — giriş/kayıt sayfası (Sign in / Create account sekmeleri, "Continue with Google" butonu). Firebase compat SDK script'leri + `firebase.js`, diğer JS'lerden önce yükleniyor (sıra önemli).
- `frontend/search.html` — ana arama sayfası (Text search / Camera search sekmeleri, mikrofon butonu)
- `frontend/recipe.html` — tarif detay sayfası (instructions + kalp butonu ile favori toggle)
- `frontend/favorites.html` — kayıtlı tariflerin listesi (boş durum ekranı ile)
- `frontend/css/style.css` — tüm sayfalar için ortak CSS (design tokens, layout, components, user menu dropdown)
- `frontend/js/firebase.js` — Firebase init + `authReady` promise'i (oturum durumu **kesinleşene** kadar bekler). Her sayfada compat SDK script'lerinden sonra, diğer JS'lerden önce yüklenir.
- `frontend/js/api.js` — ortak API katmanı (Firebase ID token'ı header'a ekleyen fetch wrapper, `authReady` tabanlı auth guard, 401'de otomatik logout, kullanıcı menüsü/email + dropdown sign out, doğrulanmamış e-posta için hatırlatma bandı)
- `frontend/js/auth.js` — giriş/kayıt formu mantığı + Google girişi (Firebase `signInWithPopup`), hesap bağlama (`linkWithCredential`), kayıtta `sendEmailVerification()`
- `frontend/js/search.js` — arama sayfası, mode tabs, kamera stream (`getUserMedia`), sesli arama (`SpeechRecognition`), sonuç render
- `frontend/js/recipe.js` — detay sayfası, `parseInstructions()` (R vector kalıntılarını filtreliyor)
- `frontend/js/favorites.js` — favori listesini çekip her ID için detay endpoint'inden tarif bilgisi paralel çekiyor
- `frontend/Dockerfile` — `nginx:alpine`, statik dosyaları doğrudan sunuyor

## Henüz Yapılmadı
- README + sunum hazırlığı (Faz 5)
- GitHub'a bağlama (Faz 5 sonunda toplu push planlanıyor — henüz sadece lokal Git kullanılıyor)
- **Deploy** (planlanan: frontend → Vercel, API → Docker destekleyen bir platform). **Vercel API'yi hâlâ kaldıramaz**: Faz 7'den sonra image 1.14GB ve bu Vercel'in 250MB serverless limitinin çok üstünde — o kapı kapalı. Adaylar: **Hugging Face Spaces** (ücretsiz, kart istemiyor, 16GB RAM — staj/demo için en düşük sürtünmeli) ya da **Google Cloud Run** (ücretsiz kota yeterli, sıfıra ölçekleniyor, Firebase+Gemini ile aynı ekosistem, ama kart zorunlu). Railway/Fly.io'nun ücretsiz katmanı kalmadı.
- **Deploy'un önündeki asıl mimari engel — "şekil sorunu" (henüz çözülmedi):** Bulut container'ları öldürülüp yeniden başlatılabilir olmalı; diske yazdığın her şey kaybolur, kalıcı disk kiralamak ücretsiz katmanların vermediği şeydir. Backend'in iki ChromaDB koleksiyonu var ve doğaları çok farklı:
  - `recipes` — ingestion ile **bir kez** yazılıyor, sonra sadece okunuyor (`query`/`get`). Çalışma anında tek satır yazılmıyor, boyutu ~8MB. Yani kalıcı disk isteyen bir veritabanı değil, salt-okunur bir dosya. **Image'ın içine gömülebilir** (`PersistentClient` ile API'nin kendi içinde okunur) → ayrı `chromadb` servisi tamamen kalkar.
  - `favorites` — gerçekten çalışma anında değişen tek veri; kalıcı disk ihtiyacının **tek** sebebi bu. **Firestore'a taşınmalı** (`firebase-admin` ve credential'lar zaten kurulu). Ek kanıt: `favorites.py` ChromaDB'ye sahte bir embedding (`[[0.0] * 384]`) yazıyor — vektör veritabanına vektörü olmayan veri konuyor, yani ChromaDB burada yanlış alet.

  İkisi ayrılınca backend **tek, stateless container** olur (3 servis → 1, kalıcı disk → 0) ve barındırma sorunu kendiliğinden çözülür.

### ⚠️ Deploy'da MUTLAKA düzeltilecekler (canlıda patlar)
- **`api.js`'deki `API` sabiti**: şu an `` `http://${window.location.hostname}:8080` `` — bilgisayarda localhost, telefonda LAN IP olarak çözülsün diye böyle. Production'da **bozulur**: frontend ve backend farklı domain'lerde olacak, HTTPS olacak ve `:8080` portu olmayacak (`http://app.vercel.app:8080` üretir → yanlış). Ortama göre ayarlanabilir bir config'e alınmalı (`config.js` ya da build-time değişken).
- **Google girişinde `signInWithPopup` → mobilde sorunlu**: mobil tarayıcılar popup'ları agresif engelliyor; Instagram/Facebook gibi uygulamaların **in-app tarayıcılarında** popup çoğu zaman hiç açılmıyor, iOS Safari'de third-party cookie davranışı ekstra sorun çıkarıyor. Firebase'in mobil önerisi **`signInWithRedirect`**. Yaygın çözüm: cihaza göre seçim (masaüstü popup, mobil redirect) ya da her yerde redirect. Localhost'ta popup çalıştığı için şu an görünmüyor, gerçek kullanıcı telefondan girmeye çalışınca çıkacak.
- **Firebase Authorized domains**: production domain'i Firebase Console → Authentication → Settings → Authorized domains listesine eklenmeli, yoksa Google girişi `auth/unauthorized-domain` verir (şu an listede sadece `localhost` var).
- **CORS**: `main.py`'de `allow_origins=["*"]` (geliştirme için). Production'da gerçek frontend domain'iyle sınırlanmalı.

### Ertelenen küçük iyileştirmeler
- LLM cevabındaki `**bold**` markdown karakterlerinin HTML render'ı (şu an ham metin görünüyor)
- Instructions'daki bazı adımların sonundaki tekil `\` backslash temizliği (dataset veri kalitesi kalıntısı)
- `filters.py` iyileştirmeleri (malzeme çıkarımı, sayısal ifadeler "under 30 minutes", olumsuz ifadeler)
- **`nut_free` etiketinde açık var** (Faz 7'de tesadüfen fark edildi): "nut free cookies for kids" araması `Pine Nut and Almond Cookies` ve `wheat free peanut butter cookies` döndürüyor — ikisi de `nut_free: True` etiketli, yani yanlış. `validate_tags.py` nut kontrolünde 0 çelişki verdiği için doğrulama scriptinin de gözden kaçırdığı bir durum var (muhtemelen "pine nut"/"peanut butter" gibi bileşik adlar kural listesine takılmıyor). Sunumda sorulabilecek türden; `clean_data.py` + `validate_tags.py` birlikte gözden geçirilmeli.

## Şu An Üzerinde Çalışılıyor
- **`firebase-auth` branch'i** (`main`'e henüz merge edilmedi). Firebase Auth migrasyonu (Faz 6) + torch'un kaldırılması (Faz 7) bu branch'te. `main` el değmemiş durumda — sorun çıkarsa `git checkout main` + `docker compose up -d --build` ile eski sisteme dönülebilir (rebuild şart: frontend bind-mount olduğu için dosyalar anında eskiye döner ama API image'ı yeni kalır, yoksa karışım oluşur).
- Repo **hâlâ tamamen lokal** — remote yok, commit'ler hiçbir yere push edilmedi.

## Güncel Durum: Faz 7 (Faz 6 TAMAMLANDI ✅)

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
- **Doğrulama:** gerçek `search_recipes` endpoint fonksiyonu çağrıldı (testler değil, asıl kod yolu) — filtre çıkarımı, ChromaDB araması ve Gemini cevabı çalışıyor, koleksiyon 4886 tarifle ayakta. Not: korumalı endpoint'e HTTP üzerinden Firebase token'ı olmadan girilemediği için fonksiyon doğrudan çağrılarak test edildi; tarayıcıdan uçtan uca doğrulama ayrıca yapılmalı.

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
- **Arama yavaşlığı — suçlu LLM değil, alias'tı** (Faz 6'da ölçüldü): Arama ~20sn sürüyordu. Adım adım ölçüm: embedding 0.04sn, filtre 0.00sn, ChromaDB 0.27sn, **Gemini 20.14sn** (toplamın %98.5'i). Yani **tarifler 0.3sn'de hazırdı**, kod sadece LLM'i bekliyordu. Sebep araştırması: thinking kapatmak fayda etmedi (21.8sn), 5 token'lık "say hi" bile 20.3sn sürdü, TCP+TLS el sıkışma 0.16sn (ağ sağlam). Ham HTTP isteği **503 UNAVAILABLE** döndürdü → `gemini-flash-latest`'in işaret ettiği model free tier'da aşırı yüklü, SDK 503'ü görüp retry ediyor ve süre 20sn'ye çıkıyordu. `gemini-2.5-flash` aynı istekte ort. **3.5sn** (~6x). **Hâlâ açık olan asıl iyileştirme:** tarifleri LLM'i beklemeden döndürüp AI yorumunu asenkron çekmek — algılanan süre 0.3sn'ye iner. Bilinçli olarak ertelendi.
- **Gemini free tier kota limiti**: Günde 20 istek limiti var. Yoğun test günlerinde takılıyor. `llm.py` çağrıları artık `main.py`'de try/except ile sarılı (bkz. "Şu An Üzerinde Çalışılıyor") — kota dolunca arama sonuçları LLM cevabı olmadan da gösteriliyor.
- **Diyet tag sıralaması**: `search.js` ve `recipe.js`'de aktif diyet tag'leri `[vegan, vegetarian, pescatarian, gluten_free, dairy_free, nut_free]` sırasıyla gösteriliyor — yemek türü bilgisi allergen-free bilgisinden önce görünüyor.
- **Instructions parse edge case**: Bazı tariflerin ham verisinde R vector'daki boş elementler `,` veya `\` gibi anlamsız karakterlere çevrilmiş, bu da 17 tane sahte adım oluşturuyordu. `recipe.js`'deki `parseInstructions()` fonksiyonu 3 karakterden kısa ve sadece noktalama içeren parçaları filtreliyor. Sağlıklı tarifleri etkilemiyor.
- **Live Server + `file://` protokolü**: `getUserMedia` API'si `file://` üzerinde çalışmıyor, HTTP sunucusu şart. VS Code Live Server extension kullanılıyor.

## ChromaDB Koleksiyonları (güncel, 3 tane)
- `recipes` — 4886 tarif (bkz. yukarıdaki alanlar)
- `users` — **artık kullanılmıyor** (email, hashed_password, auth_provider, created_at). Faz 6'da kimlik Firebase'e taşındı; bu koleksiyon okunmuyor ama geri dönüş için bilerek silinmedi. Kullanıcılar artık Firebase Auth'ta.
- `favorites` — kullanıcı favorileri (user_email, recipe_id, added_at), bileşik ID ile

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