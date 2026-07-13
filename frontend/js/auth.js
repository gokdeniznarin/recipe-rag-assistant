const API = 'http://localhost:8080';

// ── Token yönetimi ───────────────────────────────────────
function saveToken(token) {
  localStorage.setItem('recipe_token', token);
}

function getToken() {
  return localStorage.getItem('recipe_token');
}

function clearToken() {
  localStorage.removeItem('recipe_token');
}

// Zaten giriş yapılmışsa direkt search.html'e yönlendir
if (getToken()) {
  window.location.href = 'search.html';
}

// ── Tab geçişi ───────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const tab = btn.dataset.tab;
    document.getElementById('login-form').classList.toggle('hidden', tab !== 'login');
    document.getElementById('register-form').classList.toggle('hidden', tab !== 'register');

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

  try {
    const res  = await fetch(`${API}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();

    if (data.access_token) {
      saveToken(data.access_token);
      window.location.href = 'search.html';
    } else {
      errorEl.textContent = data.error || 'Invalid email or password.';
    }
  } catch {
    errorEl.textContent = 'Could not reach the server. Is it running?';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sign in';
  }
});

// ── Kayıt ────────────────────────────────────────────────
document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const email     = document.getElementById('reg-email').value.trim();
  const password  = document.getElementById('reg-password').value;
  const errorEl   = document.getElementById('register-error');
  const successEl = document.getElementById('register-success');
  const btn       = e.target.querySelector('button[type="submit"]');

  errorEl.textContent = '';
  successEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Creating account…';

  try {
    const res  = await fetch(`${API}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();

    if (data.message) {
      successEl.classList.remove('hidden');
      e.target.reset();
    } else {
      errorEl.textContent = data.error || 'Registration failed.';
    }
  } catch {
    errorEl.textContent = 'Could not reach the server. Is it running?';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create account';
  }
});



// ── Google Sign-In ───────────────────────────────────────
const GOOGLE_CLIENT_ID = '490027664953-ne5lp527bovm51j30qh3aqrto329fjog.apps.googleusercontent.com';

async function handleGoogleCredential(response) {
  const errorEl = document.getElementById('google-error');
  errorEl.textContent = '';

  try {
    const res = await fetch(`${API}/api/auth/google`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: response.credential }),
    });
    const data = await res.json();

    if (data.access_token) {
      saveToken(data.access_token);
      window.location.href = 'search.html';
    } else {
      errorEl.textContent = data.error || 'Google sign-in failed.';
    }
  } catch {
    errorEl.textContent = 'Could not reach the server. Is it running?';
  }
}

// Google kütüphanesi yüklendiğinde butonu render et
window.addEventListener('load', () => {
  if (typeof google === 'undefined') {
    console.warn('Google Identity Services could not be loaded.');
    return;
  }

  google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: handleGoogleCredential,
  });

  google.accounts.id.renderButton(
    document.getElementById('google-btn'),
    {
      theme: 'outline',
      size: 'large',
      text: 'continue_with',
      shape: 'rectangular',
    }
  );
});