/**
 * `api.js` auth guard testi — sahte DOM (Faz 29).
 *
 *   node scripts/test_auth_guard.js
 *
 * NEDEN VAR: Faz 29'da guard'a bir istisna eklendi (`window.PUBLIC_PAGE`) ve
 * bu tek satır İKİ YÖNDE DE sessizce felakete gidiyor:
 *
 *   fazla GEVŞEK → korumalı sayfalar (dolap, plan, favoriler) giriş yapmamış
 *                  ziyaretçiye açılır. Hiçbir hata çıkmaz.
 *   fazla SIKI   → tarif sayfası Pinterest'ten geleni giriş formuna atar,
 *                  yani büyüme kanalının tamamı kapıda ölür. Yine hiçbir
 *                  hata çıkmaz — sayfa "çalışıyor" görünür.
 *
 * `test_auth_gate.js` giriş SAYFASINI (auth.js) test ediyor; burası
 * uygulamanın geri kalanına giren kapı.
 *
 * En değerli test aşağıdaki sonuncusu: hangi HTML dosyalarının kendini açık
 * ilan ettiğini sabitliyor. Bir gün biri işareti kopyala-yapıştır ile başka
 * bir sayfaya taşırsa, o sayfa sessizce herkese açılır.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const FRONTEND = path.join(__dirname, '..', 'frontend');

let pass = 0;
let failures = 0;
const check = (name, cond, extra) => {
  if (cond) { console.log('  ok    ' + name); pass++; }
  else { console.error('  FAIL  ' + name + (extra ? ' :: ' + extra : '')); failures++; }
};

/**
 * api.js'i taze bir sahte ortamda çalıştırır.
 * `user`: null (giriş yok) ya da bir nesne. `publicPage`: sayfanın işareti.
 */
function run(user, publicPage) {
  const redirects = [];
  const shown = new Set();
  const hidden = new Set();

  const makeEl = (marker) => ({
    dataset: { auth: marker },
    classList: {
      add: (c) => { if (c === 'hidden') hidden.add(marker); },
      remove: (c) => { if (c === 'hidden') shown.add(marker); },
      contains: () => false,
      toggle() {},
    },
    addEventListener() {},
    textContent: '',
    style: {},
  });

  const elements = { in: makeEl('in'), out: makeEl('out') };

  // Bağlantısız (detached) eleman: initUserMenu doğrulama bandını böyle kuruyor.
  const detached = () => ({
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    addEventListener() {},
    appendChild() {},
    insertBefore() {},
    prepend() {},
    remove() {},
    setAttribute() {},
    querySelector: () => null,
    querySelectorAll: () => [],
    style: {},
    dataset: {},
    textContent: '',
    innerHTML: '',
    firstChild: null,
  });

  // Faz 29: guard, oturum netleşene kadar sayfayı `html.auth-pending` ile
  // gizliyor. Sınıfın gerçekten kurulup KALDIRILDIĞI teste bağlı — kaldırma
  // unutulursa kullanıcı boş bir sayfa görür ve hiçbir hata çıkmaz.
  const rootClasses = new Set();
  // ⚠️ AYRI bir kayit: `rootClasses` SON durumu tutuyor ve ortu her kosulda
  // kaldirildigi icin son durum HER ZAMAN temiz. Ilk surumde "acik sayfa
  // ortulmuyor" testi bunu kontrol ediyordu ve bir TOTOLOJIYDI — mutasyon
  // testinde yakalandi. Ortunun HIC kurulup kurulmadigini bilmek icin
  // eklemeler ayrica kaydediliyor.
  const everAdded = new Set();
  const removed = new Set();
  // ⚠️ SIRA kaydediliyor: ortunun kaldirilmasi ile yonlendirme arasindaki
  // sira, cakmanin OLUP OLMAMASINI belirliyor (asagidaki teste bak).
  const events = [];

  const documentStub = {
    documentElement: {
      classList: {
        add: (c) => { rootClasses.add(c); everAdded.add(c); },
        remove: (c) => {
          rootClasses.delete(c); removed.add(c);
          if (c === 'auth-pending') events.push('reveal');
        },
        contains: (c) => rootClasses.has(c),
      },
    },
    readyState: 'complete',
    addEventListener() {},
    getElementById: () => null,           // menü/sidebar elemanları yok
    createElement: detached,
    querySelectorAll: (sel) => {
      if (sel === '[data-auth="in"]') return [elements.in];
      if (sel === '[data-auth="out"]') return [elements.out];
      return [];
    },
    querySelector: () => null,
    body: {
      classList: { add() {}, remove() {}, contains: () => false },
      prepend() {},
      appendChild() {},
      insertBefore() {},
      firstChild: null,
    },
  };

  const windowStub = {
    API_BASE: 'https://api.example.com',
    PUBLIC_PAGE: publicPage,
    location: {
      pathname: '/recipe.html',
      get href() { return '/recipe.html'; },
      set href(v) { redirects.push({ to: v, mode: 'push' }); events.push('redirect'); },
      // Faz 29: guard artik `replace()` kullaniyor — geri tusu asla
      // gorulmemesi gereken sayfaya donmesin diye.
      replace(v) { redirects.push({ to: v, mode: 'replace' }); events.push('redirect'); },
    },
    addEventListener() {},
  };

  const noop = () => {};
  const logger = {
    get: () => ({ info: noop, warn: noop, error: noop, debug: noop }),
    timed: (fn) => fn,
    duration: noop,
    fmt: (n) => String(n),
  };

  const sandbox = {
    window: windowStub,
    document: documentStub,
    Logger: logger,
    auth: { currentUser: user, signOut: () => Promise.resolve() },
    authReady: Promise.resolve(user),
    fetch: () => Promise.reject(new Error('no network in tests')),
    performance: { now: () => 0 },
    sessionStorage: { removeItem: noop, getItem: () => null, setItem: noop },
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    console,
    setTimeout,
  };
  sandbox.globalThis = sandbox;

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(FRONTEND, 'js', 'api.js'), 'utf8'), sandbox);
  // `logout()` ayrica cagrilabilsin (401 yolu testi).
  const callLogout = () => sandbox.logout();

  // guard `authReady.then(...)` içinde — mikrogörev kuyruğunun boşalmasını bekle.
  return new Promise((resolve) =>
    setTimeout(() => resolve({ redirects, shown, hidden, rootClasses, everAdded, removed, events, callLogout }), 0));
}

