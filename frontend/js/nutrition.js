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
const barcodeBtn    = document.getElementById('barcode-btn');
const analyzeStatus = document.getElementById('analyze-status');

const loading      = document.getElementById('loading');
const panel        = document.getElementById('nutrition-panel');
const emptyState   = document.getElementById('nutrition-empty');
const errorBox     = document.getElementById('nutrition-error');
const sourceLabel  = document.getElementById('nutrition-source');
const totalsBox    = document.getElementById('nutrition-totals');
const itemsBox     = document.getElementById('nutrition-items');
const noteBox      = document.getElementById('nutrition-note');
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
    barcodeBtn.disabled = false;
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
// ⚠️ Backend'in döndürebileceği HER kaynak değerinin burada karşılığı olmalı:
// eksik anahtar aşağıda sessizce `estimate`'e düşüyor, yani ARANMIŞ veriyi
// "AI estimate" diye etiketlerdi — kullanıcıya söylenebilecek en yanlış şey.
const SOURCE_LABELS = {
  fatsecret:     'Looked up in a nutrition database',
  openfoodfacts: "From the product's own label",
  mixed:         'Partly looked up, partly AI-estimated',
  estimate:      'AI estimate',
};

function macroValue(item, field) {
  const raw = Number(item[field.key]);
  const value = Number.isFinite(raw) ? raw : 0;
  // Kalori tam sayı okunur, makrolar ondalıklı anlamlı.
  return field.key === 'calories' ? String(Math.round(value)) : String(Math.round(value * 10) / 10);
}

// Porsiyonun NEREDEN geldiğini söyleyen iki ayrı dürüst cümle. Fotoğraf
// yolundaki "kaba tahmin" uyarısını barkod sonucunun altına da koymak, elimizde
// olan en iyi veriyi (üreticinin kendi beyanı) haksız yere kötülemek olurdu;
// tersi ise fotoğraf tahminini olduğundan güvenilir göstermek.
const PORTION_NOTES = {
  photo:   'Portion size is estimated from the photo, so these numbers are rough. '
         + 'This is not medical or dietary advice.',
  barcode: "Values come from the product's own label for one serving. "
         + 'This is not medical or dietary advice.',
};

