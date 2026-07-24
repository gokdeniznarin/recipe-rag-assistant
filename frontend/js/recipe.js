// URL'den ID al: recipe.html?id=37913
const params   = new URLSearchParams(window.location.search);
const recipeId = params.get('id');

if (!recipeId) {
  window.location.href = 'search.html';
}

// ── DOM ──────────────────────────────────────────────────
const loading      = document.getElementById('loading');
const recipeEl     = document.getElementById('recipe');
const errorEl      = document.getElementById('recipe-error');

const titleEl      = document.getElementById('recipe-title');
const categoryEl   = document.getElementById('recipe-category');
const tagsEl       = document.getElementById('recipe-tags');
const descEl       = document.getElementById('recipe-description');
const instructionsEl = document.getElementById('recipe-instructions');
const ingredientsEl  = document.getElementById('recipe-ingredients');
const favoriteBtn  = document.getElementById('favorite-btn');

const addCollectionBtn = document.getElementById('add-collection-btn');
const collectionPicker = document.getElementById('collection-picker');
const pickerList       = document.getElementById('picker-list');
const pickerNewForm    = document.getElementById('picker-new-form');
const pickerNewInput   = document.getElementById('picker-new-input');
const pickerError      = document.getElementById('picker-error');

const addPlanBtn     = document.getElementById('add-plan-btn');
const planModal      = document.getElementById('plan-modal');
const planDaySelect  = document.getElementById('plan-day');
const planSlotSelect = document.getElementById('plan-slot');
const planCancel     = document.getElementById('plan-cancel');
const planConfirm    = document.getElementById('plan-confirm');
const planModalError = document.getElementById('plan-modal-error');
const planStatus     = document.getElementById('plan-status');

const infoTime     = document.getElementById('info-time');
const infoCalories = document.getElementById('info-calories');
const infoProtein  = document.getElementById('info-protein');
const infoCarbs    = document.getElementById('info-carbs');
const infoFat      = document.getElementById('info-fat');

let isFavorited = false;

// ── Render ───────────────────────────────────────────────
function renderRecipe(recipe) {
  titleEl.textContent    = recipe.name;
  categoryEl.textContent = recipe.category || 'Recipe';

  // Diyet tag'leri
  const tagOrder = ['vegan', 'vegetarian', 'pescatarian', 'gluten_free', 'dairy_free', 'nut_free'];
  const activeTags = tagOrder
    .filter(k => recipe.diet_tags[k])
    .map(k => k.replace('_', '-'));

  tagsEl.innerHTML = activeTags
    .map(t => `<span class="tag">${t}</span>`)
    .join('');

  // Bilgi çubuğu
  infoTime.textContent     = recipe.total_time_min > 0 ? `${recipe.total_time_min} min` : '—';
  infoCalories.textContent = recipe.calories > 0 ? `${Math.round(recipe.calories)} kcal` : '—';
  infoProtein.textContent  = recipe.protein_content > 0 ? `${Math.round(recipe.protein_content)} g` : '—';
  infoCarbs.textContent    = recipe.carbohydrate_content > 0 ? `${Math.round(recipe.carbohydrate_content)} g` : '—';
  infoFat.textContent      = recipe.fat_content > 0 ? `${Math.round(recipe.fat_content)} g` : '—';

  // Description
  descEl.textContent = recipe.description || 'No description available.';

  // Malzemeler — Faz 17'de eklendi. Önceden metadata'da yapılandırılmış malzeme
  // listesi yoktu (yalnızca gömme metninin içinde düz yazıydı), bu yüzden detay
  // sayfası malzemeleri hiç gösteremiyordu.
  const ingredients = recipe.ingredients || [];
  ingredientsEl.innerHTML = ingredients.length === 0
    ? '<li class="no-instructions">No ingredient list available for this recipe.</li>'
    : ingredients.map(i => `<li>${escapeHtml(i)}</li>`).join('');

  // Instructions: "1. adım1 2. adım2..." formatını split ederek liste yapıyoruz
  const rawInstructions = recipe.instructions || '';
  const steps = parseInstructions(rawInstructions);

  if (steps.length === 0) {
    instructionsEl.innerHTML = '<li class="no-instructions">No instructions available for this recipe.</li>';
  } else {
    instructionsEl.innerHTML = steps
      .map(step => `<li>${escapeHtml(step)}</li>`)
      .join('');
  }
}

/**
 * "1. Melt butter. 2. Add tomatoes. 3. Simmer covered."
 * → ["Melt butter.", "Add tomatoes.", "Simmer covered."]
 */
