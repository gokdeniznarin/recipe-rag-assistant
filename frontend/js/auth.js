/**
 * Giriş sayfası (index.html) mantığı — kimlik doğrulama Firebase Auth ile.
 * Bu dosya, Firebase compat SDK script'leri ve firebase.js'ten SONRA yüklenir.
 */

const authLog = Logger.get('auth');

// ── Oturum durumu kesinleşene kadar formu gizle ──────────
// Giriş yapmışsa search.html'e yönlendir; yapmamışsa formu göster.
//
// Kart `auth-checking` sınıfıyla GİZLİ başlıyor (index.html + style.css).
// Öncesinde form anında çiziliyor, `authReady` ise oturum kalıcı depodan geri
// yüklendikten sonra çözülüyordu (canlıda ~975 ms) — yani giriş yapmış kullanıcı
// yönlendirilmeden önce formu bir an görüyordu. PWA'da Google popup'ından
// dönerken bu bekleme baştan ödendiği için belirgin bir "giriş ekranına attı
// sonra girdi" etkisi yaratıyordu.
function revealAuthForm() {
  document.body.classList.remove('auth-checking');
  hideWaitingScreen();
  clearSignInPending();
}

// ── "Signing you in…" ekranı ─────────────────────────────
// PWA'da Google popup'ından dönerken pencere yeniden kuruluyor ve `index.html`
// BAŞTAN yükleniyor. Kartı gizlemek yetmiyordu: hero ve tanıtım içeriği görünür
// kaldığı için ekran hâlâ "giriş sayfası" gibi duruyordu ve kullanıcı geri
// atıldığını sanıyordu (gerçek cihazda iki kez doğrulandı).
//
// Çözüm: giriş BAŞLATILDIĞINDA bir işaret bırakmak. Sayfa yeniden yüklendiğinde
// işaret duruyorsa giriş sayfası yerine tam ekran bir bekleme durumu gösteriliyor.
//
// NEDEN WEB'İ ETKİLEMİYOR: web'de popup aynı sayfa bağlamında çözülüyor, sayfa
// hiç yeniden yüklenmiyor — işaret konup siliniyor ama okuyan olmuyor. Ekran
// yalnızca "giriş başlatıldı VE sayfa yeniden yüklendi" durumunda değişiyor.
// `display-mode` ile yapay olarak PWA'ya kısıtlanmadı: tetikleyici zaten kesin.
const SIGNIN_PENDING_KEY = 'signin_pending';
const SIGNIN_PENDING_MAX_AGE = 2 * 60 * 1000;   // bayat işaret ekranı kilitlemesin

// Depolama erişimi try/catch'li: Safari gizli modda localStorage'a DOKUNMAK bile
// SecurityError fırlatıyor ve bu dosya giriş sayfasının tamamını yönetiyor —
// burada bir istisna kimsenin giriş yapamaması demek (Faz 13b dersi).
function markSignInPending() {
  try { localStorage.setItem(SIGNIN_PENDING_KEY, String(Date.now())); } catch (e) { /* yoksay */ }
}

function clearSignInPending() {
  try { localStorage.removeItem(SIGNIN_PENDING_KEY); } catch (e) { /* yoksay */ }
}

