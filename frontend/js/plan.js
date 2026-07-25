// Öğün listesi. DOĞRULUK KAYNAĞI backend'deki meal_plan.SLOTS — burası onun
// kopyası. Sunucudan çekmek düşünüldü ve elendi: 3 elemanlı bir sabit için her
// sayfa açılışına fazladan bir ağ turu bindirirdi. Kopya sessizce ayrışmasın
// diye Katman 1'de bir test bu listeyi sabitliyor (test_meal_plan.py).
// Yanlış bir slot gönderilse bile backend `validate_slot` ile reddediyor.
const SLOTS = ['breakfast', 'lunch', 'dinner'];
const SLOT_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner' };
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// ── DOM ──────────────────────────────────────────────────
const loading      = document.getElementById('loading');
const gridEl       = document.getElementById('week-grid');
const errorEl      = document.getElementById('plan-error');

const weekLabel    = document.getElementById('week-label');
const prevWeekBtn  = document.getElementById('prev-week');
const nextWeekBtn  = document.getElementById('next-week');
const thisWeekBtn  = document.getElementById('this-week');
const weekCount    = document.getElementById('week-count');

const clearWeekBtn = document.getElementById('clear-week-btn');
const clearModal   = document.getElementById('clear-modal');
const clearCount   = document.getElementById('clear-count');
const clearCancel  = document.getElementById('clear-cancel');
const clearConfirm = document.getElementById('clear-confirm');

const pickerModal  = document.getElementById('picker-modal');
const pickerTitle  = document.getElementById('picker-title');
const pickerList   = document.getElementById('picker-recipes');
const pickerCancel = document.getElementById('picker-cancel');
const pickerError  = document.getElementById('picker-modal-error');

// ── Durum ────────────────────────────────────────────────
let currentWeek = null;      // "YYYY-MM-DD" (pazartesi)
let entries = [];            // [{date, slot, recipe_id, recipe}]
let pickerTarget = null;     // {date, slot}
let savedRecipes = null;     // seçici için favoriler (lazy, bir kez)

// ── Tarih yardımcıları ───────────────────────────────────
// TARİHLER HEP YEREL: sunucu "bugün"ü hiç hesaplamıyor (Render UTC'de çalışıyor,
// kullanıcı başka saat diliminde olabilir). Bu yüzden `toISOString()` KULLANMIYORUZ
// — o UTC'ye çevirir ve Istanbul'da 03:00'ten önce günü bir geri kaydırırdı.
function toISO(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function mondayOf(d) {
  const copy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (copy.getDay() + 6) % 7;      // getDay(): Pazar = 0 → Pazartesi = 0
  copy.setDate(copy.getDate() - dow);
  return copy;
}

function addDays(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(y, m - 1, d + n);
  return toISO(dt);
}

function formatWeekLabel(mondayISO) {
  const [y, m, d] = mondayISO.split('-').map(Number);
  const start = new Date(y, m - 1, d);
  const end = new Date(y, m - 1, d + 6);
  const opts = { month: 'short', day: 'numeric' };
  const startTxt = start.toLocaleDateString('en-US', opts);
  const endTxt = end.toLocaleDateString('en-US', opts);
  return `${startTxt} – ${endTxt}, ${end.getFullYear()}`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// escapeHtml `"` karakterini kaçırmıyor (metin bağlamı için yeterli). Bir
// ÖZNİTELİK değerinin içinde kullanılacaksa tırnak da kaçmalı, yoksa adında `"`
// olan tarifler (veri setinde 20 tane var, örn. Vegan "whipped Cream") özniteliği
// erken kapatıp bozuk HTML üretir.
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, '&quot;');
}

// ── Render ───────────────────────────────────────────────
function entryFor(date, slot) {
  return entries.find(e => e.date === date && e.slot === slot) || null;
}

const renderWeek = Logger.timed(function () {
  gridEl.innerHTML = '';
  const todayISO = toISO(new Date());

  for (let i = 0; i < 7; i++) {
    const date = addDays(currentWeek, i);

    const col = document.createElement('div');
    col.className = 'day-col' + (date === todayISO ? ' day-col--today' : '');

    const head = document.createElement('div');
    head.className = 'day-head';
    head.innerHTML = `
      <span class="day-name">${DAY_NAMES[i]}</span>
      <span class="day-num">${Number(date.split('-')[2])}</span>
    `;
    col.appendChild(head);

    SLOTS.forEach(slot => col.appendChild(renderSlot(date, slot)));
    gridEl.appendChild(col);
  }

  const n = entries.length;
  weekCount.textContent = n === 0 ? 'Nothing planned yet' : `${n} ${n === 1 ? 'meal' : 'meals'} planned`;
  clearWeekBtn.classList.toggle('hidden', n === 0);

  gridEl.classList.remove('hidden');
}, 'render week', 'plan');

