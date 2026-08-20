/**
 * Service worker — PWA'nın "uygulama gibi davranmasını" sağlayan katman.
 *
 * Tek işi UYGULAMA KABUĞUNU (HTML/CSS/JS/ikon) elde tutmak. Kullanıcı verisi
 * ASLA buraya girmiyor — gerekçe aşağıda.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * 1) API YANITLARI HİÇBİR KOŞULDA ÖNBELLEĞE ALINMIYOR
 * Faz 20'de sessionStorage ile birebir aynı hatayı yaşadık: depolama SEKMEYE
 * özeldi ama KULLANICIYA özel değildi, aynı sekmede hesap değiştirilince önceki
 * kullanıcının aramaları yenisine görünüyordu. Cache Storage aynı tuzağı daha
 * beteriyle taşır — origin başına, kalıcı ve çıkışta temizlenmiyor. Favoriler,
 * dolap, plan, alışveriş listesi burada tutulsaydı ortak bir bilgisayarda
 * doğrudan veri sızıntısı olurdu. Bu yüzden iki ayrı koruma var:
 *   - farklı origin'deki istekler (canlıda Render, yerelde :8080) hiç ele alınmıyor
 *   - ayrıca `/api/` yolu açıkça dışarıda bırakılıyor
 *
 * 2) NETWORK-FIRST (cache-first DEĞİL)
 * Sıradan bir PWA statik dosyaları önce önbellekten verir; hızlıdır ama deploy
 * sonrası kullanıcı bir süre eski JS ile çalışır. Bu projede dosya adlarında
 * hash YOK ve tüm JS global <script> ile yükleniyor, yani "yeni HTML + eski JS"
 * karışımı sessizce ReferenceError üretebilir. Ağ önce denenirse böyle bir
 * karışım hiç oluşmuyor; önbellek yalnızca ağ ERİŞİLEMEZKEN devreye giriyor.
 * Kaybedilen hız da bu uygulamada önemsiz: darboğaz statik dosyalar değil,
 * ölçülmüş 6.4 sn'lik ChromaDB embedding'i (CLAUDE.md Faz 17).
 *
 * 3) SÜRÜM: normal güncellemeler için CACHE_VERSION'ı artırmak GEREKMİYOR —
 * network-first olduğu için çevrimiçi kullanıcı zaten hep tazesini alıyor.
 *
 * ⚠️ AMA BİR İSTİSNA VAR ve Faz 29'da yaşandı: önbellekteki KOPYANIN KENDİSİ
 * hatalıysa, network-first onu yalnızca ağ erişilebildiği sürece gizliyor.
 * Mobil bağlantı titrek olduğunda `fetch` düşüyor, `catch` bloğu devreye
 * giriyor ve BAYAT kopya servis ediliyor. Faz 29'da 8 korumalı sayfanın
 * önbellekteki kopyası, örtü (`auth-pending`) eklenmeden ÖNCEki hâlleriydi —
 * yani o kopya her servis edildiğinde çakma geri geliyordu, ve tam olarak
 * telefonda, yalnızca bazı sayfalarda (hangi isteğin düştüğüne bağlı olarak).
 * Sürümü artırmak eski önbelleği tamamen siliyor ve taze precache kuruyor;
 * bayat bir kopyanın hataya SEBEP olduğu durumda doğru araç bu.
 */

// v3: günlük besin toplamı. Normalde sürüm arttırmak GEREKMİYOR (yukarıdaki
// 3. madde), ama bu değişiklik yukarıdaki İSTİSNANIN ta kendisi: ızgaranın satır
// sayısı 4'ten 5'e çıktı ve `grid-auto-flow: column` yüzünden ESKİ style.css +
// YENİ plan.js karışımı beşinci öğeyi bir sonraki SÜTUNA atar — hafta ızgarası
// görünür biçimde dağılır. Titrek mobil bağlantıda `catch` bloğu tam da böyle bir
// karışım üretebiliyor (Faz 29'da yaşandı). Sürümü arttırmak eski önbelleği
// komple silip taze precache kuruyor, yani o pencere hiç açılmıyor.
const CACHE_VERSION = 'v3';
const CACHE_NAME = `recipe-assistant-${CACHE_VERSION}`;

