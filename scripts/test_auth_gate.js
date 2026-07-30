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

// Sabit sahte "simdi". Isaret zaman damgalari BUNDAN turetilmeli: gercek
// Date.now() ile karistirilirsa bayatlik hesabi anlamsiz (hatta negatif) cikar.
const NOW = 1700000000000;

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
function run(authReady, storageOpt, search, popupResult) {
  const classes = new Set(['auth-page', 'auth-checking']);
  const timers = [];
  const intervals = [];
  const authListeners = [];
  let cleared = 0;

  // Sahte saat: sayacin gecen sureyi Date.now() ile olcmesi yuzunden sart.
  let fakeNow = NOW;
  const fakeDate = function () {};
  fakeDate.now = () => fakeNow;

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

  // Elemanlar id basina SAKLANIYOR ve handler'lari yakalaniyor: Google butonuna
  // basma yolunu gercekten calistirabilmek icin sart (popup hatasi + gec gelen
  // giris senaryosu ancak boyle test edilebiliyor).
  const elements = {};
  const el = (id) => {
    if (!elements[id]) {
      // Gercek DOM'da bu buton `hidden` ile basliyor; sahte DOM da oyle
      // baslamali, yoksa "birkac saniye sonra beliriyor" testi anlamsiz olur.
      const cls = new Set(id === 'signin-cancel' ? ['hidden'] : []);
      elements[id] = {
        id,
        handlers: {},
        classes: cls,
        addEventListener(type, fn) { this.handlers[type] = fn; },
        classList: {
          add: (c) => cls.add(c),
          remove: (c) => cls.delete(c),
          contains: (c) => cls.has(c),
          toggle() {},
        },
        focus() {},
        textContent: '',
        value: '',
        disabled: false,
        dataset: {},
        style: {},
      };
    }
    return elements[id];
  };

  const ctx = {
    console,
    performance: { now: () => 0 },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout: () => { cleared++; },
    // Bekleme ekraninin sayaci setInterval kullaniyor. Zamani da sahteliyoruz,
    // yoksa "5 saniye sonra cikis baglantisi belirir" gercek zamanda beklenirdi.
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
    clearInterval: () => { intervals.length = 0; },
    Date: fakeDate,
    Logger: {
      get: () => ({ debug() {}, info() {}, warn() {}, error() {} }),
      duration() {},
      timed: (fn) => fn,
    },
    firebase: { auth: { GoogleAuthProvider: function () { this.setCustomParameters = () => {}; } } },
    auth: {
      // popupResult: undefined => cozulur | Error => reddeder
      signInWithPopup() {
        return popupResult instanceof Error
          ? Promise.reject(popupResult)
          : Promise.resolve({ user: { email: 'a@b.com' } });
      },
      signInWithEmailAndPassword() {},
      // Surekli dinleyici: gec gelen girisi yakalayan mekanizma. Testler
      // `emitAuth(user)` ile bunu tetikliyor.
      onAuthStateChanged(fn) { authListeners.push(fn); },
    },
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
    /** Firebase'in GEC gelen auth durumunu taklit eder. */
    emitAuth: (user) => authListeners.forEach((fn) => fn(user)),
    listenerCount: () => authListeners.length,
    /** Google butonuna basar (handler async, cagiran await etmeli). */
    clickGoogle: () => elements['google-btn'].handlers.click(),
    googleError: () => elements['google-error'].textContent,
    /** Saati n saniye ileri sarip sayaci tetikler. */
    advance: (secs) => {
      for (let i = 0; i < secs; i++) {
        fakeNow += 1000;
        intervals.slice().forEach((iv) => iv.fn());
      }
    },
    tickerRunning: () => intervals.length > 0,
    elapsedText: () => (elements['signin-elapsed'] || {}).textContent,
    cancelVisible: () => !!elements['signin-cancel'] && !elements['signin-cancel'].classes.has('hidden'),
    clickCancel: () => elements['signin-cancel'].handlers.click(),
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
  const fresh = { signin_pending: String(NOW) };
  r = run(new Promise(() => {}), fresh);      // auth henuz cozulmedi
  await new Promise((res) => setImmediate(res));
  check('pending sign-in -> waiting screen is shown', r.overlayShown());

  r = run(new Promise(() => {}));             // isaret yok
  await new Promise((res) => setImmediate(res));
  check('no pending sign-in -> waiting screen is NOT shown', !r.overlayShown());

  // Yarida birakilmis bir giris sonsuza dek bekleme ekrani gostermemeli.
  const stale = { signin_pending: String(NOW - 5 * 60 * 1000) };
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

  // ⚠️ BU BEKLENTI GERCEK CIHAZ KANITIYLA TERSINE CEVRILDI.
  // Eskiden burada "snapshot signed out ise hemen formu goster" bekleniyordu.
  // Telefondaki teshis kutusu bunu curuttu (marker 8s, overlay true, auth
  // "signed out"): PWA'da Google sonucu snapshot'tan SONRA geliyor, yani hemen
  // formu gostermek tam da duzeltilmeye calisilan "giris ekranina atti"
  // hatasini URETIYORDU. Artik bekleme ekrani grace suresi boyunca korunuyor
  // (asagidaki "late sign-in" testleri) ve isaret erken SILINMEMELI — silinirse
  // gec gelen giris yolunun tek kaniti yok olur.
  r = run(Promise.resolve(null), fresh);
  await new Promise((res) => setImmediate(res));
  check('pending + signed out -> marker is NOT cleared prematurely', r.markerLeft());

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

  // ── 6b. GEC GELEN GIRIS (gercek cihazda olculen hata) ──
  // Teshis kutusu sunu gosterdi: marker 8s, overlay true, auth "signed out".
  // Yani PWA'da Google sonucu `authStateReady()` fotografindan SONRA geliyor.
  // Tek seferlik snapshot bunu goremez; surekli dinleyici gormeli.
  r = run(Promise.resolve(null), fresh);
  await new Promise((res) => setImmediate(res));
  check('late sign-in: an ongoing auth listener is registered', r.listenerCount() === 1);
  check('late sign-in: waiting screen is NOT dismissed while sign-in is in flight',
        r.overlayShown());
  check('late sign-in: form stays hidden during the grace period', r.formHidden());
  r.emitAuth({ email: 'a@b.com' });                  // giris sonunda geliyor
  await new Promise((res) => setImmediate(res));
  check('late sign-in: redirects when the user finally arrives',
        r.redirectedTo() === 'search.html');
  check('late sign-in: marker is cleared on the way out', !r.markerLeft());

  // Gec giris GELMEZSE kullanici sonsuza dek beklememeli. Vazgecme karari artik
  // TEK bir yerde: bekleme ekraninin kendi sayaci. Onceki turda buna paralel bir
  // 10 sn'lik zamanlayici daha vardi ve hangisi once dolarsa davranisi o
  // belirliyordu — erken vazgecilmesinin sebebi buydu, o yuzden kaldirildi.
  r = run(Promise.resolve(null), fresh);
  await new Promise((res) => setImmediate(res));
  check('reload path: no competing short reveal timer is scheduled',
        !r.timers.some((t) => t.ms < 45000),
        JSON.stringify(r.timers.map((t) => t.ms)));
  r.advance(46);
  check('reload path: form is revealed once the waiting screen gives up', !r.formHidden());
  check('reload path: waiting screen is dismissed too', !r.overlayShown());

  // `null` YAYINI YONLENDIRMEMELI — Faz 6'daki giris<->search sonsuz dongusu
  // tam da gecici bir null'dan dogmustu.
  r = run(Promise.resolve(null));
  await new Promise((res) => setImmediate(res));
  r.emitAuth(null);
  check('a null auth event never redirects (phase 6 loop guard)',
        r.redirectedTo() === 'index.html');

  // ── 6c. POPUP HATA VERIYOR AMA GIRIS BASARILI (gercek cihazda olculen hata) ──
  // PWA'da hesap secildikten sonra signInWithPopup REDDEDIYOR, ama giris sunucu
  // tarafinda tamamlaniyor ve saniyeler icinde onAuthStateChanged ile geliyor.
  // Hemen forma donmek "once giris ekrani, sonra iceri" davranisini uretiyordu.
  // ── 6d. POPUP BASARIYLA COZULUYOR ama arada bosluk var ──
  // EKRAN KAYDIYLA bulundu: PWA'da popup uygulamanin USTUNE acilan bir Custom
  // Tab. Sayfa yeniden yuklenmiyor, signInWithPopup hata da firlatmiyor;
  // basariyla cozuluyor. Custom Tab kapandiktan sonra promise cozulene kadar
  // ~1.5 sn geciyor ve o boslukta ARKADAKI form goruluyor. Bekleme ekranini
  // TIKLAMA ANINDA gostermek bunun tek carasi.
  r = run(new Promise(() => {}));            // auth snapshot hic cozulmesin
  await new Promise((res) => setImmediate(res));
  const clickDone = r.clickGoogle();
  check('click: waiting screen appears immediately, before the popup',
        r.overlayShown());
  check('click: the marker is written', r.markerLeft());
  await clickDone;
  await new Promise((res) => setImmediate(res));
  check('popup resolves: navigates into the app', r.redirectedTo() === 'search.html');
  check('popup resolves: form is never shown in the gap', !r.googleError());

  const popupErr = Object.assign(new Error('popup closed'), { code: 'auth/popup-closed-by-user' });

  r = run(Promise.resolve(null), undefined, '', popupErr);
  await new Promise((res) => setImmediate(res));
  await r.clickGoogle();
  check('popup error: waiting screen is kept instead of the form', r.overlayShown());
  check('popup error: no error message is shown yet', r.googleError() === '');

  r.emitAuth({ email: 'a@b.com' });                 // giris gec geliyor
  await new Promise((res) => setImmediate(res));
  check('popup error + late sign-in: redirects into the app',
        r.redirectedTo() === 'search.html');
  check('popup error + late sign-in: never shows an error', r.googleError() === '');

  // Gercek basarisizlik: kimse gelmezse form ve hata mesaji donmeli.
  r = run(Promise.resolve(null), undefined, '', popupErr);
  await new Promise((res) => setImmediate(res));
  await r.clickGoogle();
  // Sabir: onceki tur 4 saniyede vazgeciyordu ve gercek cihazda giris yetismedi.
  check('popup error: a ticker is running', r.tickerRunning());
  r.advance(3);
  check('waiting 3s: still waiting, form not shown', r.overlayShown());
  check('waiting 3s: elapsed seconds are displayed', r.elapsedText() === '3s');
  check('waiting 3s: escape link is still hidden', !r.cancelVisible());

  r.advance(3);                                   // toplam 6 sn
  check('waiting 6s: escape link appears (user is never trapped)', r.cancelVisible());
  check('waiting 6s: still waiting', r.overlayShown());

  // 8. saniyede giris nihayet geliyor: iceri almali, hata GOSTERMEMELI.
  r.emitAuth({ email: 'a@b.com' });
  await new Promise((res) => setImmediate(res));
  check('slow sign-in: still redirects after several seconds',
        r.redirectedTo() === 'search.html');
  check('slow sign-in: no error is ever shown', r.googleError() === '');

  // Ust sinir: kimse gelmezse kendiliginden forma donmeli.
  r = run(Promise.resolve(null), undefined, '', popupErr);
  await new Promise((res) => setImmediate(res));
  await r.clickGoogle();
  r.advance(46);
  check('nothing arrives: waiting screen gives up eventually', !r.overlayShown());
  check('nothing arrives: marker is cleared', !r.markerLeft());
  // Kullanici popup'i KENDI kapattiysa mesaj gostermek yanlis olur; friendlyError
  // bu kod icin bilerek bos donuyor.
  check('cancelled popup: no error message (deliberate)', r.googleError() === '');

  // Kullanici bekleme ekranindan CIKABILMELI.
  r = run(Promise.resolve(null), undefined, '', popupErr);
  await new Promise((res) => setImmediate(res));
  await r.clickGoogle();
  r.advance(6);
  r.clickCancel();
  check('escape link: returns to the form on demand', !r.overlayShown());
  check('escape link: stops the ticker', !r.tickerRunning());

  // Gercek bir arizada mesaj GORUNMELI, yoksa kullanici ne oldugunu bilemez.
  const netErr = Object.assign(new Error('offline'), { code: 'auth/network-request-failed' });
  r = run(Promise.resolve(null), undefined, '', netErr);
  await new Promise((res) => setImmediate(res));
  await r.clickGoogle();
  r.advance(46);
  check('real failure: the error message is shown', r.googleError() !== '');

  // Hesap baglama: kullanicinin SIFRE YAZMASI gerekiyor, bekletmek anlamsiz.
  const linkErr = Object.assign(new Error('exists'), {
    code: 'auth/account-exists-with-different-credential',
    email: 'a@b.com',
  });
  r = run(Promise.resolve(null), undefined, '', linkErr);
  await new Promise((res) => setImmediate(res));
  await r.clickGoogle();
  check('account-linking error: form is shown immediately, no waiting',
        !r.overlayShown());
  check('account-linking error: marker is cleared', !r.markerLeft());

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
