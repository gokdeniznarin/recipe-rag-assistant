// ── DOM ──────────────────────────────────────────────────
const loading      = document.getElementById('loading');
const listSection  = document.getElementById('list-section');
const itemsEl      = document.getElementById('shopping-items');
const countEl      = document.getElementById('shopping-count');
const emptyState   = document.getElementById('empty-state');
const errorEl      = document.getElementById('shopping-error');

const weekLabel    = document.getElementById('week-label');
const prevWeekBtn  = document.getElementById('prev-week');
const nextWeekBtn  = document.getElementById('next-week');
const planLink     = document.getElementById('plan-link');

const addForm      = document.getElementById('add-form');
const addInput     = document.getElementById('add-input');
const addError     = document.getElementById('add-error');

const shopCta      = document.getElementById('shop-cta');
const shopNote     = document.getElementById('shop-note');

// Buton/not metnini config'deki mağaza adına göre kur (tek yerde tanımlı).
shopCta.textContent = `Browse groceries on ${window.SHOP.store} →`;
shopNote.textContent = `Tap ${window.SHOP.store} ↗ next to an item to go straight to that product.`;

// ── Durum ────────────────────────────────────────────────
let currentWeek = null;   // "YYYY-MM-DD" (pazartesi)
let items = [];           // [{name, source, from_recipes, checked}]
let recipeCount = 0;      // haftada planlı tarif sayısı (boş durum mesajı için)

const emptyTitle = document.querySelector('#empty-state .empty-title');
const emptyText  = document.querySelector('#empty-state .empty-text');

// ── Tarih yardımcıları ───────────────────────────────────
// plan.js ile aynı: `toISOString()` KULLANMIYORUZ (UTC'ye çevirip günü kaydırır).
function toISO(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function mondayOf(d) {
  const copy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - dow);
  return copy;
}

function addDays(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  return toISO(new Date(y, m - 1, d + n));
}

function formatWeekLabel(mondayISO) {
  const [y, m, d] = mondayISO.split('-').map(Number);
  const start = new Date(y, m - 1, d);
  const end = new Date(y, m - 1, d + 6);
  const opts = { month: 'short', day: 'numeric' };
  return `${start.toLocaleDateString('en-US', opts)} – ${end.toLocaleDateString('en-US', opts)}, ${end.getFullYear()}`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, '&quot;');
}

// ── Render ───────────────────────────────────────────────
function render() {
  itemsEl.innerHTML = '';

  if (items.length === 0) {
    listSection.classList.add('hidden');
    // Boş listenin İKİ nedeni var, mesaj ona göre:
    if (recipeCount > 0) {
      emptyTitle.textContent = "You're all stocked";
      emptyText.textContent = "Your pantry already covers everything this week's plan needs. Nothing to buy.";
    } else {
      emptyTitle.textContent = 'Nothing to buy yet';
      emptyText.textContent = "Plan some meals for this week and we'll list what you're missing — everything the recipes need that isn't already in your pantry.";
    }
    emptyState.classList.remove('hidden');
    return;
  }

  emptyState.classList.add('hidden');

  const remaining = items.filter(i => !i.checked).length;
  countEl.textContent = remaining === 0
    ? 'All set — everything checked off'
    : `${remaining} ${remaining === 1 ? 'item' : 'items'} to buy`;

  items.forEach(item => itemsEl.appendChild(renderItem(item)));
  listSection.classList.remove('hidden');
  shopCta.disabled = remaining === 0;
}

function renderItem(item) {
  const li = document.createElement('li');
  li.className = 'shopping-item' + (item.checked ? ' is-checked' : '');

  // Kaynak notu: hangi tarif(ler)den geldi, ya da elle eklendi.
  let sub = '';
  if (item.source === 'custom') {
    sub = 'Added by you';
  } else if (item.from_recipes && item.from_recipes.length) {
    sub = item.from_recipes.length <= 2
      ? item.from_recipes.join(', ')
      : `${item.from_recipes.length} recipes`;
  }

  const removeBtn = item.source === 'custom'
    ? `<button class="shopping-remove" type="button" aria-label="Remove ${escapeAttr(item.name)}" title="Remove">×</button>`
    : '';

  // Satır-başına market linki: yalnızca ALINACAK (işaretsiz) malzemelerde.
  // Malzeme Türkçe'ye çevrilip market aramasına gidiyor (affiliate config
  // uygulanmış URL). Tek malzeme = tek ürün araması, markette sepete atılır.
  // Malzeme adı DOĞRUDAN aranıyor — dataset İngilizce, amazon.com İngilizce,
  // araya çeviri girmiyor (Migros dönemindeki EN→TR katmanı kalktı).
  // rel="sponsored": affiliate/ücretli link için web standardı işaret; arama
  // motorları bunu bekliyor. noopener güvenlik için.
  const findLink = !item.checked
    ? `<a class="shopping-find" href="${escapeAttr(Stores.buildUrl(item.name, window.SHOP))}"
          target="_blank" rel="noopener sponsored"
          title="Find on ${escapeAttr(window.SHOP.store)}">${escapeHtml(window.SHOP.store)} ↗</a>`
    : '';

  li.innerHTML = `
    <label class="shopping-check">
      <input type="checkbox" ${item.checked ? 'checked' : ''} />
      <span class="shopping-body">
        <span class="shopping-name">${escapeHtml(item.name)}</span>
        ${sub ? `<span class="shopping-sub">${escapeHtml(sub)}</span>` : ''}
      </span>
    </label>
    <span class="shopping-actions">${findLink}${removeBtn}</span>
  `;

  li.querySelector('input').addEventListener('change', (e) => toggleCheck(item, e.target));

  if (item.source === 'custom') {
    li.querySelector('.shopping-remove').addEventListener('click', () => removeCustom(item));
  }

  return li;
}