// Uygulama kabuğu. Çevrimdışıyken bu liste sayesinde sayfalar AÇILIYOR
// (içerik gelmiyor, çünkü içerik API'den geliyor — bilinçli).
const PRECACHE = [
  '/',
  '/index.html',
  '/search.html',
  '/recipe.html',
  '/discover.html',
  '/favorites.html',
  '/collection.html',
  '/pantry.html',
  '/plan.html',
  '/shopping.html',
  '/nutrition.html',
  '/account.html',
  '/privacy.html',
  '/css/style.css',
  '/js/account.js',
  '/js/api.js',
  '/js/auth.js',
  '/js/camera.js',
  '/js/collection.js',
  '/js/config.js',
  '/js/favorites.js',
  '/js/firebase.js',
  '/js/install.js',
  '/js/logger.js',
  '/js/nutrition.js',
  '/js/pantry.js',
  '/js/plan.js',
  '/js/pwa.js',
  '/js/recipe.js',
  '/js/discover.js',
  '/js/intent.js',
  '/js/search.js',
  '/js/shopping.js',
  '/js/stores.js',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/icons/olive-branch.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      // addAll YERİNE tek tek + allSettled: addAll ATOMİK, yani listedeki tek
      // bir dosya 404 verirse kurulum komple başarısız olur ve service worker
      // HİÇ devreye girmez. Bir dosyanın adı değiştiğinde PWA'nın sessizce
      // ölmesindense o dosyasız çalışması yeğ.
      const results = await Promise.allSettled(PRECACHE.map((url) => cache.add(url)));
      const failed = results.filter((r) => r.status === 'rejected').length;
      if (failed) console.warn(`[sw] ${failed}/${PRECACHE.length} precache entries failed`);
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((n) => n.startsWith('recipe-assistant-') && n !== CACHE_NAME)
          .map((n) => caches.delete(n))
      );
      await self.clients.claim();
    })()
  );
});

/**
 * Önbellek anahtarı. Sayfa gezinmelerinde SORGU PARAMETRESİ atılıyor:
 * `recipe.html?id=17450` ve `?id=37913` aynı HTML kabuğu — ayrı ayrı saklansaydı
 * her görüntülenen tarif önbelleğe bir kopya daha eklerdi (sınırsız büyüme).
 */
function cacheKey(request) {
  const url = new URL(request.url);
  return request.mode === 'navigate' ? url.origin + url.pathname : request;
}

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offline — Recipe Assistant</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#F5F0E8;color:#2D3B2D;font-family:system-ui,-apple-system,sans-serif;text-align:center}
  div{padding:2rem;max-width:22rem}
  h1{font-size:1.3rem;margin:0 0 .5rem}
  p{color:#6b6b60;line-height:1.5;margin:0}
</style></head>
<body><div><h1>You're offline</h1>
<p>Recipe Assistant needs a connection to search recipes. Reconnect and try again.</p>
</div></body></html>`;

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Yalnızca GET. POST/PATCH/DELETE zaten hepsi API çağrısı.
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Başka origin'ler (Render API, Firebase SDK, Google Fonts) doğrudan ağa.
  if (url.origin !== self.location.origin) return;

  // İkinci koruma: aynı origin'den servis edilse bile API asla önbelleğe girmez.
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(networkFirst(request));
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const key = cacheKey(request);

  try {
    const fresh = await fetch(request);
    // Yalnızca gerçekten başarılı, kendi origin'imizden gelen, YÖNLENDİRİLMEMİŞ
    // yanıtlar saklanır.
    //   - `basic` = same-origin; opaque/CORS yanıtları buraya hiç düşmemeli.
    //   - `redirected` KRİTİK: yönlendirilmiş bir yanıt önbellekten bir
    //     NAVİGASYONA servis edilirse tarayıcı "a redirected response was used
    //     for a request whose redirect mode is not follow" diye atar ve sayfa
    //     hiç açılmaz. Üstelik cache.match BAŞARILI olduğu için aşağıdaki
    //     offline yedek sayfası da devreye girmez — yani çevrimdışı mod
    //     sessizce tamamen bozulur. (Vercel yol normalizasyonunda yönlendirme
    //     üretebiliyor; sahte-SW harness'ı bu hatayı canlıya çıkmadan yakaladı.)
    if (fresh && fresh.status === 200 && fresh.type === 'basic' && !fresh.redirected) {
      cache.put(key, fresh.clone());
    }
    return fresh;
  } catch (err) {
    // ignoreVary: sunucu `Vary: Accept-Encoding` gönderdiğinde, precache
    // sırasındaki istek ile sayfanın isteği başlık farkı yüzünden EŞLEŞMEYEBİLİR
    // ve çevrimdışı mod sebepsiz çalışmaz. Kabuk dosyaları için varyant yok.
    const cached = await cache.match(key, { ignoreVary: true });
    if (cached) return cached;
    if (request.mode === 'navigate') {
      return new Response(OFFLINE_HTML, {
        status: 200,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }
    throw err;
  }
}
