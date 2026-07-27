// URL'den koleksiyon ID'si: collection.html?id=aB3xK9
const params       = new URLSearchParams(window.location.search);
const collectionId = params.get('id');

if (!collectionId) {
  window.location.href = 'favorites.html';
}

// ── DOM ──────────────────────────────────────────────────
const loading    = document.getElementById('loading');
const sectionEl  = document.getElementById('collection');
const errorEl    = document.getElementById('collection-error');

const titleEl    = document.getElementById('collection-title');
const countEl    = document.getElementById('collection-count');
const listEl     = document.getElementById('collection-list');
const emptyEl    = document.getElementById('collection-empty');

const titleView   = document.getElementById('title-view');
const renameBtn    = document.getElementById('rename-btn');
const renameForm   = document.getElementById('rename-form');
const renameInput  = document.getElementById('rename-input');
const renameCancel = document.getElementById('rename-cancel');
const renameError  = document.getElementById('rename-error');

const deleteBtn     = document.getElementById('delete-btn');
const deleteModal   = document.getElementById('delete-modal');
const deleteCancel  = document.getElementById('delete-cancel');
const deleteConfirm = document.getElementById('delete-confirm');

// ── Yardımcı ─────────────────────────────────────────────
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function updateCount(n) {
  countEl.textContent = `${n} ${n === 1 ? 'recipe' : 'recipes'}`;
}

// ── Tarif satırı (kart + koleksiyondan çıkar butonu) ─────
function renderRecipeRow(recipe) {
  const tagOrder = ['vegan', 'vegetarian', 'pescatarian', 'gluten_free', 'dairy_free', 'nut_free'];
  const activeTags = tagOrder
    .filter(k => recipe.diet_tags[k])
    .map(k => k.replace('_', '-'));

  const tagsHtml = activeTags.map(t => `<span class="tag">${t}</span>`).join('');

  const row = document.createElement('div');
  row.className = 'collection-recipe-row';
  row.innerHTML = `
    <a href="recipe.html?id=${encodeURIComponent(recipe.id)}" class="recipe-card">
      ${recipeThumbHtml(recipe)}
      <div class="recipe-card-body">
        <h3 class="recipe-name">${escapeHtml(recipe.name)}</h3>
        <p class="recipe-meta">
          ${recipe.category ? escapeHtml(recipe.category) : ''}
          ${recipe.total_time_min > 0 ? ` · ${recipe.total_time_min} min` : ''}
          ${recipe.calories > 0 ? ` · ${Math.round(recipe.calories)} cal` : ''}
        </p>
        <div class="recipe-tags">${tagsHtml}</div>
      </div>
      <span class="recipe-arrow">→</span>
    </a>
    <button class="remove-from-collection" title="Remove from this collection"
            aria-label="Remove from this collection">Remove</button>
  `;

  attachRemove(row, recipe.id);
  return row;
}

/**
 * Tarifi artık veritabanında olmayan bir üyelik satırı.
 *
 * Önce bunlar `filter(Boolean)` ile SESSİZCE atılıyordu — ama favoriler
 * sayfasındaki sayaç saklanan `recipe_ids` uzunluğunu gösterdiği için
 * "1 recipe" yazıp içeride hiçbir şey çıkmıyordu. Sessizce yutmak yerine
 * durumu gösterip kullanıcıya temizleme imkânı veriyoruz (yemek planındaki
 * "Recipe unavailable" davranışının aynısı).
 */
function renderUnavailableRow(recipeId) {
  const row = document.createElement('div');
  row.className = 'collection-recipe-row';
  row.innerHTML = `
    <div class="recipe-card recipe-card--unavailable">
      <div class="recipe-card-body">
        <h3 class="recipe-name">Recipe unavailable</h3>
        <p class="recipe-meta">This recipe is no longer in our database.</p>
      </div>
    </div>
    <button class="remove-from-collection" title="Remove from this collection"
            aria-label="Remove from this collection">Remove</button>
  `;

  attachRemove(row, recipeId);
  return row;
}