function renderSlot(date, slot) {
  const entry = entryFor(date, slot);
  const cell = document.createElement('div');
  cell.className = 'plan-slot';

  const label = `<span class="plan-slot-label">${SLOT_LABELS[slot] || slot}</span>`;

  if (!entry) {
    cell.classList.add('plan-slot--empty');
    cell.innerHTML = `${label}<button class="plan-slot-add" type="button" aria-label="Add ${slot} for ${date}">＋</button>`;
    cell.querySelector('.plan-slot-add').addEventListener('click', () => openPicker(date, slot));
    return cell;
  }

  // Tarif veri setinden kalkmışsa `recipe` null gelir (favoriler/koleksiyonlarla
  // aynı davranış) — slotu boş göstermek yerine dürüst bir yer tutucu.
  const name = entry.recipe ? entry.recipe.name : 'Recipe unavailable';
  const time = entry.recipe && entry.recipe.total_time_min > 0
    ? `${entry.recipe.total_time_min} min` : '';

  // Etiket ve eylemler bir başlık satırında (space-between). Absolute konum
  // yerine flex: dar slotta (620-1000px arası 3 öğün yan yana) uzun etiket
  // butonların altına girmesin.
  cell.innerHTML = `
    <div class="plan-slot-top">
      ${label}
      <div class="plan-slot-actions">
        <button class="plan-slot-change" type="button" aria-label="Change ${escapeAttr(name)}" title="Change recipe">⇄</button>
        <button class="plan-slot-remove" type="button" aria-label="Remove ${escapeAttr(name)}" title="Remove">×</button>
      </div>
    </div>
    <a class="plan-slot-recipe" href="recipe.html?id=${encodeURIComponent(entry.recipe_id)}">
      <span class="plan-slot-name">${escapeHtml(name)}</span>
      ${time ? `<span class="plan-slot-time">${time}</span>` : ''}
    </a>
  `;

  // Dolu slotu değiştirmek: aynı seçiciyi açıyor, seçilen tarif eskisinin
  // yerine geçiyor. Backend POST zaten replace yapıyor; choose() de frontend
  // tarafında eski girdiyi düşürüp yenisini koyuyor. Yani "önce sil sonra ekle"
  // gerekmiyor.
  cell.querySelector('.plan-slot-change').addEventListener('click', () => openPicker(date, slot));

  cell.querySelector('.plan-slot-remove').addEventListener('click', async (e) => {
    e.preventDefault();
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const res = await apiRequest(
        `/api/meal-plan?date=${encodeURIComponent(date)}&slot=${encodeURIComponent(slot)}`,
        { method: 'DELETE' }
      );
      if (res.error) {
        showTransientError(res.error);
        btn.disabled = false;
        return;
      }
      entries = entries.filter(en => !(en.date === date && en.slot === slot));
      renderWeek();
    } catch (err) {
      showTransientError('Could not update your plan.');
      btn.disabled = false;
    }
  });

  return cell;
}

function showTransientError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove('hidden');
  setTimeout(() => errorEl.classList.add('hidden'), 3000);
}

// ── Hafta yükleme ────────────────────────────────────────
async function loadWeek(mondayISO) {
  currentWeek = mondayISO;
  weekLabel.textContent = formatWeekLabel(mondayISO);
  thisWeekBtn.classList.toggle('hidden', mondayISO === toISO(mondayOf(new Date())));

  gridEl.classList.add('hidden');
  loading.classList.remove('hidden');

  try {
    const data = await apiRequest(
      `/api/meal-plan?week=${encodeURIComponent(mondayISO)}&include_details=true`
    );
    loading.classList.add('hidden');

    if (data.error) {
      errorEl.textContent = data.error;
      errorEl.classList.remove('hidden');
      return;
    }

    errorEl.classList.add('hidden');
    entries = data.entries || [];
    renderWeek();
  } catch (err) {
    loading.classList.add('hidden');
    errorEl.textContent = 'Could not load your plan.';
    errorEl.classList.remove('hidden');
  }
}

prevWeekBtn.addEventListener('click', () => loadWeek(addDays(currentWeek, -7)));
nextWeekBtn.addEventListener('click', () => loadWeek(addDays(currentWeek, 7)));
thisWeekBtn.addEventListener('click', () => loadWeek(toISO(mondayOf(new Date()))));

