/**
 * Service worker davranış testi — sahte ServiceWorkerGlobalScope.
 *
 *   node scripts/test_sw.js
 *
 * NEDEN VAR: `sw.js` tarayıcıda, sayfanın DIŞINDA, kendi thread'inde çalışıyor;
 * bir hatası konsolda görünmüyor ve "uygulama çevrimdışı açılmıyor" ya da daha
 * kötüsü "başka kullanıcının verisi görünüyor" şeklinde SESSİZCE ortaya çıkıyor.
 * Sözdizimi kontrolü (check_frontend.js) bunların hiçbirini göremez.
 *
 * Harness yazılır yazılmaz GERÇEK bir hata yakaladı: yönlendirilmiş yanıtlar
 * önbelleğe alınıyordu (aşağıdaki 9. test), ki bu çevrimdışı modu tamamen
 * bozardı — üstelik cache.match başarılı olacağı için offline yedek sayfası
 * bile devreye girmezdi.
 *
 * En kritik testler GİZLİLİK olanları (4–6): kullanıcı verisi taşıyan hiçbir
 * isteğin önbelleğe girmediğini sabitliyorlar. Faz 20'de sessionStorage ile
 * birebir aynı hata yaşandı (hesap değişince önceki kullanıcının verisi
 * görünüyordu) ve Cache Storage'da sonuçları daha ağır olurdu.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ORIGIN = 'https://recipe-rag-assistant.vercel.app';
const SW_PATH = path.join(__dirname, '..', 'frontend', 'sw.js');
// Sürüm sw.js'ten OKUNUYOR, sabit yazılmıyor: Faz 29'da CACHE_VERSION v1→v2
// çıkarıldı ve sabit yazılmış hâli bu süiti kırdı. Testin, sürümün ne olduğuna
// değil önbelleğin DOĞRU KULLANILDIĞINA bakması gerekiyor.
const CACHE = 'recipe-assistant-'
  + /CACHE_VERSION = '([^']+)'/.exec(fs.readFileSync(SW_PATH, 'utf8'))[1];

let pass = 0;
let failures = 0;
const check = (name, cond, extra) => {
  if (cond) { console.log('  ok    ' + name); pass++; }
  else { console.error('  FAIL  ' + name + (extra ? ' :: ' + extra : '')); failures++; }
};

// ── Sahte Cache API ──────────────────────────────────────
class FakeResponse {
  constructor(body, init = {}) {
    this.body = body;
    this.status = init.status === undefined ? 200 : init.status;
    this.type = init.type || 'basic';
    this.redirected = !!init.redirected;
    this.headers = init.headers || {};
  }
  clone() { return new FakeResponse(this.body, this); }
}

class FakeCache {
  constructor() { this.store = new Map(); }
  _key(k) { return typeof k === 'string' ? new URL(k, ORIGIN).href : new URL(k.url).href; }
  async put(k, v) {
    // Gerçek Cache API 200 dışını reddediyor; harness de reddetsin ki
    // sw.js'in status kontrolünü kaldırmak testi kırsın.
    if (v.status !== 200) throw new TypeError('cannot cache a non-200 response');
    this.store.set(this._key(k), v);
  }
  async match(k) { return this.store.get(this._key(k)); }
  async add(url) {
    const res = await ctx.fetch({ url: new URL(url, ORIGIN).href, method: 'GET', mode: 'no-cors' });
    if (!res || res.status !== 200) throw new Error('add failed: ' + url);
    return this.put(url, res);
  }
}

const cacheStorage = new Map();
let netMode = 'online';   // online | offline | 404 | redirect
const handlers = {};

const ctx = {
  console,
  URL,
  Response: FakeResponse,
  caches: {
    async open(name) {
      if (!cacheStorage.has(name)) cacheStorage.set(name, new FakeCache());
      return cacheStorage.get(name);
    },
    async keys() { return [...cacheStorage.keys()]; },
    async delete(name) { return cacheStorage.delete(name); },
  },
  async fetch(req) {
    const url = typeof req === 'string' ? req : req.url;
    if (netMode === 'offline') throw new TypeError('Failed to fetch');
    if (netMode === 'redirect') return new FakeResponse('via-redirect', { redirected: true });
    if (netMode === '404') return new FakeResponse('not found', { status: 404 });
    return new FakeResponse('fresh:' + url);
  },
  self: {
    location: { origin: ORIGIN },
    addEventListener: (type, fn) => { handlers[type] = fn; },
    skipWaiting: async () => {},
    clients: { claim: async () => {} },
  },
};
ctx.self.caches = ctx.caches;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(SW_PATH, 'utf8'), ctx, { filename: 'sw.js' });

const req = (p, opts = {}) => ({
  url: p.startsWith('http') ? p : ORIGIN + p,
  method: opts.method || 'GET',
  mode: opts.mode || 'no-cors',
});

/** null dönerse service worker isteğe HİÇ karışmamış demektir (doğrudan ağa gider). */
function dispatchFetch(request) {
  let responded = null;
  handlers.fetch({ request, respondWith: (p) => { responded = p; } });
  return responded;
}

