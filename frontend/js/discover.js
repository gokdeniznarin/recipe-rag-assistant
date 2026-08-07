/**
 * Küratörlü koleksiyon sayfası (Faz 29) — Pinterest pin'lerinin indiği yer.
 *
 * Giriş GEREKTİRMİYOR. Sayfanın tamamı, gelen ziyaretçinin tarifleri hiçbir
 * kapıya takılmadan görmesi üzerine kurulu; kayıt daveti kenar çubuğunda ve
 * sayfa sonunda duruyor, içeriğin önünde değil.
 */
const discoverLog = Logger.get('discover');

// Slug iki yoldan gelebiliyor: sunucu tarafı render (`/discover/cookies`)
// gömüyor, ya da elle `discover.html?c=cookies` yazılıyor.
const discoverParams = new URLSearchParams(window.location.search);
const slug = window.__COLLECTION_SLUG__ || discoverParams.get('c');

// SSR koleksiyonu da gömüyor — böylece sayfa açılır açılmaz dolu geliyor,
// `apiRequest`'in `authReady` beklemesi (canlıda ~975 ms, Faz 13b) hiç
// ödenmiyor. Pinterest'ten gelen için bu, boş ekranda geçen bir saniye demekti.
const embeddedCollection = window.__COLLECTION_DATA__ || null;

const loadingEl = document.getElementById('discover-loading');
const errorEl = document.getElementById('discover-error');
const contentEl = document.getElementById('discover-content');
const titleEl = document.getElementById('discover-title');
const descEl = document.getElementById('discover-description');
const gridEl = document.getElementById('discover-grid');
const countEl = document.getElementById('discover-count');
const indexEl = document.getElementById('discover-index');

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : text;
  return div.innerHTML;
}

function renderCollection(data) {
  titleEl.textContent = data.title;
  descEl.textContent = data.description;
  countEl.textContent = `${data.recipes.length} recipes`;
  document.title = `${data.title} — Recipe Assistant`;

  gridEl.innerHTML = '';
  data.recipes.forEach((recipe) => {
    const card = document.createElement('a');
    // Kanonik adres: pin'lerin ve arama motorlarının gördüğü biçim.
    // `recipe.html?id=` de çalışıyor ama tek bir adres tutmak, aynı tarifin
    // iki farklı URL'de indekslenmesini önlüyor.
    card.href = `/recipes/${encodeURIComponent(recipe.id)}`;
    card.className = 'recipe-card';
    card.innerHTML = `
      ${recipeThumbHtml(recipe)}
      <div class="recipe-card-body">
        <h3 class="recipe-name">${escapeHtml(recipe.name)}</h3>
        <p class="recipe-meta">
          ${recipe.category ? escapeHtml(recipe.category) : ''}
          ${recipe.total_time_min > 0 ? ` · ${recipe.total_time_min} min` : ''}
        </p>
      </div>`;
    gridEl.appendChild(card);
  });
}

/** Sayfa sonundaki diğer koleksiyonlar — ziyaretçiyi sitede tutan halka. */
async function renderIndex() {
  try {
    const res = await fetch(`${window.API_BASE}/api/discover`);
    const data = await res.json();
    const others = (data.collections || []).filter((c) => c.slug !== slug);
    if (!others.length) return;

    indexEl.innerHTML = others
      .map((c) => `<a class="discover-chip" href="/discover/${encodeURIComponent(c.slug)}">${escapeHtml(c.title)}</a>`)
      .join('');
    indexEl.parentElement.classList.remove('hidden');
  } catch (err) {
    // Yutuluyor: bu liste sayfanın ikincil parçası, gelmemesi koleksiyonu
    // göstermemek için sebep değil (tarif detayındaki "similar" ile aynı karar).
    discoverLog.debug(`collection index unavailable: ${err.message}`);
  }
}

(async () => {
  if (!slug) {
    window.location.href = 'search.html';
    return;
  }

  try {
    // `apiRequest` DEĞİL, düz `fetch`: uç zaten açık ve apiRequest önce
    // `authReady`'yi bekliyor — giriş yapmamış ziyaretçiye o beklemeyi
    // ödetmenin bir karşılığı yok.
    const data = embeddedCollection
      || await (await fetch(`${window.API_BASE}/api/discover/${encodeURIComponent(slug)}`)).json();

    if (data.error || !data.recipes) {
      loadingEl.classList.add('hidden');
      errorEl.textContent = data.error || 'Could not load this collection.';
      errorEl.classList.remove('hidden');
      return;
    }

    renderCollection(data);
    loadingEl.classList.add('hidden');
    contentEl.classList.remove('hidden');
    renderIndex();
  } catch (err) {
    discoverLog.error(`could not load collection ${slug}: ${err.message}`);
    loadingEl.classList.add('hidden');
    errorEl.textContent = 'Could not load this collection.';
    errorEl.classList.remove('hidden');
  }
})();