/** Koleksiyondan çıkarma — iki satır tipi de aynı akışı kullanıyor. */
function attachRemove(row, recipeId) {
  // Koleksiyondan çıkar (favoride KALIR — sadece bu gruptan düşer).
  row.querySelector('.remove-from-collection').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await apiRequest(
        `/api/collections/${encodeURIComponent(collectionId)}/recipes/${encodeURIComponent(recipeId)}`,
        { method: 'DELETE' }
      );
      row.remove();
      const remaining = listEl.querySelectorAll('.collection-recipe-row').length;
      updateCount(remaining);
      if (remaining === 0) {
        listEl.classList.add('hidden');
        emptyEl.classList.remove('hidden');
      }
    } catch (err) {
      btn.disabled = false;
      errorEl.textContent = 'Could not remove the recipe.';
      errorEl.classList.remove('hidden');
      setTimeout(() => errorEl.classList.add('hidden'), 3000);
    }
  });
}

// ── Yeniden adlandırma ───────────────────────────────────
renameBtn.addEventListener('click', () => {
  renameInput.value = titleEl.textContent;
  renameForm.classList.remove('hidden');
  titleView.classList.add('hidden');
  renameError.classList.add('hidden');
  renameInput.focus();
});

renameCancel.addEventListener('click', () => {
  renameForm.classList.add('hidden');
  titleView.classList.remove('hidden');
  renameError.classList.add('hidden');
});

renameForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = renameInput.value.trim();
  if (!name) return;

  const saveBtn = renameForm.querySelector('button[type="submit"]');
  saveBtn.disabled = true;

  try {
    const res = await apiRequest(`/api/collections/${encodeURIComponent(collectionId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });

    // Aynı-isim / boş ad hataları 200 + {"error": ...} (favori kalıbı).
    if (res.error) {
      renameError.textContent = res.error;
      renameError.classList.remove('hidden');
      saveBtn.disabled = false;
      return;
    }

    titleEl.textContent = res.name;
    document.title = `${res.name} — Recipe Assistant`;
    renameForm.classList.add('hidden');
    titleView.classList.remove('hidden');
    saveBtn.disabled = false;
  } catch (err) {
    renameError.textContent = 'Could not rename the collection.';
    renameError.classList.remove('hidden');
    saveBtn.disabled = false;
  }
});

// ── Silme ────────────────────────────────────────────────
deleteBtn.addEventListener('click', () => deleteModal.classList.remove('hidden'));
deleteCancel.addEventListener('click', () => deleteModal.classList.add('hidden'));
deleteModal.addEventListener('click', (e) => {
  if (e.target === deleteModal) deleteModal.classList.add('hidden');   // dışına tıkla → kapat
});

deleteConfirm.addEventListener('click', async () => {
  deleteConfirm.disabled = true;
  try {
    await apiRequest(`/api/collections/${encodeURIComponent(collectionId)}`, { method: 'DELETE' });
    window.location.href = 'favorites.html';
  } catch (err) {
    deleteConfirm.disabled = false;
    deleteModal.classList.add('hidden');
    errorEl.textContent = 'Could not delete the collection.';
    errorEl.classList.remove('hidden');
  }
});

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  try {
    const data = await apiRequest(
      `/api/collections/${encodeURIComponent(collectionId)}?include_details=true`
    );

    loading.classList.add('hidden');

    if (data.error) {
      errorEl.textContent = data.error;
      errorEl.classList.remove('hidden');
      return;
    }

    titleEl.textContent = data.name;
    document.title = `${data.name} — Recipe Assistant`;

    // `recipes` ve `recipe_ids` AYNI SIRADA geliyor (backend id→kart eşlemesini
    // koruyor), bulunamayan tarif `null` oluyor. Eskiden null'lar `filter`
    // ile atılıyordu; o zaman favoriler sayfasındaki sayaç (saklanan
    // recipe_ids uzunluğu) ile burada görünen liste ÇELİŞİYORDU — "1 recipe"
    // yazıp içerisi boş kalıyordu. Artık her üyelik bir satır alıyor.
    const recipes = data.recipes || [];
    const ids = data.recipe_ids || [];
    updateCount(ids.length);

    if (ids.length === 0) {
      emptyEl.classList.remove('hidden');
    } else {
      ids.forEach((rid, i) => {
        const recipe = recipes[i];
        listEl.appendChild(recipe ? renderRecipeRow(recipe) : renderUnavailableRow(rid));
      });
    }

    sectionEl.classList.remove('hidden');
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load the collection.';
    errorEl.classList.remove('hidden');
  }
})();
