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
const favoriteBtn  = document.getElementById('favorite-btn');

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