function signInIsPending() {
  try {
    const started = Number(localStorage.getItem(SIGNIN_PENDING_KEY));
    if (!started) return false;
    // Yarıda bırakılmış bir giriş sonsuza dek bekleme ekranı göstermemeli.
    if (Date.now() - started > SIGNIN_PENDING_MAX_AGE) {
      clearSignInPending();
      return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

// ── Bekleme ekranının ömrü ───────────────────────────────
// Önceki tur 4 saniye sonra vazgeçiyordu ve gerçek cihazda giriş o süreye
// yetişmedi: ekran kalkıp form göründü, giriş ise saniyeler sonra geldi.
// SÜREYİ TAHMİN ETMEK YERİNE iki şey yapıyoruz:
//   1. sabırlı olmak (aşağıdaki üst sınır cömert),
//   2. kullanıcıyı HAPSETMEMEK — birkaç saniye sonra çıkış bağlantısı beliriyor.
// Ayrıca geçen süre ekranda YAZIYOR: "uzun sürdü" ifadesini sayıya çeviren tek
// şey bu, ve bir sonraki kararı (popup mu, redirect mi) o sayı belirleyecek.
const WAIT_ESCAPE_SEC = 5;      // bu saniyeden sonra "vazgeç" bağlantısı görünür
const WAIT_MAX_SEC = 45;        // bu saniyeden sonra kendiliğinden forma döner

let waitTicker = null;

function showWaitingScreen(onGiveUp) {
  document.body.classList.add('signing-in');

  const elapsedEl = document.getElementById('signin-elapsed');
  const cancelEl = document.getElementById('signin-cancel');
  const started = Date.now();

  if (waitTicker) clearInterval(waitTicker);
  waitTicker = setInterval(() => {
    if (leavingForApp) { hideWaitingScreen(); return; }
    const secs = Math.round((Date.now() - started) / 1000);
    if (elapsedEl) elapsedEl.textContent = secs + 's';
    if (cancelEl && secs >= WAIT_ESCAPE_SEC) cancelEl.classList.remove('hidden');
    if (secs >= WAIT_MAX_SEC) {
      hideWaitingScreen();
      if (onGiveUp) onGiveUp();
    }
  }, 1000);

  if (cancelEl && !cancelEl.dataset.bound) {
    cancelEl.dataset.bound = '1';
    cancelEl.addEventListener('click', () => {
      hideWaitingScreen();
      if (onGiveUp) onGiveUp();
    });
  }
}

function hideWaitingScreen() {
  if (waitTicker) { clearInterval(waitTicker); waitTicker = null; }
  document.body.classList.remove('signing-in');
  const cancelEl = document.getElementById('signin-cancel');
  if (cancelEl) cancelEl.classList.add('hidden');
}

// Sayfa açılır açılmaz karar veriliyor ki giriş sayfası bir kare bile görünmesin.
if (signInIsPending()) {
  authLog.info('Returning from an in-progress sign-in; showing the waiting screen');
  showWaitingScreen(() => revealAuthForm());
}

// ── Teşhis kutusu — YALNIZCA ?debug=1 ────────────────────
// Telefondaki konsolu okumak bilgisayar + USB kablosu istiyor. Bu blok aynı
// bilgiyi doğrudan EKRANDA gösteriyor. URL'de debug=1 yoksa hiçbir şey yapmıyor,
// yani normal kullanıcı için görünmez ve davranışı değiştirmiyor.
//
// BUILD değeri her dağıtımda elle artırılıyor: "telefondaki kod güncel mi?"
// sorusunun tek kesin cevabı bu — kurulu PWA sayfayı bellekte tuttuğu için
// güncellemenin gerçekten indiğini başka türlü doğrulayamıyoruz.
const BUILD = '26c-2';

// `?debug=1` KALICI bir işaret bırakıyor. Sebep pratik: kurulu PWA'nın adres
// çubuğu yok, yani uygulamanın içinde bir sorgu parametresi yazmak MÜMKÜN DEĞİL.
// Chrome ile kurulu PWA aynı origin'in deposunu paylaştığı için, tarayıcıda bir
// kez açmak teşhisi PWA'da da açıyor. `?debug=0` kapatıyor.
function debugEnabled() {
  try {
    const q = window.location.search;
    if (q.indexOf('debug=1') !== -1) { localStorage.setItem('debug_auth', '1'); return true; }
    if (q.indexOf('debug=0') !== -1) { localStorage.removeItem('debug_auth'); return false; }
    return localStorage.getItem('debug_auth') === '1';
  } catch (e) {
    // Depolama kapalıysa yalnızca URL'ye bak; teşhis aracı sayfayı düşürmemeli.
    return window.location.search.indexOf('debug=1') !== -1;
  }
}

if (debugEnabled()) {
  const box = document.createElement('pre');
  box.style.cssText =
    'position:fixed;left:0;right:0;bottom:0;z-index:200;margin:0;padding:.6rem;' +
    'background:#2D3B2D;color:#F5F0E8;font:12px/1.5 monospace;white-space:pre-wrap;';
  const standalone =
    (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
    window.navigator.standalone === true;

  let marker = 'n/a';
  try {
    const raw = localStorage.getItem(SIGNIN_PENDING_KEY);
    marker = raw ? Math.round((Date.now() - Number(raw)) / 1000) + 's ago' : 'none';
  } catch (e) {
    marker = 'localStorage blocked';
  }

  const lines = [
    'BUILD      ' + BUILD,
    'standalone ' + standalone,
    'marker     ' + marker,
    'overlay    ' + document.body.classList.contains('signing-in'),
    'auth       resolving...',
  ];
  box.textContent = lines.join('\n');
  document.body.appendChild(box);

  authReady
    .then((u) => { lines[4] = 'auth       ' + (u ? 'signed in: ' + u.email : 'signed out'); })
    .catch((e) => { lines[4] = 'auth       ERROR ' + e.message; })
    .then(() => { box.textContent = lines.join('\n'); });
}

// Girişten sonra bir kez yönlendir. İki ayrı yol buraya varabiliyor (aşağıdaki
// tek seferlik `authReady` ve sürekli dinleyici), ikisi birden tetiklenmesin.
let leavingForApp = false;
function goToApp() {
  if (leavingForApp) return;
  leavingForApp = true;
  clearSignInPending();
  window.location.href = 'search.html';
}

// ⚠️ SÜREKLİ DİNLEYİCİ — bu sayfanın en kritik parçası.
//
// `authReady` TEK SEFERLİK bir fotoğraf: `authStateReady()` bir kez çözülüyor.
// PWA'da Google popup'ı ayrı bir bağlamda açıldığı için giriş sonucu uygulamaya
// GEÇ ulaşıyor ve o fotoğraf çoktan "signed out" demiş oluyor. Giriş sonradan
// gerçekten tamamlanıyor, ama dinleyen olmadığı için yönlendirme hiç olmuyordu:
// kullanıcı aslında GİRMİŞ hâlde giriş ekranında oturuyordu. Gerçek cihazdaki
// teşhis kutusu bunu gösterdi (marker 8s, overlay true, auth signed out).
//
// Yalnızca KULLANICI VARSA yönlendiriyor, `null`'da hiçbir şey yapmıyor —
// Faz 6'daki giriş↔search sonsuz döngüsü tam da geçici `null`'dan doğmuştu.
auth.onAuthStateChanged((user) => {
  if (user) {
    authLog.info('Auth state arrived after the initial snapshot; entering the app');
    goToApp();
  }
});

// Savunmacı zaman aşımı: `authStateReady()` ağa çıkmadığı için normalde hızlı
// çözülür, ama beklenmedik bir sebeple çözülmezse kart sonsuza dek gizli kalır
// ve kullanıcı GİRİŞ YAPAMAZ. Yardımcı bir iyileştirme uygulamayı kilitlememeli
// (Faz 13b'de logger.js'in localStorage yüzünden uygulamayı düşürmesinin dersi).
//
// Giriş SÜRÜYORSA bu zamanlayıcı hiç kurulmuyor: o durumda bekleme ekranının
// kendi ömrü geçerli (sayaç + çıkış bağlantısı + üst sınır). İki ayrı zaman
// aşımı olsaydı hangisinin önce dolduğu davranışı belirlerdi — önceki turda
// erken vazgeçilmesinin sebebi tam olarak buydu.
const authRevealTimer = signInIsPending()
  ? null
  : setTimeout(() => {
      if (leavingForApp) return;
      authLog.warn('Auth state did not settle in 3s; showing the form anyway');
      revealAuthForm();
    }, 3000);

authReady
  .then((user) => {
    if (user) {
      clearTimeout(authRevealTimer);
      goToApp();
      return;
    }
    // Çıkış yapılmış GÖRÜNÜYOR. Ama az önce bir giriş başlatıldıysa bu fotoğraf
    // erken çekilmiş olabilir — dinleyiciye şans tanıyıp bekleme ekranını
    // koruyoruz. Vazgeçme kararı bekleme ekranının kendisine ait.
    if (signInIsPending()) {
      authLog.info('Signed out at snapshot time, but a sign-in is in flight; waiting');
      return;
    }
    clearTimeout(authRevealTimer);
    revealAuthForm();
  })
  .catch((err) => {
    // Oturum durumu okunamadıysa kullanıcıyı kilitlemek yerine formu göster.
    clearTimeout(authRevealTimer);
    authLog.error('Could not resolve auth state: ' + err.message);
    revealAuthForm();
  });

// Google ile girilmeye çalışılıp "bu email şifreyle kayıtlı" hatası alınırsa,
// Google kimliği burada bekletilir; kullanıcı şifresiyle giriş yapınca hesaba bağlanır.
let pendingGoogleCredential = null;

// ── Firebase hata kodlarını okunur mesajlara çevir ──────
function friendlyError(code) {
  switch (code) {
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
    case 'auth/user-not-found':
      // Google ile kayıt olan kullanıcının şifresi yoktur — ipucu ver.
      return 'Invalid email or password. If you signed up with Google, use the Google button.';
    case 'auth/email-already-in-use':
      return 'An account with this email already exists. If you signed up with Google, use the Google button.';
    case 'auth/weak-password':
      return 'Password should be at least 6 characters.';
    case 'auth/invalid-email':
      return 'Please enter a valid email address.';
    case 'auth/popup-closed-by-user':
    case 'auth/cancelled-popup-request':
      return '';  // kullanıcı iptal etti — mesaj gösterme
    case 'auth/network-request-failed':
      return 'Network error. Please check your connection.';
    default:
      return 'Something went wrong. Please try again.';
  }
}

// ── Tab geçişi ───────────────────────────────────────────
function showTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab)
  );
  document.getElementById('login-form').classList.toggle('hidden', tab !== 'login');
  document.getElementById('register-form').classList.toggle('hidden', tab !== 'register');
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    showTab(btn.dataset.tab);
    // Hata mesajlarını temizle
    document.getElementById('login-error').textContent = '';
    document.getElementById('register-error').textContent = '';
  });
});