// ── İşaretleme ───────────────────────────────────────────
async function toggleCheck(item, checkbox) {
  const nowChecked = checkbox.checked;
  checkbox.disabled = true;
  try {
    const res = await apiRequest('/api/shopping-list/check', {
      method: 'POST',
      body: JSON.stringify({ week: currentWeek, name: item.name, checked: nowChecked }),
    });
    if (res.error) {
      checkbox.checked = !nowChecked;      // geri al
      showTransientError(res.error);
      return;
    }
    item.checked = nowChecked;
    render();   // sayacı ve "hepsi tamam" durumunu güncelle
  } catch (err) {
    checkbox.checked = !nowChecked;
    showTransientError('Could not update the list.');
  } finally {
    checkbox.disabled = false;
  }
}

// ── Elle ekleme / çıkarma ────────────────────────────────
addForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = addInput.value.trim();
  if (!name) return;

  const submitBtn = addForm.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  addError.classList.add('hidden');

  try {
    const data = await apiRequest('/api/shopping-list/custom', {
      method: 'POST',
      body: JSON.stringify({ week: currentWeek, name }),
    });

    if (data.error) {
      addError.textContent = data.error;
      addError.classList.remove('hidden');
      return;
    }
    if (data.skipped && !data.added) {
      addError.textContent = `"${name}" is already on your list.`;
      addError.classList.remove('hidden');
    }

    addInput.value = '';
    await loadWeek(currentWeek);   // listeyi tazele (yeni öğe doğru yere otursun)
  } catch (err) {
    addError.textContent = 'Could not add the item.';
    addError.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    addInput.focus();
  }
});

async function removeCustom(item) {
  try {
    const res = await apiRequest(
      `/api/shopping-list/custom?week=${encodeURIComponent(currentWeek)}&name=${encodeURIComponent(item.name)}`,
      { method: 'DELETE' }
    );
    if (res.error) {
      showTransientError(res.error);
      return;
    }
    items = items.filter(i => i !== item);
    render();
  } catch (err) {
    showTransientError('Could not remove the item.');
  }
}

// ── Shop CTA (gelir kapısı) ──────────────────────────────
// Mağaza anasayfasını açıyor; affiliate etiketi bu linke de işleniyor.
// Asıl ürün bulma işi satır-başına "↗" linklerinde (tek ürün araması) —
// çoklu terimi tek aramaya doldurmak kötü sonuç veriyordu.
shopCta.addEventListener('click', () => {
  window.open(Stores.storeHome(window.SHOP), '_blank', 'noopener');
});

// ── Hafta yükleme ────────────────────────────────────────
function showTransientError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove('hidden');
  setTimeout(() => errorEl.classList.add('hidden'), 3000);
}

async function loadWeek(mondayISO) {
  currentWeek = mondayISO;
  weekLabel.textContent = formatWeekLabel(mondayISO);
  planLink.href = `plan.html?week=${encodeURIComponent(mondayISO)}`;

  listSection.classList.add('hidden');
  emptyState.classList.add('hidden');
  loading.classList.remove('hidden');

  try {
    const data = await apiRequest(`/api/shopping-list?week=${encodeURIComponent(mondayISO)}`);
    loading.classList.add('hidden');

    if (data.error) {
      errorEl.textContent = data.error;
      errorEl.classList.remove('hidden');
      return;
    }

    errorEl.classList.add('hidden');
    items = data.items || [];
    recipeCount = data.recipe_count || 0;
    render();
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load your shopping list.';
    errorEl.classList.remove('hidden');
  }
}

prevWeekBtn.addEventListener('click', () => loadWeek(addDays(currentWeek, -7)));
nextWeekBtn.addEventListener('click', () => loadWeek(addDays(currentWeek, 7)));

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  const requested = new URLSearchParams(window.location.search).get('week');
  let start = mondayOf(new Date());
  if (requested) {
    const parsed = new Date(`${requested}T00:00:00`);
    if (!isNaN(parsed.getTime())) start = mondayOf(parsed);
  }
  await loadWeek(toISO(start));
})();
