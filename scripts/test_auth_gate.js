/**
 * Giriş sayfası kapısının davranış testi — sahte DOM.
 *
 *   node scripts/test_auth_gate.js
 *
 * NEDEN VAR: `index.html` giriş formunu artık GİZLİ başlatıyor ve `auth.js`
 * oturum durumu kesinleşince açıyor. Kazancı, giriş yapmış kullanıcının
 * yönlendirilmeden önce formu bir an görmemesi (PWA'da belirgindi).
 *
 * Riski ise net: açma yolu bozulursa form HİÇ görünmez ve kimse giriş
 * YAPAMAZ — üstelik sayfa hatasız görünür, yani sessiz. Ayrıca burası Faz 6'daki
 * giriş↔search sonsuz yönlendirme döngüsünün yaşandığı yer. Bu yüzden dört
 * yolun dördü de sabitleniyor: giriş var, giriş yok, hata, ve hiç çözülmeme.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'js', 'auth.js'), 'utf8');

let pass = 0;
let failures = 0;
const check = (name, cond, extra) => {
  if (cond) { console.log('  ok    ' + name); pass++; }
  else { console.error('  FAIL  ' + name + (extra ? ' :: ' + extra : '')); failures++; }
};

/**
 * auth.js'i taze bir sahte ortamda çalıştırır.
 * `authReady`'nin nasıl sonuçlanacağını çağıran belirliyor.
 */
function run(authReady, storageOpt, search) {
  const classes = new Set(['auth-page', 'auth-checking']);
  const timers = [];
  let cleared = 0;

  // storageOpt: undefined => bos localStorage
  //             { signin_pending: '<ms>' } => o degerle dolu
  //             'throws' => her erisimde SecurityError (Safari gizli mod)
  const store = new Map(Object.entries(storageOpt && storageOpt !== 'throws' ? storageOpt : {}));
  const localStorage = storageOpt === 'throws'
    ? {
        getItem() { throw new Error('SecurityError'); },
        setItem() { throw new Error('SecurityError'); },
        removeItem() { throw new Error('SecurityError'); },
      }
    : {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, v),
        removeItem: (k) => store.delete(k),
      };

  const el = () => ({
    addEventListener() {},
    classList: { toggle() {}, add() {}, remove() {} },
    focus() {},
    textContent: '',
    value: '',
    disabled: false,
    dataset: {},
    style: {},
  });

  const ctx = {
    console,
    performance: { now: () => 0 },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => { cleared++; },
    Logger: {
      get: () => ({ debug() {}, info() {}, warn() {}, error() {} }),
      duration() {},
      timed: (fn) => fn,
    },
    firebase: { auth: { GoogleAuthProvider: function () { this.setCustomParameters = () => {}; } } },
    auth: { signInWithPopup() {}, signInWithEmailAndPassword() {} },
    authReady,
    document: {
      body: {
        classList: {
          remove: (c) => classes.delete(c),
          add: (c) => classes.add(c),
          contains: (c) => classes.has(c),
        },
        appendChild() {},
      },
      getElementById: el,
      querySelectorAll: () => [],
      createElement: () => ({ style: {}, textContent: '' }),
    },
    localStorage,
    window: {
      location: { href: 'index.html', search: search || '' },
      matchMedia: () => ({ matches: false }),
      navigator: {},
    },
  };
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx, { filename: 'auth.js' });

  return {
    formHidden: () => classes.has('auth-checking'),
    overlayShown: () => classes.has('signing-in'),
    markerLeft: () => storageOpt !== 'throws' && store.has('signin_pending'),
    debugFlag: () => (storageOpt === 'throws' ? null : store.get('debug_auth')),
    redirectedTo: () => ctx.window.location.href,
    timers,
    clearedCount: () => cleared,
  };
}