function parseInstructions(text) {
  if (!text.trim()) return [];
  const parts = text.split(/\s*\d+\.\s+/).map(s => s.trim());
  // Anlamlı adımları tut: en az 3 karakter olmalı ve sadece noktalama işaretlerinden ibaret olmamalı
  return parts.filter(s => {
    if (s.length < 3) return false;
    // sadece virgül, backslash, boşluk, tire varsa at
    if (/^[,\\\s\-\.]+$/.test(s)) return false;
    return true;
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── Favori butonu ────────────────────────────────────────
function updateFavoriteUI() {
  if (isFavorited) {
    favoriteBtn.classList.add('is-favorited');
    favoriteBtn.querySelector('.heart').textContent = '♥';
    favoriteBtn.setAttribute('aria-label', 'Remove from favorites');
  } else {
    favoriteBtn.classList.remove('is-favorited');
    favoriteBtn.querySelector('.heart').textContent = '♡';
    favoriteBtn.setAttribute('aria-label', 'Add to favorites');
  }
}

async function checkIfFavorited() {
  try {
    const data = await apiRequest('/api/favorites');
    isFavorited = data.favorites.some(f => f.recipe_id === recipeId);
    updateFavoriteUI();
  } catch {
    // Sessizce geç, favori durumu kritik değil
  }
}

favoriteBtn.addEventListener('click', async () => {
  favoriteBtn.disabled = true;

  try {
    if (isFavorited) {
      await apiRequest(`/api/favorites/${encodeURIComponent(recipeId)}`, {
        method: 'DELETE',
      });
      isFavorited = false;
      // Favoriden çıkmak tarifi tüm koleksiyonlardan da düşürüyor (backend
      // kuralı). Seçici açıksa checkbox'lar bayatlamasın diye tazele.
      if (!collectionPicker.classList.contains('hidden')) loadCollectionsPicker();
    } else {
      await apiRequest('/api/favorites/add', {
        method: 'POST',
        body: JSON.stringify({ recipe_id: recipeId }),
      });
      isFavorited = true;
    }
    updateFavoriteUI();
  } catch (err) {
    // Basit hata, kullanıcıya kısa mesaj göster
    errorEl.textContent = 'Could not update favorites.';
    errorEl.classList.remove('hidden');
    setTimeout(() => errorEl.classList.add('hidden'), 3000);
  } finally {
    favoriteBtn.disabled = false;
  }
});

// ── Koleksiyona ekleme seçicisi ──────────────────────────
// Seçiciyi aç/kapat
addCollectionBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  const willOpen = collectionPicker.classList.contains('hidden');
  collectionPicker.classList.toggle('hidden');
  if (willOpen) loadCollectionsPicker();
});

// Dışına tıklayınca kapat (seçicinin içine tıklamak kapatmasın)
document.addEventListener('click', (e) => {
  if (!collectionPicker.classList.contains('hidden') &&
      !collectionPicker.contains(e.target) &&
      e.target !== addCollectionBtn) {
    collectionPicker.classList.add('hidden');
  }
});

// Koleksiyon listesini bu tarifin üyeliğine göre kur (checkbox durumları).
async function loadCollectionsPicker() {
  try {
    const data = await apiRequest('/api/collections');
    const collections = data.collections || [];

    pickerList.innerHTML = '';
    if (collections.length === 0) {
      pickerList.innerHTML = '<p class="picker-empty">No collections yet. Create one below.</p>';
      return;
    }

    collections.forEach(coll => {
      const inThisCollection = (coll.recipe_ids || []).includes(recipeId);

      const row = document.createElement('label');
      row.className = 'picker-row';
      row.innerHTML = `
        <input type="checkbox" ${inThisCollection ? 'checked' : ''} />
        <span class="picker-name">${escapeHtml(coll.name)}</span>
      `;

      const checkbox = row.querySelector('input');
      checkbox.addEventListener('change', async () => {
        checkbox.disabled = true;
        try {
          await toggleCollectionMembership(coll.id, checkbox.checked);
        } catch (err) {
          checkbox.checked = !checkbox.checked;   // geri al
          pickerError.textContent = 'Could not update the collection.';
          pickerError.classList.remove('hidden');
          setTimeout(() => pickerError.classList.add('hidden'), 3000);
        } finally {
          checkbox.disabled = false;
        }
      });

      pickerList.appendChild(row);
    });
  } catch (err) {
    pickerList.innerHTML = '<p class="picker-empty">Could not load collections.</p>';
  }
}

async function toggleCollectionMembership(collId, nowChecked) {
  if (nowChecked) {
    await apiRequest(`/api/collections/${encodeURIComponent(collId)}/recipes`, {
      method: 'POST',
      body: JSON.stringify({ recipe_id: recipeId }),
    });
    // Koleksiyona eklemek tarifi otomatik favoriye de ekler (backend kuralı) —
    // kalbi buna göre güncelle.
    if (!isFavorited) {
      isFavorited = true;
      updateFavoriteUI();
    }
  } else {
    await apiRequest(
      `/api/collections/${encodeURIComponent(collId)}/recipes/${encodeURIComponent(recipeId)}`,
      { method: 'DELETE' }
    );
    // Koleksiyondan çıkarmak favoriyi ETKİLEMEZ — kalp olduğu gibi kalır.
  }
}

// Yeni koleksiyon oluştur + bu tarifi hemen içine ekle
pickerNewForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = pickerNewInput.value.trim();
  if (!name) return;

  const createBtn = pickerNewForm.querySelector('button[type="submit"]');
  createBtn.disabled = true;

  try {
    const res = await apiRequest('/api/collections', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });

    if (res.error) {
      pickerError.textContent = res.error;
      pickerError.classList.remove('hidden');
      createBtn.disabled = false;
      return;
    }

    // Yeni koleksiyona bu tarifi ekle (auto-favorite dahil)
    await toggleCollectionMembership(res.id, true);
    pickerNewInput.value = '';
    pickerError.classList.add('hidden');
    await loadCollectionsPicker();   // listeyi tazele (yeni koleksiyon işaretli gelir)
  } catch (err) {
    pickerError.textContent = 'Could not create the collection.';
    pickerError.classList.remove('hidden');
  } finally {
    createBtn.disabled = false;
  }
});

