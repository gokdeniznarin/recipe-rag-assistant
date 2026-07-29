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
  document.body.classList.remove('signing-in');
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

// Sayfa açılır açılmaz karar veriliyor ki giriş sayfası bir kare bile görünmesin.
if (signInIsPending()) {
  document.body.classList.add('signing-in');
  authLog.info('Returning from an in-progress sign-in; showing the waiting screen');
}

// Savunmacı zaman aşımı: `authStateReady()` ağa çıkmadığı için normalde hızlı
// çözülür, ama beklenmedik bir sebeple çözülmezse kart sonsuza dek gizli kalır
// ve kullanıcı GİRİŞ YAPAMAZ. Yardımcı bir iyileştirme uygulamayı kilitlememeli
// (Faz 13b'de logger.js'in localStorage yüzünden uygulamayı düşürmesinin dersi).
const authRevealTimer = setTimeout(() => {
  authLog.warn('Auth state did not settle in 3s; showing the form anyway');
  revealAuthForm();
}, 3000);

authReady
  .then((user) => {
    clearTimeout(authRevealTimer);
    if (user) {
      window.location.href = 'search.html';
      return;               // yönlendiriliyoruz: formu göstermeye gerek yok
    }
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

  try {
    await auth.signInWithPopup(googleProvider);
    Logger.duration('auth', 'sign in (Google popup)', performance.now() - start, 10000);
    // Buraya ulaştıysak pencere hayatta kaldı (tipik olarak web): işaretin
    // görevi bitti, yoksa index.html'e sonraki dönüşte bekleme ekranı çıkardı.
    clearSignInPending();
    window.location.href = 'search.html';
  } catch (err) {
    // Giriş tamamlanmadı: işaret kalırsa kullanıcı bir daha bu sayfaya
    // geldiğinde hiçbir sebep yokken bekleme ekranıyla karşılaşır.
    clearSignInPending();
    document.body.classList.remove('signing-in');
    // Bu email şifreyle kayıtlı: Firebase güvenlik gereği otomatik bağlamaz,
    // önce kullanıcının mevcut şifresiyle kimliğini kanıtlaması gerekir.
    if (err.code === 'auth/account-exists-with-different-credential') {
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

    errorEl.textContent = friendlyError(err.code);
  }
});
