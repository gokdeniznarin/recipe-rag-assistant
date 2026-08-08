// ── DOM ──────────────────────────────────────────────────
const loading       = document.getElementById('loading');
const listEl        = document.getElementById('favorites-list');
const emptyState    = document.getElementById('empty-state');
const errorEl       = document.getElementById('favorites-error');
const savedHeading  = document.getElementById('saved-heading');

const collectionsSection = document.getElementById('collections-section');
const collectionsGrid    = document.getElementById('collections-grid');
const newTile            = document.getElementById('new-collection-tile');
const newForm            = document.getElementById('new-collection-form');
const newInput           = document.getElementById('new-collection-input');
const newCancel          = document.getElementById('new-collection-cancel');
const newError           = document.getElementById('new-collection-error');

// ── Yardımcı ─────────────────────────────────────────────
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── Tarif kartı (favori listesi) ─────────────────────────
function renderRecipeCard(recipe) {
  const tagOrder = ['vegan', 'vegetarian', 'pescatarian', 'gluten_free', 'dairy_free', 'nut_free'];
  const activeTags = tagOrder
    .filter(k => recipe.diet_tags[k])
    .map(k => k.replace('_', '-'));

  const tagsHtml = activeTags
    .map(t => `<span class="tag">${t}</span>`)
    .join('');

  const card = document.createElement('a');
  card.href = `/recipes/${encodeURIComponent(recipe.id)}`;
  card.className = 'recipe-card';
  card.innerHTML = `
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
  `;
  return card;
}

// ── Koleksiyon kartları ──────────────────────────────────
function renderCollectionTile(coll) {
  const count = (coll.recipe_ids || []).length;
  const tile = document.createElement('a');
  tile.href = `collection.html?id=${encodeURIComponent(coll.id)}`;
  tile.className = 'collection-tile';
  tile.innerHTML = `
    <span class="collection-tile-name">${escapeHtml(coll.name)}</span>
    <span class="collection-tile-count">${count} ${count === 1 ? 'recipe' : 'recipes'}</span>
  `;
  return tile;
}

function renderCollections(collections) {
  // "New collection" kutucuğunu koruyup önündeki eski kartları temizle.
  collectionsGrid.querySelectorAll('.collection-tile:not(.collection-tile--new)')
    .forEach(el => el.remove());

  // Kartları "New" kutucuğunun ÖNÜNE ekle (kutucuk hep en sonda kalsın).
  collections.forEach(coll => {
    collectionsGrid.insertBefore(renderCollectionTile(coll), newTile);
  });
}

// ── Yeni koleksiyon oluşturma ────────────────────────────
function openNewCollectionForm() {
  newForm.classList.remove('hidden');
  newTile.classList.add('hidden');
  newError.classList.add('hidden');
  newInput.value = '';
  newInput.focus();
}

function closeNewCollectionForm() {
  newForm.classList.add('hidden');
  newTile.classList.remove('hidden');
  newError.classList.add('hidden');
}

newTile.addEventListener('click', openNewCollectionForm);
newCancel.addEventListener('click', closeNewCollectionForm);

newForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = newInput.value.trim();
  if (!name) return;

  const submitBtn = newForm.querySelector('button[type="submit"]');
  submitBtn.disabled = true;

  try {
    const res = await apiRequest('/api/collections', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });

    // Backend biçim/aynı-isim hatalarını 200 + {"error": ...} olarak dönüyor
    // (favorilerdeki kalıp) — bunu kullanıcıya göster, sayfayı bozma.
    if (res.error) {
      newError.textContent = res.error;
      newError.classList.remove('hidden');
      submitBtn.disabled = false;
      return;
    }

    // Yeni koleksiyona git — henüz boş, kullanıcı oraya tarif ekleyebilir.
    window.location.href = `collection.html?id=${encodeURIComponent(res.id)}`;
  } catch (err) {
    newError.textContent = 'Could not create the collection.';
    newError.classList.remove('hidden');
    submitBtn.disabled = false;
  }
});

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  try {
    // Koleksiyonları ve favorileri PARALEL çek — birbirlerini beklemesinler.
    const [collData, favData] = await Promise.all([
      apiRequest('/api/collections'),
      apiRequest('/api/favorites?include_details=true'),
    ]);

    const collections = collData.collections || [];
    const favorites = favData.favorites || [];

    loading.classList.add('hidden');

    // Koleksiyonlar bölümü her zaman görünür (yeni koleksiyon oluşturma buradan).
    renderCollections(collections);
    collectionsSection.classList.remove('hidden');

    if (favorites.length === 0) {
      // Hiç kayıt yok VE hiç koleksiyon yoksa büyük boş durumu göster.
      if (collections.length === 0) {
        emptyState.classList.remove('hidden');
      }
      return;
    }

    // Tarifi bulunamayan favorileri atla (veri setinden kalkmış olabilir).
    const recipes = favorites.map(f => f.recipe).filter(Boolean);
    recipes.forEach(recipe => listEl.appendChild(renderRecipeCard(recipe)));

    savedHeading.classList.remove('hidden');
    listEl.classList.remove('hidden');
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load your recipes.';
    errorEl.classList.remove('hidden');
  }
})();
