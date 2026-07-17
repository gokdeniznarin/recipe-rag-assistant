/**
 * Ortak API katmanı. Her korumalı sayfa bu dosyayı firebase.js'ten sonra yükler.
 * - Kimlik doğrulama Firebase Auth ile yönetilir
 * - Oturum yoksa giriş sayfasına atar
 * - Fetch wrapper'ı: her istekte Firebase ID token'ını Authorization header'a ekler
 * - 401 dönerse otomatik çıkış yapar
 */

// Sayfa hangi host'tan açıldıysa API'yi de oradan çağır: bilgisayarda
// localhost, telefondan LAN IP'si (örn. 10.240.100.10) olarak çözülür.
const API = `http://${window.location.hostname}:8080`;

// ── Token ────────────────────────────────────────────────
// Firebase ID token'ı gerektiğinde otomatik yenilenir.
async function getToken() {
  // Firebase oturumu geri yükleyene kadar bekle — yoksa sayfa yüklenirken
  // currentUser henüz null olabilir ve istek yanlışlıkla 401 alır.
  await authReady;
  const user = auth.currentUser;
  if (!user) return null;
  return await user.getIdToken();
}

function logout() {
  auth.signOut().then(() => {
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
async function apiRequest(path, options = {}) {
  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    'authorization': `Bearer ${token}`,
    ...(options.headers || {}),
  };

  const res = await fetch(`${API}${path}`, { ...options, headers });

  if (res.status === 401) {
    logout();
    throw new Error('Session expired');
  }

  return res.json();
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
    '<span>Verify your email to secure your account and enable Google sign-in.</span>';

  const btn = document.createElement('button');
  btn.textContent = 'Resend email';
  btn.style.cssText =
    'background:none;border:1px solid #b8873a;color:#6b4f1d;border-radius:4px;' +
    'padding:4px 10px;cursor:pointer;font-size:13px;';
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

  bar.appendChild(btn);
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