const renderNutrition = Logger.timed(function (data, fromBarcode) {
  sourceLabel.textContent = SOURCE_LABELS[data.source] || SOURCE_LABELS.estimate;
  noteBox.textContent = fromBarcode ? PORTION_NOTES.barcode : PORTION_NOTES.photo;

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
    // Yalnızca barkod yolunda dolu: "1 bar (45 g)" gibi üreticinin kendi
    // porsiyon tarifi. Gramdan çok daha okunur, ama gram da duruyor.
    const serving = item.serving_label
      ? `<span class="nutrition-matched">per serving: ${escapeHtml(item.serving_label)}</span>`
      : '';

    // Barkod sonucunda porsiyon TAHMİN DEĞİL, o yüzden "≈" işareti orada
    // yanıltıcı olurdu — üreticinin verdiği sayıyı belirsizmiş gibi gösterirdi.
    const grams = `${item.serving_label ? '' : '≈ '}${escapeHtml(String(item.grams))} g`;

    return `
      <div class="nutrition-item">
        <div class="nutrition-item-head">
          <span class="nutrition-item-name">${escapeHtml(item.name)}</span>
          <span class="nutrition-item-grams">${grams}</span>
        </div>
        <div class="nutrition-item-macros">
          ${MACRO_FIELDS.map(f => `<span><b>${escapeHtml(macroValue(item, f))}</b>${f.unit === 'kcal' ? ' kcal' : ' g'} ${f.label.toLowerCase()}</span>`).join('')}
        </div>
        <div class="nutrition-item-meta">${serving}${matched}${estimated}</div>
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

// ── Barkod okuma (istemci tarafı) ────────────────────────
// Tarayıcının YERLEŞİK okuyucusu. Chrome'da yalnızca Android, macOS ve
// ChromeOS'ta var; Windows'ta ve iOS Safari'de YOK.
//
// Buton yine de GİZLENMİYOR — mikrofondaki karardan (Faz 5) bilinçli olarak
// ayrılıyoruz. Orada destek yoksa özelliğin karşılığı hiç yoktu; burada
// çalışan bir yedek var: fotoğraf sunucuya gidiyor ve rakamları Gemini
// okuyor. Yani destek, özelliğin ÇALIŞIP çalışmamasını değil yalnızca kotaya
// mal olup olmamasını belirliyor.
//
// null dönmek "yerelde okuyamadım" demek ve her zaman güvenli: çağıran
// sunucu yoluna düşüyor.
async function readBarcodeLocally(canvasEl) {
  if (!('BarcodeDetector' in window)) return null;

  try {
    // getSupportedFormats() ŞART: API'nin var olması formatların desteklendiği
    // anlamına gelmiyor (platform boş liste döndürebiliyor) ve desteklenmeyen
    // bir formatla constructor hata fırlatıyor.
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = ['ean_13', 'ean_8', 'upc_a', 'upc_e'].filter(f => supported.includes(f));
    if (!formats.length) return null;

    const codes = await new window.BarcodeDetector({ formats }).detect(canvasEl);
    if (!codes.length) return null;

    nutritionLog.info(`Barcode read in the browser (${codes[0].format})`);
    return codes[0].rawValue;
  } catch (err) {
    // Bozuk kare, izin, platform tuhaflığı — hepsinde sunucu yedeği var.
    nutritionLog.warn(`Local barcode read failed, falling back to the server: ${err.message || err}`);
    return null;
  }
}

// ── Analiz ───────────────────────────────────────────────
// İki akış da (tabak fotoğrafı / barkod) aynı iskeleti paylaşıyor: butonları
// kilitle, eski sonucu temizle, yükleniyor göster, sonucu bas, her hâlükârda
// eski hâle dön. İki ayrı handler'a kopyalansaydı biri düzeltilip diğeri
// unutulurdu — projedeki "aynı kuralı iki yere yazma" ilkesi (Faz 15d/19).
async function runLookup({ endpoint, buildBody, status, fromBarcode }) {
  const photo = camera.getPhoto();
  if (!photo) return;

  analyzeBtn.disabled = true;
  barcodeBtn.disabled = true;
  analyzeStatus.textContent = status;
  clearResult();
  emptyState.classList.add('hidden');
  loading.classList.remove('hidden');

  try {
    const data = await apiRequest(endpoint, {
      method: 'POST',
      body: JSON.stringify(await buildBody(photo)),
    });

    if (data.error) {
      showError(data.error);
    } else {
      renderNutrition(data, fromBarcode);
    }
  } catch (err) {
    nutritionLog.error(`Nutrition request failed: ${err.message || err}`);
    showError('Could not reach the server.');
  } finally {
    loading.classList.add('hidden');
    analyzeStatus.textContent = '';
    analyzeBtn.disabled = false;
    barcodeBtn.disabled = false;
  }
}

analyzeBtn.addEventListener('click', () => runLookup({
  endpoint: '/api/nutrition/from-image',
  buildBody: photo => ({ image_base64: photo }),
  status: 'Analyzing…',
  fromBarcode: false,
}));

barcodeBtn.addEventListener('click', () => runLookup({
  endpoint: '/api/nutrition/from-barcode',
  // Numarayı tarayıcı çözebiliyorsa fotoğrafı hiç göndermiyoruz: gövde
  // ~8 KB yerine 13 karakter oluyor VE sunucuda bir Gemini kotası yanmıyor.
  buildBody: async (photo) => {
    const local = await readBarcodeLocally(canvas);
    return local ? { barcode: local } : { image_base64: photo };
  },
  status: 'Reading barcode…',
  fromBarcode: true,
}));