/**
 * install/activate handler'ları `event.waitUntil(promise)` çağırıyor ama KENDİLERİ
 * bir şey döndürmüyor. Handler'ı doğrudan `await` etmek işi beklemez ve testler
 * precache daha bitmeden çalışır — bu harness'ı yazarken tam olarak bu oldu.
 */
async function runLifecycle(type) {
  let work;
  handlers[type]({ waitUntil: (p) => { work = p; } });
  await work;
}

(async () => {
  // ── 1–2. install: kabuk önbelleğe alınıyor mu ──
  await runLifecycle('install');
  const shell = cacheStorage.get(CACHE);
  check('install precaches the app shell', shell && shell.store.size > 25,
        'size=' + (shell ? shell.store.size : 'none'));
  check('install precaches / and /search.html',
        !!shell.store.get(ORIGIN + '/') && !!shell.store.get(ORIGIN + '/search.html'));

  // ── 3–6. GİZLİLİK: kullanıcı verisi taşıyan hiçbir istek ele alınmamalı ──
  check('POST is not intercepted', dispatchFetch(req('/search.html', { method: 'POST' })) === null);
  check('same-origin /api/ is NOT intercepted (privacy guard 2)',
        dispatchFetch(req('/api/favorites')) === null);
  check('cross-origin Render API is NOT intercepted (privacy guard 1)',
        dispatchFetch(req('https://recipe-rag-assistant-api-7g6a.onrender.com/api/favorites')) === null);
  check('cross-origin Firebase SDK is not intercepted',
        dispatchFetch(req('https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js')) === null);

  // ── 7–8. Çevrimiçi: ağ kazanır, önbellek tazelenir ──
  netMode = 'online';
  let res = await dispatchFetch(req('/js/search.js'));
  check('online: network response is returned', res.body === 'fresh:' + ORIGIN + '/js/search.js');
  check('online: response was written to cache',
        (await shell.match(ORIGIN + '/js/search.js')).body === 'fresh:' + ORIGIN + '/js/search.js');

  // ── 9–10. Navigasyon anahtarından sorgu parametresi düşüyor mu ──
  // Düşmezse görüntülenen HER tarif önbelleğe ayrı bir kopya ekler.
  const before = shell.store.size;
  for (const id of ['17450', '37913', '306021']) {
    await dispatchFetch(req('/recipe.html?id=' + id, { mode: 'navigate' }));
  }
  check('navigation cache key drops ?query (no unbounded growth)',
        shell.store.size === before, `${before} -> ${shell.store.size}`);
  check('navigation cached under bare pathname', !!shell.store.get(ORIGIN + '/recipe.html'));

  // ── 11–12. 404 önbelleğe yazılmamalı (iyi kopyayı ezmesin) ──
  await shell.put('/pantry.html', new FakeResponse('good-cached'));
  netMode = '404';
  res = await dispatchFetch(req('/pantry.html', { mode: 'navigate' }));
  check('404 is returned but NOT cached', res.status === 404);
  check('404 did not overwrite the good cached copy',
        (await shell.match('/pantry.html')).body === 'good-cached');

  // ── 13–15. Çevrimdışı davranışı ──
  netMode = 'offline';
  res = await dispatchFetch(req('/pantry.html', { mode: 'navigate' }));
  check('offline: falls back to cache', res.body === 'good-cached');

  res = await dispatchFetch(req('/never-visited.html', { mode: 'navigate' }));
  check('offline: unknown page gets the offline fallback page',
        res.status === 200 && String(res.body).includes("You're offline"));

  let threw = false;
  try { await dispatchFetch(req('/js/never-existed.js')); } catch (e) { threw = true; }
  check('offline: uncached sub-resource rejects (does not fake a 200)', threw);

  // ── 16. Yönlendirilmiş yanıt önbelleğe GİRMEMELİ ──
  // Bu testi yazan hata gerçekti: önbellekteki redirected yanıt bir navigasyona
  // servis edilince tarayıcı "a redirected response was used for a request whose
  // redirect mode is not follow" diye atar; sayfa açılmaz ve cache.match
  // başarılı olduğu için offline yedek sayfası da devreye girmez.
  netMode = 'redirect';
  await dispatchFetch(req('/plan.html', { mode: 'navigate' }));
  const stored = await shell.match('/plan.html');
  check('redirected response is NOT cached', !stored || !stored.redirected,
        stored ? 'redirected=' + stored.redirected : 'absent');

  // ── 17–19. activate: yalnızca KENDİ eski sürümlerimizi siler ──
  cacheStorage.set('recipe-assistant-v0', new FakeCache());
  cacheStorage.set('some-other-app-cache', new FakeCache());
  await runLifecycle('activate');
  check('activate deletes the previous version', !cacheStorage.has('recipe-assistant-v0'));
  check('activate keeps the current version', cacheStorage.has(CACHE));
  check('activate does not touch unrelated caches', cacheStorage.has('some-other-app-cache'));

  console.log(failures === 0
    ? `\nservice worker checks passed (${pass})`
    : `\n${failures} problem(s)`);
  process.exit(failures === 0 ? 0 : 1);
})();