(async () => {
  // ── 1. Giriş yapmış kullanıcı: yönlendirilir, form HİÇ görünmez ──
  let r = run(Promise.resolve({ email: 'a@b.com' }));
  await new Promise((res) => setImmediate(res));
  check('signed in -> redirected to search.html', r.redirectedTo() === 'search.html', r.redirectedTo());
  check('signed in -> form is never revealed (no flash)', r.formHidden());
  check('signed in -> defensive timer is cancelled', r.clearedCount() === 1);

  // ── 2. Giriş yapmamış kullanıcı: form açılır, yönlendirme YOK ──
  r = run(Promise.resolve(null));
  await new Promise((res) => setImmediate(res));
  check('signed out -> form is revealed', !r.formHidden());
  check('signed out -> stays on the login page', r.redirectedTo() === 'index.html');
  check('signed out -> defensive timer is cancelled', r.clearedCount() === 1);

  // ── 3. authReady REDDEDİLİRSE kullanıcı kilitlenmemeli ──
  r = run(Promise.reject(new Error('storage unavailable')));
  await new Promise((res) => setImmediate(res));
  check('auth state error -> form is still revealed (user not locked out)', !r.formHidden());
  check('auth state error -> no redirect', r.redirectedTo() === 'index.html');

  // ── 4. authReady HİÇ çözülmezse zaman aşımı formu açmalı ──
  // En sinsi senaryo: hata yok, sayfa normal görünür, ama form sonsuza dek
  // gizli kalır ve giriş imkansız hale gelir.
  r = run(new Promise(() => {}));            // asla çözülmez
  await new Promise((res) => setImmediate(res));
  check('never settles -> form is still hidden before the timeout', r.formHidden());
  check('never settles -> a 3s fallback timer was scheduled',
        r.timers.length === 1 && r.timers[0].ms === 3000,
        JSON.stringify(r.timers.map((t) => t.ms)));
  r.timers[0].fn();                          // zaman aşımını tetikle
  check('never settles -> timeout reveals the form', !r.formHidden());
  check('never settles -> timeout does NOT redirect', r.redirectedTo() === 'index.html');

  // ── 5. "Signing you in..." ekrani ──
  // PWA'da Google popup'indan donerken sayfa BASTAN yukleniyor. Isaret duruyorsa
  // giris sayfasi HIC gorunmemeli, tam ekran bekleme durumu cikmali.
  const fresh = { signin_pending: String(Date.now()) };
  r = run(new Promise(() => {}), fresh);      // auth henuz cozulmedi
  await new Promise((res) => setImmediate(res));
  check('pending sign-in -> waiting screen is shown', r.overlayShown());

  r = run(new Promise(() => {}));             // isaret yok
  await new Promise((res) => setImmediate(res));
  check('no pending sign-in -> waiting screen is NOT shown', !r.overlayShown());

  // Yarida birakilmis bir giris sonsuza dek bekleme ekrani gostermemeli.
  const stale = { signin_pending: String(Date.now() - 5 * 60 * 1000) };
  r = run(new Promise(() => {}), stale);
  await new Promise((res) => setImmediate(res));
  check('stale marker (>2min) -> waiting screen is NOT shown', !r.overlayShown());
  check('stale marker is cleaned up', !r.markerLeft());

  // Giris basarili: yonlendirme olurken bekleme ekrani KALMALI, yoksa son anda
  // giris sayfasi gorunur — duzeltmeye calistigimiz seyin ta kendisi.
  r = run(Promise.resolve({ email: 'a@b.com' }), fresh);
  await new Promise((res) => setImmediate(res));
  check('pending + signed in -> redirects', r.redirectedTo() === 'search.html');
  check('pending + signed in -> waiting screen stays until navigation', r.overlayShown());

  // Giris basarisiz (popup iptal): bekleme ekrani kalkmali, form gelmeli,
  // isaret temizlenmeli. Aksi halde kullanici kilitli bir ekranda kalir.
  r = run(Promise.resolve(null), fresh);
  await new Promise((res) => setImmediate(res));
  check('pending + signed out -> waiting screen is dismissed', !r.overlayShown());
  check('pending + signed out -> form is revealed', !r.formHidden());
  check('pending + signed out -> marker is cleared', !r.markerLeft());

  // ── 6. localStorage erisilemezse (Safari gizli mod) cokmemeli ──
  // Bu dosya giris sayfasinin TAMAMINI yonetiyor; burada bir istisna
  // hic kimsenin giris yapamamasi demek (Faz 13b dersi).
  let crashed = false;
  try {
    r = run(Promise.resolve(null), 'throws');
    await new Promise((res) => setImmediate(res));
  } catch (e) {
    crashed = true;
  }
  check('localStorage unavailable -> auth.js still loads', !crashed);
  check('localStorage unavailable -> no waiting screen', !crashed && !r.overlayShown());
  check('localStorage unavailable -> form still works', !crashed && !r.formHidden());

  // ── 7. ?debug=1 teshis kutusu ──
  // Normal kullanici icin GORUNMEZ olmali; yalnizca URL'de debug=1 varsa cikmali.
  // Ayrica hicbir kosulda auth.js'i cokertmemeli (giris sayfasinin tamamini yonetiyor).
  crashed = false;
  try {
    r = run(Promise.resolve(null), undefined, '?debug=1');
    await new Promise((res) => setImmediate(res));
  } catch (e) { crashed = true; }
  check('debug=1 -> does not break the page', !crashed);
  check('debug=1 -> form is still revealed', !crashed && !r.formHidden());
  // Kalici olmali: kurulu PWA'nin adres cubugu yok, yani icine ?debug=1 yazilamiyor.
  // Chrome'da bir kez acmak PWA'da da etkinlestirmeli (ayni origin, ayni depo).
  check('debug=1 -> persists a flag for the installed PWA', r.debugFlag() === '1');

  // Bayrak varken parametre OLMADAN da acilmali (PWA'nin gordugu durum).
  crashed = false;
  try {
    r = run(Promise.resolve(null), { debug_auth: '1' }, '');
    await new Promise((res) => setImmediate(res));
  } catch (e) { crashed = true; }
  check('stored debug flag -> diagnostics work without the URL param', !crashed && !r.formHidden());

  // ?debug=0 kapatabilmeli, yoksa kutu kalici olarak ekranda kalir.
  r = run(Promise.resolve(null), { debug_auth: '1' }, '?debug=0');
  await new Promise((res) => setImmediate(res));
  check('debug=0 -> clears the stored flag', !r.debugFlag());

  crashed = false;
  try {
    r = run(Promise.resolve(null), undefined, '');
    await new Promise((res) => setImmediate(res));
  } catch (e) { crashed = true; }
  check('no debug param -> page behaves normally', !crashed && !r.formHidden());

  console.log(failures === 0
    ? `\nauth gate checks passed (${pass})`
    : `\n${failures} problem(s)`);
  process.exit(failures === 0 ? 0 : 1);
})();