// ── Tarif seçici ─────────────────────────────────────────
async function openPicker(date, slot) {
  pickerTarget = { date, slot };
  pickerTitle.textContent = `${SLOT_LABELS[slot] || slot} · ${formatDayLabel(date)}`;
  pickerError.classList.add('hidden');
  pickerModal.classList.remove('hidden');

  // Favoriler LAZY yükleniyor: her sayfa açılışında değil, seçici ilk kez
  // açıldığında. Sonraki açılışlar önbellekten (kullanıcı tarif eklemediği
  // sürece liste değişmiyor).
  if (savedRecipes === null) {
    pickerList.innerHTML = '<p class="picker-empty">Loading…</p>';
    try {
      const data = await apiRequest('/api/favorites?include_details=true');
      savedRecipes = (data.favorites || []).map(f => f.recipe).filter(Boolean);
    } catch (err) {
      pickerList.innerHTML = '<p class="picker-empty">Could not load your saved recipes.</p>';
      return;
    }
  }

  renderPickerList();
}

function formatDayLabel(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    weekday: 'long', month: 'short', day: 'numeric',
  });
}

function renderPickerList() {
  pickerList.innerHTML = '';

  if (savedRecipes.length === 0) {
    pickerList.innerHTML = `
      <p class="picker-empty">
        You haven't saved any recipes yet. Search for something you like and tap
        the heart — saved recipes show up here.
      </p>`;
    return;
  }

  savedRecipes.forEach(recipe => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'plan-picker-row';
    row.innerHTML = `
      <span class="plan-picker-name">${escapeHtml(recipe.name)}</span>
      <span class="plan-picker-meta">
        ${recipe.category ? escapeHtml(recipe.category) : ''}
        ${recipe.total_time_min > 0 ? ` · ${recipe.total_time_min} min` : ''}
      </span>
    `;
    row.addEventListener('click', () => choose(recipe));
    pickerList.appendChild(row);
  });
}

async function choose(recipe) {
  const { date, slot } = pickerTarget;
  pickerList.querySelectorAll('button').forEach(b => (b.disabled = true));

  try {
    const res = await apiRequest('/api/meal-plan', {
      method: 'POST',
      body: JSON.stringify({ date, slot, recipe_id: recipe.id }),
    });

    if (res.error) {
      pickerError.textContent = res.error;
      pickerError.classList.remove('hidden');
      pickerList.querySelectorAll('button').forEach(b => (b.disabled = false));
      return;
    }

    // Backend haftanın tamamını dönüyor ama kart bilgileri olmadan; elimizdeki
    // tarifi ekleyip yeniden çizmek ikinci bir isteği gereksiz kılıyor.
    entries = entries.filter(e => !(e.date === date && e.slot === slot));
    entries.push({ date, slot, recipe_id: recipe.id, recipe });
    entries.sort((a, b) =>
      a.date === b.date ? SLOTS.indexOf(a.slot) - SLOTS.indexOf(b.slot)
                        : a.date.localeCompare(b.date)
    );

    closePicker();
    renderWeek();
  } catch (err) {
    pickerError.textContent = 'Could not update your plan.';
    pickerError.classList.remove('hidden');
    pickerList.querySelectorAll('button').forEach(b => (b.disabled = false));
  }
}

function closePicker() {
  pickerModal.classList.add('hidden');
  pickerTarget = null;
}

pickerCancel.addEventListener('click', closePicker);
pickerModal.addEventListener('click', (e) => {
  if (e.target === pickerModal) closePicker();
});

// ── Haftayı temizleme ────────────────────────────────────
clearWeekBtn.addEventListener('click', () => {
  const n = entries.length;
  clearCount.textContent = `${n} ${n === 1 ? 'meal' : 'meals'}`;
  clearModal.classList.remove('hidden');
});

clearCancel.addEventListener('click', () => clearModal.classList.add('hidden'));
clearModal.addEventListener('click', (e) => {
  if (e.target === clearModal) clearModal.classList.add('hidden');
});

clearConfirm.addEventListener('click', async () => {
  clearConfirm.disabled = true;
  try {
    await apiRequest(`/api/meal-plan/week?week=${encodeURIComponent(currentWeek)}`, {
      method: 'DELETE',
    });
    clearModal.classList.add('hidden');
    entries = [];
    renderWeek();
  } catch (err) {
    clearModal.classList.add('hidden');
    showTransientError('Could not clear the week.');
  } finally {
    clearConfirm.disabled = false;
  }
});

// ── Yükleme ──────────────────────────────────────────────
(async () => {
  // URL'de hafta varsa onu aç (recipe.html'den gelen link kullanabilir).
  // `T00:00:00` şart: `new Date('2026-07-27')` tarihi UTC gece yarısı sayar ve
  // negatif ofsetli saat dilimlerinde günü bir geri kaydırırdı.
  const requested = new URLSearchParams(window.location.search).get('week');
  let start = mondayOf(new Date());
  if (requested) {
    const parsed = new Date(`${requested}T00:00:00`);
    if (!isNaN(parsed.getTime())) start = mondayOf(parsed);   // çöp parametre → bu hafta
  }
  await loadWeek(toISO(start));
})();