// ── Plana ekleme ─────────────────────────────────────────
// Plana eklemek favoriye EKLEMEZ (koleksiyonların aksine): plan bir takvim,
// düzenleme katmanı değil — bir tarifi bir kez denemek için planlamak onu
// kalıcı kaydetmek anlamına gelmiyor.

// Tarihler YEREL üretiliyor; `toISOString()` UTC'ye çevirip Istanbul'da gece
// yarısından sonra günü bir geri kaydırırdı.
function localISO(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function fillDayOptions() {
  planDaySelect.innerHTML = '';
  const today = new Date();
  // Önümüzdeki 14 gün yetiyor: daha uzak bir plan için plan sayfasındaki hafta
  // gezinmesi var (orada boş slota tıklayarak seçiliyor).
  for (let i = 0; i < 14; i++) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
    const iso = localISO(d);
    const opt = document.createElement('option');
    opt.value = iso;
    opt.textContent = i === 0
      ? `Today · ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
      : i === 1
        ? `Tomorrow · ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
        : d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
    planDaySelect.appendChild(opt);
  }
}

addPlanBtn.addEventListener('click', () => {
  fillDayOptions();
  planModalError.classList.add('hidden');
  planModal.classList.remove('hidden');
});

planCancel.addEventListener('click', () => planModal.classList.add('hidden'));
planModal.addEventListener('click', (e) => {
  if (e.target === planModal) planModal.classList.add('hidden');
});

planConfirm.addEventListener('click', async () => {
  planConfirm.disabled = true;
  try {
    const res = await apiRequest('/api/meal-plan', {
      method: 'POST',
      body: JSON.stringify({
        date: planDaySelect.value,
        slot: planSlotSelect.value,
        recipe_id: recipeId,
      }),
    });

    if (res.error) {
      planModalError.textContent = res.error;
      planModalError.classList.remove('hidden');
      return;
    }

    planModal.classList.add('hidden');
    const dayText = planDaySelect.options[planDaySelect.selectedIndex].textContent;
    const slotText = planSlotSelect.options[planSlotSelect.selectedIndex].textContent;
    planStatus.innerHTML = `
      Planned for ${escapeHtml(slotText.toLowerCase())} on ${escapeHtml(dayText)}.
      <a href="plan.html?week=${encodeURIComponent(planDaySelect.value)}">View plan →</a>
    `;
    planStatus.classList.remove('hidden');
  } catch (err) {
    planModalError.textContent = 'Could not update your plan.';
    planModalError.classList.remove('hidden');
  } finally {
    planConfirm.disabled = false;
  }
});

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  try {
    const recipe = await apiRequest(`/api/recipes/${encodeURIComponent(recipeId)}`);

    if (recipe.error) {
      loading.classList.add('hidden');
      errorEl.textContent = recipe.error;
      errorEl.classList.remove('hidden');
      return;
    }

    renderRecipe(recipe);
    await checkIfFavorited();

    loading.classList.add('hidden');
    recipeEl.classList.remove('hidden');
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load recipe.';
    errorEl.classList.remove('hidden');
  }
})();