// ── Giriş ───────────────────────────────────────────────
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const email    = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  const errorEl  = document.getElementById('login-error');
  const btn      = e.target.querySelector('button[type="submit"]');

  errorEl.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Signing in…';

  // Giriş süresi YALNIZCA burada ölçülebilir: Faz 6'dan beri giriş tarayıcı ile
  // Firebase arasında geçiyor, bizim sunucumuza hiç uğramıyor. Backend logunda
  // bu işlemin izi yoktur.
  const start = performance.now();

  try {
    const result = await auth.signInWithEmailAndPassword(email, password);

    // Google girişi bekliyorsa, kimliği kanıtlanmış bu hesaba bağla —
    // bundan sonra kullanıcı hem şifreyle hem Google ile girebilir.
    if (pendingGoogleCredential) {
      await result.user.linkWithCredential(pendingGoogleCredential);
      pendingGoogleCredential = null;
      authLog.info('Google credential linked to password account');
    }

    Logger.duration('auth', 'sign in (password)', performance.now() - start, 3000);
    window.location.href = 'search.html';
  } catch (err) {
    authLog.error(
      `sign in (password) failed after ${Logger.fmt(performance.now() - start)}: ${err.code}`
    );
    errorEl.textContent = friendlyError(err.code);
    btn.disabled = false;
    btn.textContent = 'Sign in';
  }
});

