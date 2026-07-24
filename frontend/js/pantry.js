// ── DOM ──────────────────────────────────────────────────
const loading      = document.getElementById('loading');
const sectionEl    = document.getElementById('pantry-section');
const itemsEl      = document.getElementById('pantry-items');
const countEl      = document.getElementById('pantry-count');
const emptyState   = document.getElementById('empty-state');
const errorEl      = document.getElementById('pantry-error');

const addForm      = document.getElementById('add-form');
const addInput     = document.getElementById('add-input');
const addError     = document.getElementById('add-error');

const clearAllBtn  = document.getElementById('clear-all-btn');
const clearModal   = document.getElementById('clear-modal');
const clearCount   = document.getElementById('clear-count');
const clearCancel  = document.getElementById('clear-cancel');
const clearConfirm = document.getElementById('clear-confirm');

// ── Yardımcı ─────────────────────────────────────────────
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function showTransientError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove('hidden');
  setTimeout(() => errorEl.classList.add('hidden'), 3000);
}

// ── Render ───────────────────────────────────────────────
function renderPantry(items) {
  itemsEl.innerHTML = '';

  if (items.length === 0) {
    sectionEl.classList.add('hidden');
    emptyState.classList.remove('hidden');
    return;
  }

  emptyState.classList.add('hidden');
  countEl.textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'}`;

  items.forEach(item => itemsEl.appendChild(renderChip(item)));
  sectionEl.classList.remove('hidden');
}

function renderChip(item) {
  const chip = document.createElement('span');
  chip.className = 'pantry-chip';
  chip.innerHTML = `
    <span class="pantry-chip-name">${escapeHtml(item.name)}</span>
    <button class="pantry-chip-remove" aria-label="Remove ${escapeHtml(item.name)}" title="Remove">×</button>
  `;

  chip.querySelector('.pantry-chip-remove').addEventListener('click', async () => {
    const btn = chip.querySelector('.pantry-chip-remove');
    btn.disabled = true;
    try {
      const res = await apiRequest(`/api/pantry?name=${encodeURIComponent(item.name)}`, {
        method: 'DELETE',
      });
      if (res.error) {
        showTransientError(res.error);
        btn.disabled = false;
        return;
      }
      chip.remove();

      // Kalan sayıyı güncelle; sıfırlandıysa boş duruma geç.
      const remaining = itemsEl.querySelectorAll('.pantry-chip').length;
      countEl.textContent = `${remaining} ${remaining === 1 ? 'item' : 'items'}`;
      if (remaining === 0) {
        sectionEl.classList.add('hidden');
        emptyState.classList.remove('hidden');
      }
    } catch (err) {
      showTransientError('Could not remove the ingredient.');
      btn.disabled = false;
    }
  });

  return chip;
}

// ── Ekleme ───────────────────────────────────────────────
addForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = addInput.value.trim();
  if (!name) return;

  const submitBtn = addForm.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  addError.classList.add('hidden');

  try {
    // Endpoint her zaman liste alıyor (kamera akışı toplu gönderiyor);
    // elle eklemede tek elemanlı liste.
    const data = await apiRequest('/api/pantry', {
      method: 'POST',
      body: JSON.stringify({ names: [name] }),
    });

    if (data.error) {
      addError.textContent = data.error;
      addError.classList.remove('hidden');
      return;
    }

    // Zaten dolaptaysa hata değil — bilgilendir, listeyi yine tazele.
    if ((data.skipped || []).length > 0 && (data.added || []).length === 0) {
      addError.textContent = `"${name}" is already in your pantry.`;
      addError.classList.remove('hidden');
    } else if ((data.invalid || []).length > 0 && (data.added || []).length === 0) {
      // Backend geçersiz isimleri parti düşürmeden atlıyor; elle eklemede tek
      // isim gönderildiği için bu "eklenemedi" demek.
      addError.textContent = "That doesn't look like a usable ingredient name.";
      addError.classList.remove('hidden');
    }

    addInput.value = '';
    renderPantry(data.items || []);   // backend güncel listeyi de dönüyor
  } catch (err) {
    addError.textContent = 'Could not add the ingredient.';
    addError.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    addInput.focus();
  }
});

// ── Dolabı boşaltma ──────────────────────────────────────
// Tek istek: eskiden 11 malzemeyi silmek 11 ayrı istek demekti (~4 sn).
clearAllBtn.addEventListener('click', () => {
  const n = itemsEl.querySelectorAll('.pantry-chip').length;
  clearCount.textContent = `${n} ${n === 1 ? 'ingredient' : 'ingredients'}`;
  clearModal.classList.remove('hidden');
});

clearCancel.addEventListener('click', () => clearModal.classList.add('hidden'));
clearModal.addEventListener('click', (e) => {
  if (e.target === clearModal) clearModal.classList.add('hidden');   // dışına tıkla
});

clearConfirm.addEventListener('click', async () => {
  clearConfirm.disabled = true;
  try {
    await apiRequest('/api/pantry/all', { method: 'DELETE' });
    clearModal.classList.add('hidden');
    renderPantry([]);          // boş duruma geç
  } catch (err) {
    clearModal.classList.add('hidden');
    showTransientError('Could not clear your pantry.');
  } finally {
    clearConfirm.disabled = false;
  }
});

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  try {
    const data = await apiRequest('/api/pantry');
    loading.classList.add('hidden');
    renderPantry(data.items || []);
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load your pantry.';
    errorEl.classList.remove('hidden');
  }
})();
