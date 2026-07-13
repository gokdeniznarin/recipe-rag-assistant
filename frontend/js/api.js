/**
 * Ortak API katmanı. Her sayfa bu dosyayı en başta yükler.
 * - Token'ı localStorage'dan yönetir
 * - Token yoksa giriş sayfasına atar (index.html hariç)
 * - Fetch wrapper'ı: her istekte Authorization header ekler
 * - 401 dönerse otomatik çıkış yapar
 */

const API = 'http://localhost:8080';

// ── Token ────────────────────────────────────────────────
function getToken() {
  return localStorage.getItem('recipe_token');
}

function clearToken() {
  localStorage.removeItem('recipe_token');
}

function logout() {
  clearToken();
  window.location.href = 'index.html';
}

// Auth zorunlu — token yoksa index.html'e at
if (!getToken()) {
  window.location.href = 'index.html';
}

// ── Fetch wrapper ────────────────────────────────────────
async function apiRequest(path, options = {}) {
  const token = getToken();
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
async function loadUserEmail() {
  const emailEl = document.getElementById('user-email');
  if (!emailEl) return;

  try {
    const data = await apiRequest('/api/auth/me');
    emailEl.textContent = data.email;
  } catch {
    emailEl.textContent = 'Account';
  }
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
}

// DOM hazırsa hemen çalıştır, değilse bekle
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initUserMenu);
} else {
  initUserMenu();
}