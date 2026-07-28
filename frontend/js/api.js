/**
 * Ortak API katmanı. Her korumalı sayfa bu dosyayı firebase.js'ten sonra yükler.
 * - Kimlik doğrulama Firebase Auth ile yönetilir
 * - Oturum yoksa giriş sayfasına atar
 * - Fetch wrapper'ı: her istekte Firebase ID token'ını Authorization header'a ekler
 * - 401 dönerse otomatik çıkış yapar
 */

// API adresi ortama göre config.js'te belirlenir (bu dosyadan önce yüklenir):
// yerelde/LAN'da localhost:8080, canlıda Render. Bkz. frontend/js/config.js.
const API = window.API_BASE;

// logger.js bu dosyadan önce yüklenir (bkz. HTML'lerdeki script sırası).
const apiLog = Logger.get('api');

// "Yavaş" eşiği uç noktaya göre değişiyor — backend'de de öyle. Bu iki uç
// Gemini'yi bekliyor, saniyeler sürmesi normal; tek bir genel eşik (1 sn)
// kullanılırsa normal çalışan her istek sarı yanar ve uyarı anlamını yitirir.
// Ayrıca aynı istek backend'de yeşil, frontend'de sarı görünürdü.
//
// from-image backend'inkinden (5 sn) daha yüksek: fotoğrafın base64 olarak
// yüklenmesi buraya dahil, backend ölçümü ise istek geldikten sonra başlıyor.
const SLOW_THRESHOLDS = [
  [/\/api\/recipes\/commentary/, 5000],
  [/\/api\/recipes\/from-image/, 8000],
  // Besin değeri: vision + öğe başına FatSecret araması. Fotoğrafın base64
  // yüklemesi FRONTEND ölçümüne dahil ama backend'inkine değil (o istek
  // geldikten sonra başlıyor), o yüzden eşik backend'in 5 sn'sinden yüksek.
  // Eklenmezse varsayılan 1 sn'ye düşüyordu ve normal çalışan her istek sarı
  // yanıyordu — backend YEŞİL derken tarayıcı SARI diyor, yani uyarı anlamını
  // yitiriyor. Faz 13b'de diğer uçlar için tam bu düzeltilmişti.
  [/\/api\/nutrition\/from-image/, 8000],
];

function thresholdFor(path) {
  const match = SLOW_THRESHOLDS.find(([pattern]) => pattern.test(path));
  return match ? match[1] : undefined;   // undefined -> Logger'ın varsayılanı
}

// ── Token ────────────────────────────────────────────────
// Firebase ID token'ı gerektiğinde otomatik yenilenir.
async function getToken() {
  // Firebase oturumu geri yükleyene kadar bekle — yoksa sayfa yüklenirken
  // currentUser henüz null olabilir ve istek yanlışlıkla 401 alır.
  //
  // İki bekleme AYRI ölçülüyor, çünkü sebepleri farklı: buradaki bekleme
  // sayfa ilk açılırken oturumun geri yüklenmesi (normal, bir kez olur),
  // aşağıdaki ise token'ın gerçekten yenilenmesi. İkisi tek sayı olarak
  // ölçülseydi her sayfa açılışında sahte bir "yavaş" uyarısı çıkardı.
  const t0 = performance.now();
  await authReady;
  const waited = performance.now() - t0;
  // Kayda değer olduğunda INFO: bu bekleme her sayfanın İLK isteğinde ~450 ms
  // olabiliyor (Firebase oturumu geri yüklüyor) ve isteğin toplam süresine
  // dahil. Loglanmazsa konsolda "451 ms sürdü" yazan bir istek görünüyor ama
  // backend "3 ms" diyor — aradaki fark açıklamasız kalıyor.
  // MPA olduğumuz için bu bedel HER sayfa geçişinde yeniden ödeniyor.
  if (waited > 100) {
    apiLog.info(`waited ${Logger.fmt(waited)} for Firebase auth state (first request on this page)`);
  } else if (waited > 5) {
    apiLog.debug(`waited ${Logger.fmt(waited)} for auth state to settle`);
  }

  const user = auth.currentUser;
  if (!user) return null;

  const t1 = performance.now();
  const token = await user.getIdToken();
  const refreshed = performance.now() - t1;
  // Normalde SDK önbellekteki token'ı anında verir. Uzun sürdüyse token'ın
  // süresi dolmuş ve Firebase'e gidilmiş demektir — bilmek isteriz.
  if (refreshed > 100) apiLog.info(`getIdToken took ${Logger.fmt(refreshed)} (token refreshed)`);

  return token;
}

