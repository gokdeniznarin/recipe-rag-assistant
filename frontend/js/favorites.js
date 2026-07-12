// ── DOM ──────────────────────────────────────────────────
const loading       = document.getElementById('loading');
const listEl        = document.getElementById('favorites-list');
const emptyState    = document.getElementById('empty-state');
const errorEl       = document.getElementById('favorites-error');

// ── Yardımcı ─────────────────────────────────────────────
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function renderRecipeCard(recipe) {
  const tagOrder = ['vegan', 'vegetarian', 'pescatarian', 'gluten_free', 'dairy_free', 'nut_free'];
  const activeTags = tagOrder
    .filter(k => recipe.diet_tags[k])
    .map(k => k.replace('_', '-'));

  const tagsHtml = activeTags
    .map(t => `<span class="tag">${t}</span>`)
    .join('');

  const card = document.createElement('a');
  card.href = `recipe.html?id=${encodeURIComponent(recipe.id)}`;
  card.className = 'recipe-card';
  card.innerHTML = `
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

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  try {
    // 1. Favori ID listesini al
    const favData = await apiRequest('/api/favorites');
    const favorites = favData.favorites || [];

    if (favorites.length === 0) {
      loading.classList.add('hidden');
      emptyState.classList.remove('hidden');
      return;
    }

    // 2. Her ID için detay endpoint'inden tarif bilgisi çek (paralel)
    const detailPromises = favorites.map(f =>
      apiRequest(`/api/recipes/${encodeURIComponent(f.recipe_id)}`)
        .catch(() => null)  // hata olan tarifleri sessizce atla
    );
    const recipes = (await Promise.all(detailPromises))
      .filter(r => r && !r.error);

    // 3. Render
    recipes.forEach(recipe => {
      listEl.appendChild(renderRecipeCard(recipe));
    });

    loading.classList.add('hidden');
    listEl.classList.remove('hidden');
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load favorites.';
    errorEl.classList.remove('hidden');
  }
})();