/**
 * "Kaydolduktan sonra kaldığım yere dön" niyeti (Faz 29, adım 6).
 *
 * NEDEN VAR: Pinterest'ten gelen ziyaretçi bir tarifte ♡'ye basıyor, kayıt
 * sayfasına gidiyor, kaydoluyor — ve klasik hata burada: boş bir arama
 * sayfasına düşüp geldiği tarifi kaybediyor. Bağlamı kaybettiğin an dönüşümü
 * de kaybediyorsun, çünkü kullanıcı ne istediğini SÖYLEMİŞTİ ve biz unuttuk.
 *
 * NEDEN AYRI DOSYA: niyeti YAZAN sayfa (recipe.html) `api.js` yüklüyor,
 * OKUYAN sayfa (index.html) `auth.js` yüklüyor — ortak yükledikleri bir yer
 * yok. İkisine kopyalamak, aynı kuralı iki yere yazmak olurdu (Faz 15d/19).
 *
 * NEDEN sessionStorage: niyet bir SEKMEYE ait ve tek bir giriş akışı kadar
 * yaşaması gerekiyor. `localStorage` kalıcı olurdu ve haftalar sonra açılan
 * bir sekmede beklenmedik bir yönlendirme üretirdi.
 *
 * NEDEN İKİ AYRI ANAHTAR: iki farklı sayfa iki farklı şeyi tüketiyor —
 * `auth.js` yolu (yönlendirmeden hemen önce), `recipe.js` favori niyetini
 * (dönüşten sonra). Tek kayıt olsaydı ilk okuyan diğerinin verisini de
 * silerdi; "oku ve sil" ancak tek tüketicisi olan bir kayıt için doğru.
 */
const RETURN_PATH_KEY = 'return_path_v1';
const PENDING_FAVORITE_KEY = 'pending_favorite_v1';

// 10 dakika. Giriş akışı saniyeler sürüyor ama kayıt olurken şifre seçme,
// Google hesabı seçme, e-posta doğrulama uyarısı gibi adımlar var.
// Süre sınırsız olsaydı: aynı sekmede A kişisi ♡'ye basıp vazgeçse, sonra
// B kişisi kaydolduğunda A'nın baktığı tarife düşer ve o tarif B'nin
// favorilerine eklenirdi. Faz 20'deki sessionStorage sızıntısının aynı ailesi.
const INTENT_MAX_AGE_MS = 10 * 60 * 1000;

/**
 * Yol kendi sitemizde mi?
 *
 * ⚠️ AÇIK YÖNLENDİRME (open redirect) KORUMASI. Değer bizim yazdığımız
 * sessionStorage'dan geliyor, ama `window.location` bir dizgiyi olduğu gibi
 * izliyor ve bu sınıf hata tam da "bizim verimiz, güvenilir" varsayımından
 * doğuyor.
 *   `//evil.com`  → protokol-GÖRECELİ mutlak adres, tarayıcı dış siteye gider
 *   `/\evil.com`  → bazı tarayıcılarda aynı işi görüyor
 *   `javascript:` → şema kontrolüyle eleniyor
 * Bu yüzden yalnızca tek `/` ile başlayan göreceli yollar kabul ediliyor.
 */
function isSafeReturnPath(path) {
  return typeof path === 'string'
    && path.length > 1
    && path.length < 512
    && path.startsWith('/')
    && !path.startsWith('//')
    && !path.startsWith('/\\')
    && !path.includes('://')
    && !path.includes('\n');
}

function writeStamped(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ value, at: Date.now() }));
  } catch (e) {
    // Safari gizli modda yazmak da okumak da SecurityError fırlatıyor.
    // Özellik sessizce devre dışı kalıyor; giriş akışı etkilenmiyor (Faz 13b).
  }
}

/** Oku ve SİL — her iki niyet de tek kullanımlık. */
function takeStamped(key) {
  let raw;
  try {
    raw = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
  } catch (e) {
    return null;
  }
  if (!raw) return null;

  try {
    const record = JSON.parse(raw);
    if (!record || !record.at) return null;
    if (Date.now() - record.at > INTENT_MAX_AGE_MS) return null;
    return record.value;
  } catch (e) {
    return null;                       // bozuk kayıt: yok say
  }
}

/**
 * Ziyaretçi giriş isteyen bir şeye tıkladı. Nereden geldiğini ve (varsa)
 * hangi tarifi kaydetmek istediğini not al.
 */
function saveReturnIntent(favoriteId) {
  const path = window.location.pathname + window.location.search;
  if (isSafeReturnPath(path)) writeStamped(RETURN_PATH_KEY, path);
  if (favoriteId) writeStamped(PENDING_FAVORITE_KEY, String(favoriteId));
}

/** `auth.js` çağırıyor — yönlendirmeden hemen önce. */
function takeReturnPath() {
  const path = takeStamped(RETURN_PATH_KEY);
  // Güvenlik kontrolü OKURKEN DE yapılıyor: yazma anında geçerli olan bir
  // değerin depoda değiştirilmediğini varsaymıyoruz.
  return isSafeReturnPath(path) ? path : null;
}

/** `recipe.js` çağırıyor — kullanıcı tarife döndükten sonra. */
function takePendingFavorite() {
  return takeStamped(PENDING_FAVORITE_KEY);
}

function clearReturnIntent() {
  try {
    sessionStorage.removeItem(RETURN_PATH_KEY);
    sessionStorage.removeItem(PENDING_FAVORITE_KEY);
  } catch (e) { /* yoksay */ }
}

// Node'da test edilebilsin diye (tarayıcıda `module` tanımsız — Logger ve
// stores.js'teki desenin aynısı).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    isSafeReturnPath, saveReturnIntent, takeReturnPath, takePendingFavorite,
    clearReturnIntent, RETURN_PATH_KEY, PENDING_FAVORITE_KEY, INTENT_MAX_AGE_MS,
  };
}