/**
 * Oturuma bağlı istemci verisini temizler (Faz 20).
 *
 * sessionStorage sekmeye özel ama KULLANICIYA ÖZEL DEĞİL: aynı sekmede hesap
 * değiştirildiğinde önceki kullanıcının arama sonuçları ekranda kalıyordu.
 * Ortak bir bilgisayarda bu bir gizlilik sızıntısı — çıkışta siliniyor.
 * (İkinci savunma hattı search.js'te: kayıt sahibinin e-postası da saklanıyor
 * ve eşleşmezse geri yüklenmiyor — 401 ile düşen oturum gibi çıkışın
 * çalışmadığı yolları da kapsasın diye.)
 */
function clearSessionScopedData() {
  try {
    sessionStorage.removeItem('search_state_v1');
  } catch {
    // Depolama erişilemiyorsa zaten yazılmamıştır.
  }
}

function logout() {
  const start = performance.now();
  clearSessionScopedData();
  auth.signOut().then(() => {
    // Çıkış da giriş gibi tamamen istemci tarafında: Firebase yerel oturumu
    // siliyor, sunucumuza istek gitmiyor. Genelde milisaniyeler sürer.
    Logger.duration('auth', 'sign out', performance.now() - start);
    window.location.href = 'index.html';
  });
}

// ── Auth guard ───────────────────────────────────────────
// Oturum durumu netleşince: giriş yoksa index'e at, varsa menüyü kur.
authReady.then((user) => {
  if (!user) {
    window.location.href = 'index.html';
    return;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUserMenu);
  } else {
    initUserMenu();
  }
});

// ── Fetch wrapper ────────────────────────────────────────
// Ölçüm burada duruyor çünkü BÜTÜN istekler buradan geçiyor: tek yere yazılan
// ölçüm, çağıran hiçbir dosyayı değiştirmeden hepsini kapsıyor (backend'de aynı
// işi @timed decorator'ı yapıyordu — fikir aynı, sözdizimi farklı).
//
// Ölçülen süre backend'in ölçtüğünden FAZLA: token alma, ağ gecikmesi ve JSON
// parse de içinde. Aradaki fark ağ + istemci maliyeti; Render uykudaysa o
// 30-60 saniye de yalnızca burada görünür (backend henüz çalışmıyor).
async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const start = performance.now();

  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    'authorization': `Bearer ${token}`,
    ...(options.headers || {}),
  };

  let res;
  try {
    res = await fetch(`${API}${path}`, { ...options, headers });
  } catch (err) {
    // Ağ hatası: sunucuya hiç ulaşılamadı (kapalı, DNS, CORS reddi...).
    // Bu durumun backend logunda hiçbir izi olmaz — yalnızca burada görünür.
    apiLog.error(
      `${method} ${path} failed after ${Logger.fmt(performance.now() - start)}: ${err.message}`
    );
    throw err;
  }

  if (res.status === 401) {
    apiLog.warn(`${method} ${path} -> 401, signing out`);
    logout();
    throw new Error('Session expired');
  }

  // Gövde JSON değilse (beklenmedik bir sunucu/proxy hata sayfası) json() patlar.
  // Sarmalanmazsa istek ölçümü hiç loglanmadan kaybolur ve elde sadece anlamsız
  // bir "Unexpected token <" hatası kalır.
  let data;
  try {
    data = await res.json();
  } catch (err) {
    apiLog.error(
      `${method} ${path} -> ${res.status} but body is not JSON ` +
      `(after ${Logger.fmt(performance.now() - start)}): ${err.message}`
    );
    throw err;
  }

  Logger.duration(
    'api',
    `${method} ${path} -> ${res.status}`,
    performance.now() - start,
    thresholdFor(path)
  );
  return data;
}


