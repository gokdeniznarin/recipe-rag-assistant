/**
 * Hesap sayfası — oturum bilgisi ve hesap silme.
 *
 * NEDEN YENİDEN KİMLİK DOĞRULAMA (reauthenticate) YOK — bilinçli bir ödünleşim:
 * Firebase'in önerdiği yol silmeden önce `reauthenticateWithPopup` çağırmak.
 * Ama Faz 26b'de ölçüldü ki PWA'da Google popup'ı uygulamanın üstüne açılan bir
 * Custom Tab ve o akış altı tur hata ayıklama gerektirdi. Silme yolunu ona
 * bağlamak, kullanıcının hesabını silememesi (ya da yarıda kalması) riskini
 * geri getirirdi. Bunun yerine: ayrı sayfa + modal + DELETE yazma + sunucu
 * tarafında ikinci bir onay kontrolü. Oturumu açık bir cihaza fiziksel erişimi
 * olan birine karşı bu daha zayıf; kaybı kayda geçiriyoruz.
 */
const accountLog = Logger.get('account');

const emailEl = document.getElementById('account-email');
const providerEl = document.getElementById('account-provider');
const verifiedEl = document.getElementById('account-verified');
const errorEl = document.getElementById('account-error');

const deleteBtn = document.getElementById('delete-btn');
const modal = document.getElementById('delete-modal');
const deleteEmailEl = document.getElementById('delete-email');
const confirmInput = document.getElementById('delete-confirm-input');
const confirmBtn = document.getElementById('delete-confirm');
const cancelBtn = document.getElementById('delete-cancel');
const deleteErrorEl = document.getElementById('delete-error');

const CONFIRM_WORD = 'DELETE';

// Sağlayıcı kimliğini okunur bir ada çeviriyoruz. Bu bilgi kullanıcı için
// pratik: "şifremi neden soramıyorum?" sorusunun cevabı burada görünüyor.
function providerLabel(user) {
  const ids = (user.providerData || []).map((p) => p.providerId);
  const names = [];
  if (ids.includes('google.com')) names.push('Google');
  if (ids.includes('password')) names.push('Email and password');
  return names.length ? names.join(' + ') : 'Unknown';
}

authReady.then((user) => {
  if (!user) return;      // auth guard (api.js) zaten index.html'e yönlendiriyor
  emailEl.textContent = user.email || '—';
  providerEl.textContent = providerLabel(user);
  verifiedEl.textContent = user.emailVerified ? 'Yes' : 'Not yet';
  deleteEmailEl.textContent = user.email || '';
});

// ── Modal ────────────────────────────────────────────────
function openModal() {
  confirmInput.value = '';
  confirmBtn.disabled = true;
  deleteErrorEl.classList.add('hidden');
  deleteErrorEl.textContent = '';
  modal.classList.remove('hidden');
  confirmInput.focus();
}

function closeModal() {
  modal.classList.add('hidden');
}

deleteBtn.addEventListener('click', openModal);
cancelBtn.addEventListener('click', closeModal);

// Boşluk kırpılıyor (mobil klavyeler kelimeden sonra boşluk ekleyebiliyor) ama
// büyük/küçük harf kırpılMIYOR: yazmanın kendisi bilinçli bir adım olmalı.
confirmInput.addEventListener('input', () => {
  confirmBtn.disabled = confirmInput.value.trim() !== CONFIRM_WORD;
});

// Modal dışına tıklama ve Escape kapatıyor — ama yalnızca silme BAŞLAMADIYSA.
modal.addEventListener('click', (e) => {
  if (e.target === modal && !confirmBtn.dataset.busy) closeModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !modal.classList.contains('hidden') && !confirmBtn.dataset.busy) {
    closeModal();
  }
});

// ── Silme ────────────────────────────────────────────────
confirmBtn.addEventListener('click', async () => {
  if (confirmInput.value.trim() !== CONFIRM_WORD) return;

  // `busy` iki işi birden yapıyor: çift tıklamayı engelliyor ve modalın
  // kapanmasını yasaklıyor. İkincisi önemli — kullanıcı silme sürerken
  // modalı kapatırsa hiçbir geri bildirim göremeden sayfada kalırdı.
  confirmBtn.dataset.busy = '1';
  confirmBtn.disabled = true;
  cancelBtn.disabled = true;
  confirmBtn.textContent = 'Deleting…';
  deleteErrorEl.classList.add('hidden');

  const start = performance.now();

  try {
    const data = await apiRequest('/api/account/delete', {
      method: 'POST',
      body: JSON.stringify({ confirm: CONFIRM_WORD }),
    });

    // Backend yıkıcı işlemlerde 500 yerine 200 + {error} döndürüyor
    // (Faz 11b kuralı), o yüzden gövdeye bakmak ŞART.
    if (data.error) throw new Error(data.error);

    Logger.duration('account', 'delete account', performance.now() - start, 10000);
    accountLog.info('Account deleted; signing out');

    // Oturumu kapat ve sekmeye özel veriyi temizle. `clearSessionScopedData`
    // burada atlanamaz: sessionStorage'daki arama sonuçları silinen hesaba
    // ait ve aynı tarayıcıda kalırlardı (Faz 20'deki gizlilik hatası).
    clearSessionScopedData();
    try {
      await auth.signOut();
    } catch (e) {
      // Hesap sunucuda zaten yok; yerel oturumu kapatamamak silmeyi geçersiz
      // kılmaz, kullanıcıyı yine de dışarı alıyoruz.
      accountLog.warn('Sign-out after deletion failed: ' + e.message);
    }
    window.location.replace('/index.html?deleted=1');
  } catch (err) {
    accountLog.error('Account deletion failed: ' + err.message);
    // Yarıda kalmış olabilir — ve bu SIRA sayesinde güvenli: Firestore verisi
    // önce siliniyor, Auth kaydı en son. Kullanıcı hâlâ giriş yapmış durumda,
    // tekrar denemesi kalanı temizler.
    deleteErrorEl.textContent =
      'Could not delete your account. Please try again — if it was partly done, ' +
      'trying again finishes the job.';
    deleteErrorEl.classList.remove('hidden');
    delete confirmBtn.dataset.busy;
    confirmBtn.disabled = false;
    cancelBtn.disabled = false;
    confirmBtn.textContent = 'Delete forever';
  }
});
