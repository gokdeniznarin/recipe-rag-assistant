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

// ── Ortak: sign out butonu ───────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('logout-btn');
  if (btn) btn.addEventListener('click', logout);
});