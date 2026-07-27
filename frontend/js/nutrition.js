// Besin değeri sayfası — "bunda ne var" sorusu.
//
// AYRI SAYFA (arama sayfasının bir sekmesi değil): kullanıcı buraya tarif
// aramak için gelmiyor. Kamera akışı ortak Camera modülünden geliyor, o yüzden
// ayrılma bir kopyalama bedeli getirmedi.
const nutritionLog = Logger.get('nutrition');

const preview     = document.getElementById('camera-preview');
const canvas      = document.getElementById('camera-canvas');
const startBtn    = document.getElementById('start-camera-btn');
const captureBtn  = document.getElementById('capture-btn');
const retakeBtn   = document.getElementById('retake-btn');
const uploadInput = document.getElementById('photo-upload');

const analyzeRow    = document.getElementById('analyze-row');
const analyzeBtn    = document.getElementById('analyze-btn');
const analyzeStatus = document.getElementById('analyze-status');

const loading      = document.getElementById('loading');
const panel        = document.getElementById('nutrition-panel');
const emptyState   = document.getElementById('nutrition-empty');
const errorBox     = document.getElementById('nutrition-error');
const sourceLabel  = document.getElementById('nutrition-source');
const totalsBox    = document.getElementById('nutrition-totals');
const itemsBox     = document.getElementById('nutrition-items');
const attribution  = document.getElementById('nutrition-attribution');

// ── Yardımcılar ──────────────────────────────────────────
function showError(msg) {
  errorBox.textContent = msg;
  errorBox.classList.remove('hidden');
}

function clearResult() {
  panel.classList.add('hidden');
  errorBox.classList.add('hidden');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ── Kamera / yükleme ─────────────────────────────────────
const camera = Camera.attach({
  preview, canvas, startBtn, captureBtn, retakeBtn,
  onCapture: () => {
    analyzeRow.classList.remove('hidden');
    analyzeStatus.textContent = '';
    analyzeBtn.disabled = false;
    emptyState.classList.add('hidden');
    clearResult();               // önceki fotoğrafın sonucu kalmasın
  },
  onReset: () => {
    analyzeRow.classList.add('hidden');
    analyzeStatus.textContent = '';
    emptyState.classList.remove('hidden');
    clearResult();
  },
  onError: showError,
});

uploadInput.addEventListener('change', (e) => {
  errorBox.classList.add('hidden');
  camera.loadFile(e.target.files[0]);
  // Aynı dosya arka arkaya seçilebilsin diye değeri sıfırla — yoksa `change`
  // ikinci seferde hiç tetiklenmiyor.
  e.target.value = '';
});

// ── Sonuç render ─────────────────────────────────────────
const MACRO_FIELDS = [
  { key: 'calories',  label: 'Calories', unit: 'kcal' },
  { key: 'protein_g', label: 'Protein',  unit: 'g' },
  { key: 'carbs_g',   label: 'Carbs',    unit: 'g' },
  { key: 'fat_g',     label: 'Fat',      unit: 'g' },
];

// Kaynağı DÜRÜSTÇE söylüyoruz: aranmış veri ile üretilmiş tahmin aynı şey değil.
// Bir tabakta ikisi karışabiliyor (bazı öğeler bulunur, bazıları bulunmaz).
const SOURCE_LABELS = {
  fatsecret: 'Looked up in a nutrition database',
  mixed:     'Partly looked up, partly AI-estimated',
  estimate:  'AI estimate',
};

function macroValue(item, field) {
  const raw = Number(item[field.key]);
  const value = Number.isFinite(raw) ? raw : 0;
  // Kalori tam sayı okunur, makrolar ondalıklı anlamlı.
  return field.key === 'calories' ? String(Math.round(value)) : String(Math.round(value * 10) / 10);
}

const renderNutrition = Logger.timed(function (data) {
  sourceLabel.textContent = SOURCE_LABELS[data.source] || SOURCE_LABELS.estimate;

  totalsBox.innerHTML = MACRO_FIELDS.map(field => `
    <div class="nutrition-tile">
      <span class="nutrition-tile-value">${escapeHtml(macroValue(data.totals || {}, field))}<span class="nutrition-tile-unit">${field.unit}</span></span>
      <span class="nutrition-tile-label">${field.label}</span>
    </div>
  `).join('');

  itemsBox.innerHTML = (data.items || []).map(item => {
    // matched_food yalnızca veritabanında BAŞKA bir adla bulunduğunda gösteriliyor
    // — aynıysa tekrar etmek gürültü olurdu.
    const matched = item.matched_food && item.matched_food.toLowerCase() !== item.name.toLowerCase()
      ? `<span class="nutrition-matched">matched as “${escapeHtml(item.matched_food)}”</span>`
      : '';
    const estimated = item.source === 'estimate'
      ? '<span class="nutrition-estimated" title="Not found in the nutrition database; these numbers are an AI estimate">estimated</span>'
      : '';

    return `
      <div class="nutrition-item">
        <div class="nutrition-item-head">
          <span class="nutrition-item-name">${escapeHtml(item.name)}</span>
          <span class="nutrition-item-grams">≈ ${escapeHtml(String(item.grams))} g</span>
        </div>
        <div class="nutrition-item-macros">
          ${MACRO_FIELDS.map(f => `<span><b>${escapeHtml(macroValue(item, f))}</b>${f.unit === 'kcal' ? ' kcal' : ' g'} ${f.label.toLowerCase()}</span>`).join('')}
        </div>
        <div class="nutrition-item-meta">${matched}${estimated}</div>
      </div>
    `;
  }).join('');

  // ZORUNLU ATIF: FatSecret ücretsiz katmanı veriyi kullanan uygulamadan görünür
  // atıf istiyor. Backend bunu yalnızca gerçekten o veri kullanıldığında
  // dönüyor, o yüzden burada koşulsuz basılmıyor.
  if (data.attribution) {
    attribution.textContent = data.attribution;
    attribution.classList.remove('hidden');
  } else {
    attribution.classList.add('hidden');
  }

  panel.classList.remove('hidden');
}, 'renderNutrition', 'nutrition', 100);

// ── Analiz ───────────────────────────────────────────────
analyzeBtn.addEventListener('click', async () => {
  const photo = camera.getPhoto();
  if (!photo) return;

  analyzeBtn.disabled = true;
  analyzeStatus.textContent = 'Analyzing…';
  clearResult();
  emptyState.classList.add('hidden');
  loading.classList.remove('hidden');

  try {
    const data = await apiRequest('/api/nutrition/from-image', {
      method: 'POST',
      body: JSON.stringify({ image_base64: photo }),
    });

    if (data.error) {
      showError(data.error);
    } else {
      renderNutrition(data);
    }
  } catch (err) {
    nutritionLog.error(`Nutrition request failed: ${err.message || err}`);
    showError('Could not reach the server.');
  } finally {
    loading.classList.add('hidden');
    analyzeStatus.textContent = '';
    analyzeBtn.disabled = false;
  }
});