// ── Kayıt ────────────────────────────────────────────────
document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const email    = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const errorEl  = document.getElementById('register-error');
  const btn      = e.target.querySelector('button[type="submit"]');

  errorEl.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Creating account…';

  const start = performance.now();

  try {
    // Firebase hesabı oluşturur ve kullanıcıyı otomatik giriş yaptırır.
    const result = await auth.createUserWithEmailAndPassword(email, password);
    Logger.duration('auth', 'create account', performance.now() - start, 3000);

    // Doğrulama maili gönder. Kritik: email doğrulanmadan aynı adresle Google'a
    // girilirse, Firebase güvenlik gereği doğrulanmamış şifreyi siler. Doğrulanmış
    // email'de ise Google'ı şifrenin YANINA ekler — ikisi birlikte çalışır.
    try {
      await result.user.sendEmailVerification();
    } catch (e) {
      authLog.warn(`Verification email could not be sent: ${e.code || e.message}`);
    }

    window.location.href = 'search.html';
  } catch (err) {
    errorEl.textContent = friendlyError(err.code);
    btn.disabled = false;
    btn.textContent = 'Create account';
  }
});

// ── Şifre sıfırlama ──────────────────────────────────────
// Firebase maili ve şifre değiştirme sayfasını kendisi sunuyor; bizim tarafta
// tek iş e-postayı vermek.
document.getElementById('forgot-btn').addEventListener('click', async () => {
  const email   = document.getElementById('login-email').value.trim();
  const errorEl = document.getElementById('login-error');
  const infoEl  = document.getElementById('login-info');
  const btn     = document.getElementById('forgot-btn');

  errorEl.textContent = '';
  infoEl.classList.add('hidden');

  if (!email) {
    errorEl.textContent = 'Enter your email above first, then click again.';
    document.getElementById('login-email').focus();
    return;
  }

  btn.disabled = true;
  try {
    await auth.sendPasswordResetEmail(email);
    // Hesabın var olup olmadığını AÇIKLAMIYORUZ: "bu email kayıtlı değil" demek,
    // saldırgana hangi adreslerin sistemde olduğunu tek tek sorgulatır.
    // Firebase de aynı sebeple varsayılan olarak user-not-found döndürmüyor.
    infoEl.textContent =
      'If an account exists for ' + email + ', a reset link is on its way. ' +
      'Check your spam folder too.';
    infoEl.classList.remove('hidden');
  } catch (err) {
    errorEl.textContent =
      err.code === 'auth/invalid-email'
        ? 'Please enter a valid email address.'
        : 'Could not send the reset email. Please try again.';
  } finally {
    btn.disabled = false;
  }
});