// ── Kullanıcı menüsü ─────────────────────────────────────
function loadUserEmail() {
  const emailEl = document.getElementById('user-email');
  if (!emailEl) return;
  // E-posta zaten Firebase kullanıcısında mevcut — ekstra istek gerekmez.
  emailEl.textContent = (auth.currentUser && auth.currentUser.email) || 'Account';
}

// ── Email doğrulama hatırlatması ─────────────────────────
// Şifreyle kaydolup email'ini doğrulamamış kullanıcılara gösterilir. Doğrulama
// önemli: doğrulanmamış email'le Google'a girilirse Firebase şifreyi siler.
// (Google kullanıcılarında emailVerified zaten true — onlara görünmez.)
function showVerifyBannerIfNeeded() {
  const user = auth.currentUser;
  if (!user || user.emailVerified) return;

  const bar = document.createElement('div');
  bar.style.cssText =
    'background:#fdf3e3;border-bottom:1px solid #e8d5b0;color:#6b4f1d;' +
    'padding:10px 16px;font-size:14px;display:flex;gap:12px;' +
    'align-items:center;justify-content:center;flex-wrap:wrap;';
  bar.innerHTML =
    '<span>Verify your email to secure your account and enable Google sign-in. ' +
    'The message may land in your spam folder.</span>';

  const btnStyle =
    'background:none;border:1px solid #b8873a;color:#6b4f1d;border-radius:4px;' +
    'padding:4px 10px;cursor:pointer;font-size:13px;';

  const btn = document.createElement('button');
  btn.textContent = 'Resend email';
  btn.style.cssText = btnStyle;
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await user.sendEmailVerification();
      btn.textContent = 'Sent — check your inbox';
    } catch {
      btn.textContent = 'Could not send';
      btn.disabled = false;
    }
  });

  // Doğrulama başka bir sekmede yapılıyor; bu sekmedeki kullanıcı nesnesi
  // eskimiş kalıyor. reload() sunucudan taze durumu çekiyor — yoksa kullanıcı
  // maildeki linke tıklasa bile banner sayfayı elle yenileyene kadar duruyor.
  const doneBtn = document.createElement('button');
  doneBtn.textContent = "I've verified";
  doneBtn.style.cssText = btnStyle;
  doneBtn.addEventListener('click', async () => {
    doneBtn.disabled = true;
    doneBtn.textContent = 'Checking…';
    try {
      await user.reload();
      if (auth.currentUser && auth.currentUser.emailVerified) {
        bar.remove();
        return;
      }
      doneBtn.textContent = 'Not verified yet';
    } catch {
      doneBtn.textContent = 'Check failed';
    }
    setTimeout(() => {
      doneBtn.textContent = "I've verified";
      doneBtn.disabled = false;
    }, 2500);
  });

  bar.appendChild(btn);
  bar.appendChild(doneBtn);
  document.body.prepend(bar);
}

function initUserMenu() {
  // Sign out butonu
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.addEventListener('click', logout);

  // Kullanıcı menüsü aç/kapa
  const userBtn = document.getElementById('user-btn');
  const dropdown = document.getElementById('user-dropdown');

  if (userBtn && dropdown) {
    userBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('hidden');
    });

    document.addEventListener('click', () => {
      dropdown.classList.add('hidden');
    });
  }

  loadUserEmail();
  showVerifyBannerIfNeeded();
}


/**
 * Tarif kartı küçük görseli (Faz 20).
 *
 * Kart üreten üç dosya var (search.js, favorites.js, collection.js) — aynı
 * markup'ı üçüne kopyalamamak için ortak yer olan api.js'te duruyor.
 *
 * Görsel URL'si yoksa BOŞ dize döner, yani kart eskisi gibi düz metin olur.
 * `onerror` ile kutu tamamen DOM'dan kalkıyor: linkler Food.com CDN'inde,
 * yani dış bir servise bağlıyız ve ölü linkte kırık ikon göstermektense
 * kartın metin hâline düşmesi daha iyi.
 */
function recipeThumbHtml(recipe) {
  const url = (recipe && recipe.image_url) || '';
  if (!url) return '';
  const safe = String(url)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;');
  return `<span class="recipe-thumb">` +
         `<img src="${safe}" alt="" loading="lazy" onerror="this.parentElement.remove()">` +
         `</span>`;
}