(async () => {
  // ── 1–2. Korumalı sayfa: davranış DEĞİŞMEDİ ────────────
  const protectedOut = await run(null, undefined);
  check('a protected page still bounces a signed-out visitor',
        protectedOut.redirects.some((r) => r.to === '/index.html'), JSON.stringify(protectedOut.redirects));

  const protectedIn = await run({ email: 'a@b.com' }, undefined);
  check('a protected page lets a signed-in user through',
        protectedIn.redirects.length === 0, JSON.stringify(protectedIn.redirects));

  // ── 3–5. Açık sayfa ────────────────────────────────────
  const publicOut = await run(null, true);
  check('a public page does NOT bounce a signed-out visitor',
        publicOut.redirects.length === 0, JSON.stringify(publicOut.redirects));
  check('the signed-out sidebar is revealed', publicOut.shown.has('out'));
  check('the user block is hidden when signed out', publicOut.hidden.has('in'));

  const publicIn = await run({ email: 'a@b.com' }, true);
  check('a public page still serves a signed-in user normally',
        publicIn.redirects.length === 0 && !publicIn.shown.has('out'));

  // ── 6. 🔴 Hangi sayfalar kendini AÇIK ilan ediyor ──────
  // Bu, dosyanın en önemli testi. İşaret kopyala-yapıştır ile başka bir
  // sayfaya geçerse orası sessizce herkese açılır ve hiçbir şey kırılmaz.
  // Liste bilinçli olarak DAR; genişletmek bilinçli bir karar olmalı.
  // Faz 29: tarif sayfası + küratörlü koleksiyon iniş sayfaları. İkisi de
  // Pinterest/Google trafiğinin indiği yerler. Listeye ekleme yapmak
  // BİLİNÇLİ bir karar olmalı — bu test tam da onu zorluyor.
  const ALLOWED = ['recipe.html', 'discover.html'];
  const pages = fs.readdirSync(FRONTEND).filter((f) => f.endsWith('.html'));
  const declared = pages.filter((f) =>
    /PUBLIC_PAGE\s*=\s*true/.test(fs.readFileSync(path.join(FRONTEND, f), 'utf8')));

  check('only the intended pages declare themselves public',
        declared.length === ALLOWED.length && ALLOWED.every((p) => declared.includes(p)),
        `beklenen [${ALLOWED}] · bulunan [${declared}]`);

  // ── 7–10. Kayıt davetleri (Faz 29, adım 5) ─────────────
  // İki yönde de sessiz: davet giriş yapmış kullanıcıya görünürse rahatsız
  // edici ve saçma; giriş yapmamışa görünmezse büyüme kanalının tamamı
  // sessizce çalışmaz — sayfa yine kusursuz görünür.
  check('the signed-out visitor is shown the sign-up prompts',
        publicOut.shown.has('out'));
  check('a signed-in user is never shown them',
        publicIn.hidden.has('out'),
        'initUserMenu [data-auth="out"] bloklarını gizlemeli');

  // Markup'ta da `hidden` ile başlamalılar: JS çalışana kadar geçen sürede
  // (authReady canlıda ~975 ms) davet giriş yapmış kullanıcının ekranında
  // çakardı.
  for (const page of ['recipe.html', 'discover.html']) {
    const html = fs.readFileSync(path.join(FRONTEND, page), 'utf8');
    const blocks = html.match(/<[^>]*data-auth="out"[^>]*>/g) || [];
    check(`${page} starts its sign-up prompts hidden`,
          blocks.length > 0 && blocks.every((b) => /\bhidden\b/.test(b)),
          blocks.filter((b) => !/\bhidden\b/.test(b)).join(' | ') || 'blok yok');
  }

  // ── 11–14. Geri tuşu + çakma (kullanıcı bildirdi, 2026-08-08) ──
  //
  // ⚠️ `replace()` yerine `href =` kullanılırsa geri tuşu ÇALIŞMIYOR gibi
  // görünüyor: ziyaretçi koleksiyon sayfasından "Search"e basıyor, giriş
  // ekranına atılıyor (doğru), geri tuşuna basınca `search.html`'e düşüyor,
  // guard onu yine kovuyor. Asla görülmemesi gereken sayfa geçmişte kalıyor.
  check('the bounce replaces history instead of pushing to it',
        protectedOut.redirects.every((r) => r.mode === 'replace'),
        JSON.stringify(protectedOut.redirects));

  // ── Örtü: KURULUM HTML'de, KALDIRMA api.js'te ──────────
  //
  // ⚠️ İlk sürümde kurulum da api.js'teydi ve bu YANLIŞTI: o dosya <body>'nin
  // SONUNDA yükleniyor, tarayıcı oraya gelene kadar sayfayı çoktan boyamış
  // oluyor — örtü ilk boyamadan SONRA kuruluyordu ve içerik bir an
  // görünüyordu. Kullanıcı bunu İKİ KEZ bildirdi.
  // 🔴 EN KRİTİK TEST. Faz 26c'de ölçüldü: `location.replace()` anında geçiş
  // yapmıyor (~0.25 sn) ve o boşlukta sayfa hâlâ ekranda. İlk sürümde
  // `revealPage()` yönlendirmeden ÖNCE çağrılıyordu — örtü kalkıyor, sayfa
  // görünüyor, sonra tarayıcı geçiş yapıyordu. Kullanıcı çakmayı ÜÇ KEZ
  // bildirdi ve ikisi bu sıradan kaynaklandı.
  check('the cover is NEVER lifted on a page we are leaving',
        !protectedOut.removed.has('auth-pending'),
        `olaylar: ${protectedOut.events.join(' -> ')}`);
  check('and no reveal happens before the redirect',
        protectedOut.events.indexOf('reveal') === -1,
        protectedOut.events.join(' -> '));
  // Kalınan sayfada ise örtü MUTLAKA kalkmalı, yoksa kullanıcı boş ekran görür.
  check('a signed-in user does get the page revealed',
        protectedIn.removed.has('auth-pending'));

  // ── 401 → otomatik çıkış: ÖRTÜ GERİ GELMELİ ───────────
  //
  // iPhone'da yaşandı: Firebase oturumu geri yüklüyor (kullanıcı VAR), guard
  // sayfayı açıyor, sonra ilk API çağrısı 401 alıyor ve buradan çıkışa
  // gidiliyor — kullanıcı korumalı sayfayı bir an görüyordu. Android'de
  // görünmüyor çünkü orada token yenileme çalışıyor ve bu yola hiç girilmiyor.
  // Faz 26c dersinin üçüncü yönlendirme yolundaki hâli.
  {
    const r = await run({ email: 'a@b.com' }, undefined);
    r.callLogout();
    await new Promise((res) => setTimeout(res, 0));
    check('signing out re-covers the page before leaving',
          r.rootClasses.has('auth-pending'),
          `son olaylar: ${r.events.join(' -> ')}`);
  }

  // Kurulum artık HTML'de olduğu için DOSYADAN doğrulanıyor.
  const PROTECTED = ['search.html', 'pantry.html', 'plan.html', 'shopping.html',
                     'nutrition.html', 'favorites.html', 'collection.html', 'account.html'];
  for (const page of PROTECTED) {
    const head = fs.readFileSync(path.join(FRONTEND, page), 'utf8').split('</head>')[0];
    // ⚠️ <head>'DE ve STİL DOSYASINDAN ÖNCE olmak zorunda — asıl hata buydu.
    check(`${page} covers itself in <head>, before the stylesheet`,
          head.includes("classList.add('auth-pending')")
          && head.indexOf('auth-pending') < head.indexOf('css/style.css'));
    // 🔴 ZAMAN AŞIMI SAYFAYI GÖSTERMEMELİ, GİRİŞ SAYFASINA GİTMELİ.
    // Telefondaki çakmanın sebebi tam olarak buydu: mobilde `authReady`
    // 3 sn'yi aşabiliyor (Firebase SDK gstatic'ten iniyor + oturum
    // IndexedDB'den geri yükleniyor; masaüstünde ~975 ms ölçülmüştü),
    // zaman aşımı sayfayı açıyor, sonra guard yönlendiriyordu.
    // Korumalı bir sayfada "göster" hiçbir zaman doğru yedek değil.
    const timeout = head.slice(head.indexOf('auth-pending'));
    check(`${page} falls back to the login page, not to showing itself`,
          /location\.replace/.test(timeout) && !/classList\.remove/.test(timeout),
          timeout.replace(/\s+/g, ' ').slice(0, 120));
    // Süre, YAVAŞ AMA ÇALIŞAN bir bağlantıda devreye girmeyecek kadar cömert
    // olmalı — yoksa telefonda oturumu açık kullanıcıyı sebepsiz kovar.
    check(`${page} waits long enough for a slow phone`,
          Number((timeout.match(/,\s*(\d{4,})\s*\)/) || [])[1]) >= 10000,
          (timeout.match(/,\s*(\d{4,})\s*\)/) || [])[1]);
  }

  // 🔴 Açık sayfalar örtüyü HİÇ kurmamalı: veriyi HTML'e gömülü alıyorlar ve
  // anında çiziliyorlar. Beklemek, Faz 29 adım 3'te Pinterest ziyaretçisi için
  // kazanılan ~1.2 sn'yi geri vermek olurdu.
  for (const page of ['recipe.html', 'discover.html']) {
    check(`${page} is NEVER covered while auth settles`,
          !fs.readFileSync(path.join(FRONTEND, page), 'utf8').includes('auth-pending'));
  }

  // ── 15. İşaret api.js'ten ÖNCE kurulmalı ───────────────
  // Sonra kurulursa guard onu göremez ve ziyaretçi yine kovulur — üstelik
  // sayfa hatasız göründüğü için sessizce.
  for (const page of ALLOWED) {
    const html = fs.readFileSync(path.join(FRONTEND, page), 'utf8');
    check(`${page} sets the flag before api.js loads`,
          html.indexOf('PUBLIC_PAGE') < html.indexOf('js/api.js'));
  }

  console.log(failures === 0
    ? `\nauth guard checks passed (${pass})`
    : `\n${failures} problem(s)`);
  process.exit(failures === 0 ? 0 : 1);
})();