// ── Google Sign-In ───────────────────────────────────────
const googleProvider = new firebase.auth.GoogleAuthProvider();
// Her girişte hesap seçme ekranını zorla — yoksa tek oturumu otomatik seçer
googleProvider.setCustomParameters({ prompt: 'select_account' });

document.getElementById('google-btn').addEventListener('click', async () => {
  const errorEl = document.getElementById('google-error');
  errorEl.textContent = '';

  // Popup açık kaldığı sürece kullanıcı hesap seçiyor; bu yüzden ölçülen süre
  // "sistemin yavaşlığı" değil, kullanıcının düşünme süresini de içeriyor.
  // Eşik bu yüzden yüksek (10 sn) — yoksa her normal giriş sarı yanardı.
  const start = performance.now();

  // Popup AÇILMADAN önce işaretle. PWA'da pencere popup sırasında yeniden
  // kurulabiliyor ve bu fonksiyon hiç devam etmiyor — o durumda işaret, sayfa
  // baştan yüklendiğinde giriş sayfası yerine bekleme ekranını gösteriyor.
  markSignInPending();

  // Bekleme ekranını HEMEN göster — popup açılmadan önce.
  //
  // Ekran kaydı bunun neden şart olduğunu gösterdi: PWA'da popup, uygulamanın
  // ÜSTÜNE açılan bir Custom Tab. Sayfa yeniden yüklenmiyor, `signInWithPopup`
  // da hata fırlatmıyor — BAŞARIYLA çözülüyor. Yani daha önce ekranı gösterdiğim
  // iki yol (yeniden yükleme ve hata) burada hiç çalışmıyordu.
  //
  // Custom Tab kapandıktan sonra promise çözülene kadar ~1.5 sn geçiyor ve o
  // boşlukta ARKADAKİ giriş formu görünüyor. Kullanıcının "önce giriş ekranına
  // atıyor sonra giriyor" dediği şey tam olarak bu boşluk.
  showWaitingScreen(() => {
    if (leavingForApp) return;
    clearSignInPending();
    errorEl.textContent = friendlyError('auth/popup-closed-by-user');
  });

  try {
    await auth.signInWithPopup(googleProvider);
    Logger.duration('auth', 'sign in (Google popup)', performance.now() - start, 10000);
    // Buraya ulaştıysak pencere hayatta kaldı (tipik olarak web): işaretin
    // görevi bitti, yoksa index.html'e sonraki dönüşte bekleme ekranı çıkardı.
    clearSignInPending();
    window.location.href = 'search.html';
  } catch (err) {
    // İşaret BURADA HER ZAMAN SİLİNMEZ. `popup-closed-by-user` /
    // `cancelled-popup-request` BELİRSİZ hatalar: PWA'da pencere bağlantısı
    // koptuğu için popup "iptal edildi" sayılabiliyor, oysa giriş sunucu
    // tarafında BAŞARILI olmuş olabiliyor. Bu durumda işareti silmek, sayfa
    // hemen ardından yeniden yüklendiğinde bekleme ekranını gösterecek tek
    // kanıtı yok etmek demek — düzeltmeyi kendi kendine iptal ediyordu.
    //
    // İşareti bırakmak zararsız: bu sayfada kaldığımız sürece kimse okumuyor,
    // ve `authReady` kullanıcısız çözülürse `revealAuthForm()` zaten siliyor.
    // Ayrıca 2 dakikada kendiliğinden bayatlıyor.
    // Bu email şifreyle kayıtlı: Firebase güvenlik gereği otomatik bağlamaz,
    // önce kullanıcının mevcut şifresiyle kimliğini kanıtlaması gerekir.
    // BEKLEMEDEN forma dönülen TEK durum bu: kullanıcının bir şey yazması
    // gerekiyor, bekletmenin hiçbir faydası yok.
    if (err.code === 'auth/account-exists-with-different-credential') {
      clearSignInPending();
      document.body.classList.remove('signing-in');
      pendingGoogleCredential =
        err.credential ||
        (firebase.auth.GoogleAuthProvider.credentialFromError &&
          firebase.auth.GoogleAuthProvider.credentialFromError(err));

      const email = err.email || (err.customData && err.customData.email) || '';

      showTab('login');
      document.getElementById('login-email').value = email;
      document.getElementById('login-error').textContent =
        'This email is already registered with a password. Sign in with your password to link your Google account.';
      document.getElementById('login-password').focus();
      return;
    }

    // ⚠️ DİĞER TÜM HATALAR "BELİRSİZ" SAYILIYOR — gerçek cihazda ölçüldü.
    //
    // PWA'da popup, hesap seçildikten sonra HATA olarak dönüyor (pencere
    // bağlantısı koptuğu için), ama giriş sunucu tarafında BAŞARILI oluyor ve
    // saniyeler içinde `onAuthStateChanged` ile geliyor. Burada hemen formu
    // göstermek, düzeltilmeye çalışılan davranışın ta kendisini üretiyordu:
    // "önce giriş ekranı, sonra içeri".
    //
    // Bu yüzden bekleme ekranı KORUNUYOR ve dinleyiciye şans tanınıyor. Gerçek
    // bir başarısızlıksa (kullanıcı iptal etti, ağ koptu) süre dolunca form ve
    // hata mesajı geliyor. Süre kısa tutuldu: giriş gerçekten olduysa durum
    // yerel depodan neredeyse anında geliyor, uzun beklemeye gerek yok.
    // Sabit bir süre sonra vazgeçMİYORUZ (önceki tur 4 sn'de vazgeçiyordu ve
    // giriş yetişmedi). Bekleme ekranı sabırla duruyor, geçen süreyi gösteriyor
    // ve birkaç saniye sonra kullanıcıya çıkış bağlantısı sunuyor.
    showWaitingScreen(() => {
      if (leavingForApp) return;        // dinleyici bizi çoktan içeri aldı
      authLog.warn('Google sign-in did not complete: ' + err.code);
      clearSignInPending();
      errorEl.textContent = friendlyError(err.code);
    });
  }
});
