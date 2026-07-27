const searchLog = Logger.get('search');

// ── DOM elemanları ───────────────────────────────────────
const textPanel      = document.getElementById('text-panel');
const cameraPanel    = document.getElementById('camera-panel');
const pantryPanel    = document.getElementById('pantry-panel');
const textForm       = document.getElementById('text-form');
const textQuery      = document.getElementById('text-query');
const loading        = document.getElementById('loading');
const results        = document.getElementById('results');
const llmText        = document.getElementById('llm-text');
const llmBox         = document.getElementById('llm-box');
const llmSkeleton    = document.getElementById('llm-skeleton');
const recipeList     = document.getElementById('recipe-list');
const resultsCount   = document.getElementById('results-count');
const searchError    = document.getElementById('search-error');

// Kamera elemanları
const startCameraBtn = document.getElementById('start-camera-btn');
const captureBtn     = document.getElementById('capture-btn');
const retakeBtn      = document.getElementById('retake-btn');
const cameraPreview  = document.getElementById('camera-preview');
const cameraCanvas   = document.getElementById('camera-canvas');
const cameraForm     = document.getElementById('camera-form');
const cameraExtra    = document.getElementById('camera-extra');
const detectedBox    = document.getElementById('detected-ingredients');
const detectedList   = document.getElementById('detected-list');
const addDetectedBtn = document.getElementById('add-detected-btn');
const addDetectedStatus = document.getElementById('add-detected-status');

// Besin değeri (kamera akışının ikinci okuması)
const cameraActions      = document.getElementById('camera-actions');
const nutritionBtn       = document.getElementById('nutrition-btn');
const nutritionStatus    = document.getElementById('nutrition-status');
const nutritionPanel     = document.getElementById('nutrition-panel');
const nutritionSource    = document.getElementById('nutrition-source');
const nutritionTotals    = document.getElementById('nutrition-totals');
const nutritionItems     = document.getElementById('nutrition-items');
const nutritionAttribution = document.getElementById('nutrition-attribution');

// Dolap elemanları
const pantryForm        = document.getElementById('pantry-form');
const pantryExtra       = document.getElementById('pantry-extra');
const pantrySummaryList = document.getElementById('pantry-summary-list');
const pantrySearchBtn   = document.getElementById('pantry-search-btn');

let cameraStream     = null;
let capturedBase64   = null;
let detectedNames    = [];      // son fotoğrafta tanınanlar (dolaba eklemek için)
let pantryLoaded     = false;   // dolap özeti bir kez çekilsin (lazy)

// ── Mode tabs ────────────────────────────────────────────
document.querySelectorAll('.mode-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const mode = btn.dataset.mode;
    textPanel.classList.toggle('hidden', mode !== 'text');
    cameraPanel.classList.toggle('hidden', mode !== 'camera');
    pantryPanel.classList.toggle('hidden', mode !== 'pantry');

    // Kamera sekmesinden çıkıldığında stream'i kapat
    if (mode !== 'camera' && cameraStream) {
      stopCamera();
    }

    // Dolap özetini yalnızca sekmeye ilk girişte çek (lazy — her sayfa
    // yüklemesinde gereksiz bir Firestore okuması yapmayalım)
    if (mode === 'pantry' && !pantryLoaded) loadPantrySummary();
  });
});

// pantry.html "Find recipes" ile buraya yönlendiriyor: search.html?mode=pantry
(function applyModeFromUrl() {
  const mode = new URLSearchParams(window.location.search).get('mode');
  if (!mode) return;
  const tab = document.querySelector(`.mode-tab[data-mode="${mode}"]`);
  if (tab) tab.click();
})();

// ── Yardımcı fonksiyonlar ────────────────────────────────
function showLoading() {
  loading.classList.remove('hidden');
  results.classList.add('hidden');
  // Besin paneli de gizleniyor: tarif sonuçları ve besin değeri aynı fotoğrafın
  // İKİ ayrı okuması, ikisi birden ekranda kalırsa hangisinin güncel olduğu
  // belirsizleşir. Merkezi yer burası — her arama yolu buradan geçiyor.
  nutritionPanel.classList.add('hidden');
  searchError.classList.add('hidden');
}

function hideLoading() {
  loading.classList.add('hidden');
}

function showError(msg) {
  searchError.textContent = msg;
  searchError.classList.remove('hidden');
}

// ── Arama durumunu koru (MPA geri tuşu) ──────────────────
// Bu bir MPA: tarife tıklayıp geri dönmek search.html'i SIFIRDAN yüklüyor,
// yani sonuçlar uçuyordu. sessionStorage sekme ömrü boyunca yaşıyor ve sekme
// kapanınca temizleniyor — arama sonuçları gibi geçici veri için doğru yer
// (localStorage kalıcı olurdu, gereksiz).
//
// try/catch ŞART: Safari gizli modda / site verileri engellendiğinde
// sessionStorage OKURKEN BİLE SecurityError fırlatıyor. Faz 13b'de tam bu
// yüzden logger.js uygulamayı düşürmüştü; aynı hatayı tekrarlamıyoruz.
const SEARCH_STATE_KEY = 'search_state_v1';

function readSearchState() {
  try {
    const raw = sessionStorage.getItem(SEARCH_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveSearchState(patch) {
  try {
    sessionStorage.setItem(
      SEARCH_STATE_KEY,
      JSON.stringify({
        ...(readSearchState() || {}),
        ...patch,
        // Kaydın SAHİBİ. sessionStorage sekmeye özel ama kullanıcıya özel
        // değil — bu alan olmadan aynı sekmede hesap değiştirildiğinde
        // önceki kullanıcının aramaları yeni kullanıcıya görünüyordu.
        owner: currentUserEmail(),
      })
    );
  } catch {
    // Depolama yoksa özellik sessizce devre dışı kalır — arama yine çalışır.
  }
}

function currentUserEmail() {
  try {
    return (auth.currentUser && auth.currentUser.email) || null;
  } catch {
    return null;
  }
}

// AI yorumunu arama sonuçlarından SONRA, ayrı bir istekle çeker.
// Sonuçlar zaten ekranda olduğu için bu isteğin süresi kullanıcıyı bekletmiyor;
// gelmezse (kota dolmuş olabilir) kutu hiç görünmez.
// Yorum isteği yavaş (Gemini). Kullanıcı arka arkaya arama yaparsa öncekinin
// cevabı sonrakinin üstüne düşebilir; her aramaya bir sıra numarası verip
// yalnızca en son aramanın cevabını ekrana yazıyoruz.
let commentarySeq = 0;

async function loadCommentary(query, recipes) {
  // Sonuç yoksa yorumlanacak bir şey de yok. (Non-food sorgular buraya hiç
  // ulaşmıyor: backend is_food_request ile aramadan önce reddediyor, o durumda
  // data.error dönüyor ve bu fonksiyon zaten çağrılmıyor.)
  if (recipes.length === 0) return;

  const seq = ++commentarySeq;

  llmText.textContent = '';
  llmSkeleton.classList.remove('hidden');
  llmBox.classList.remove('hidden');

  try {
    const data = await apiRequest('/api/recipes/commentary', {
      method: 'POST',
      body: JSON.stringify({
        query,
        recipe_ids: recipes.map(r => r.id),
      }),
    });

    if (seq !== commentarySeq) return;   // daha yeni bir arama var, bunu yoksay

    if (data.answer) {
      llmSkeleton.classList.add('hidden');
      llmText.innerHTML = formatCommentary(data.answer);
      // Geri dönüldüğünde yorum da dursun — yeniden istemek bir Gemini
      // çağrısı daha harcardı (kota model başına günde 20).
      saveSearchState({ commentary: data.answer });
    } else {
      llmBox.classList.add('hidden');   // yorum yok — kutuyu hiç gösterme
    }
  } catch {
    if (seq === commentarySeq) llmBox.classList.add('hidden');
  }
}

// Kartların DOM'a çizilmesi. Logger.timed ile sarmalandı — backend'in ASLA
// göremediği bir maliyet: yanıt geldikten sonra kullanıcı sonuçları ancak
// render bitince görüyor. Backend'de aynı işi @timed decorator'ı yapıyor;
// buradaki onun JS karşılığı (higher-order function).
// Eşik 100 ms: 5 kart çizmek milisaniyeler sürmeli, aşıyorsa bir sorun var.
const renderResults = Logger.timed(function (data) {
  llmBox.classList.add('hidden');   // önceki aramanın yorumu kalmasın
  recipeList.innerHTML = '';
  resultsCount.textContent = `${data.results.length} matches`;

  data.results.forEach(recipe => {
    const card = document.createElement('a');
    card.href = `recipe.html?id=${encodeURIComponent(recipe.id)}`;
    card.className = 'recipe-card';

    // Aktif diyet tag'lerini önem sırasına göre sırala:
    // vegan/vegetarian/pescatarian önce (yemek türünü belirliyor),
    // sonra allergen-free (gluten/dairy/nut) filtreleri.
    const tagOrder = ['vegan', 'vegetarian', 'pescatarian', 'gluten_free', 'dairy_free', 'nut_free'];
    const activeTags = tagOrder
      .filter(k => recipe.diet_tags[k])
      .map(k => k.replace('_', '-'));

    const tagsHtml = activeTags
      .map(t => `<span class="tag">${t}</span>`)
      .join('');

    // Eşleşme rozeti: "bu tarif dolabındaki 4/6 malzemeyi kullanıyor".
    // Backend bu alanı YALNIZCA /api/recipes/from-pantry yanıtına ekliyor
    // (metin/kamera aramasına eklemek her aramaya bir Firestore okuması
    // bindirirdi), o yüzden diğer modlarda sessizce yok sayılıyor.
    // title ile hangi malzemelerin eşleştiği de gösteriliyor — sayı tek başına
    // "hangileri?" sorusunu doğurur.
    const pm = recipe.pantry_match;
    const badgeHtml = pm && pm.count > 0
      ? `<span class="pantry-badge" title="Uses from your pantry: ${escapeHtml(pm.matched.join(', '))}">${pm.count}/${pm.pantry_total} from pantry</span>`
      : '';

    card.innerHTML = `
      ${recipeThumbHtml(recipe)}
      <div class="recipe-card-body">
        <h3 class="recipe-name">${escapeHtml(recipe.name)}</h3>
        <p class="recipe-meta">
          ${recipe.category ? escapeHtml(recipe.category) : ''}
          ${recipe.total_time_min > 0 ? ` · ${recipe.total_time_min} min` : ''}
          ${recipe.calories > 0 ? ` · ${Math.round(recipe.calories)} cal` : ''}
        </p>
        <div class="recipe-tags">${badgeHtml}${tagsHtml}</div>
      </div>
      <span class="recipe-arrow">→</span>
    `;

    recipeList.appendChild(card);
  });

  results.classList.remove('hidden');
}, 'renderResults', 'search', 100);

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// LLM cevabındaki hafif markdown'ı HTML'e çevirir. SIRA GÜVENLİK İÇİN ÖNEMLİ:
// önce metnin tamamı escape ediliyor (LLM çıktısı sayfaya HTML olarak giriyor,
// escape edilmezse XSS açığı olur), SONRA yıldız/satır dönüşümü uygulanıyor.
// Böylece enjekte edilen tek HTML bizim ürettiğimiz <strong>/<br> — yakalanan
// grup zaten escape edilmiş olduğu için ham etiket taşıyamaz.
//   **kalın** → <strong>   ·   satır sonu → <br>
function formatCommentary(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

// ── Metin araması ────────────────────────────────────────
textForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const query = textQuery.value.trim();
  if (!query) return;

  showLoading();
  try {
    const data = await apiRequest('/api/recipes/search', {
      method: 'POST',
      body: JSON.stringify({ query, n_results: 5 }),
    });

    if (data.error) {
      showError(data.error);
    } else {
      renderResults(data);
      // commentary/nutrition: null — yeni arama, öncekinin çıktısını taşımasın
      saveSearchState({ mode: 'text', query, data, commentary: null, detected: null, nutrition: null });
      loadCommentary(query, data.results);   // bilerek await edilmiyor
    }
  } catch (err) {
    showError('Could not reach the server.');
  } finally {
    hideLoading();
  }
});

// ── Kamera ───────────────────────────────────────────────
startCameraBtn.addEventListener('click', async () => {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }  // varsa arka kamera
    });
    cameraPreview.srcObject = cameraStream;
    startCameraBtn.classList.add('hidden');
    captureBtn.classList.remove('hidden');
  } catch (err) {
    showError('Could not access the camera. Check browser permissions.');
  }
});

captureBtn.addEventListener('click', () => {
  // Video'dan tek bir kareyi canvas'a çiz
  cameraCanvas.width  = cameraPreview.videoWidth;
  cameraCanvas.height = cameraPreview.videoHeight;
  const ctx = cameraCanvas.getContext('2d');
  ctx.drawImage(cameraPreview, 0, 0);

  // base64'e çevir
  capturedBase64 = cameraCanvas.toDataURL('image/jpeg', 0.85);

  // UI güncelle: preview'ı dondur, form'u göster
  stopCamera();
  cameraPreview.classList.add('hidden');
  cameraCanvas.classList.remove('hidden');

  captureBtn.classList.add('hidden');
  retakeBtn.classList.remove('hidden');
  cameraForm.classList.remove('hidden');
  cameraActions.classList.remove('hidden');
  nutritionStatus.textContent = '';      // önceki fotoğrafın mesajı kalmasın
  nutritionBtn.disabled = false;
});

retakeBtn.addEventListener('click', async () => {
  capturedBase64 = null;
  cameraCanvas.classList.add('hidden');
  cameraPreview.classList.remove('hidden');
  retakeBtn.classList.add('hidden');
  cameraForm.classList.add('hidden');
  cameraActions.classList.add('hidden');
  detectedBox.classList.add('hidden');
  nutritionPanel.classList.add('hidden');
  detectedNames = [];

  // Retake ekrandaki fotoğraf türevlerini siliyor; KAYIT da aynısını yapmalı.
  // Yoksa yeni fotoğrafın besin değeri, ESKİ fotoğrafın tarif sonuçlarının ve
  // malzemelerinin yanında geri yükleniyordu (saveSearchState merge yaptığı
  // için eski alanlar hayatta kalıyor) — geri tuşunda görünür bir tutarsızlık.
  // Yalnızca KAMERA kaydı temizleniyor: kullanıcı önce metin/dolap araması
  // yapıp sonra kameraya geçtiyse o sonuçlar korunmalı.
  const saved = readSearchState();
  if (saved && saved.mode === 'camera') {
    saveSearchState({ data: null, commentary: null, detected: null, nutrition: null });
  }

  // Kamerayı tekrar aç
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }
    });
    cameraPreview.srcObject = cameraStream;
    captureBtn.classList.remove('hidden');
  } catch {
    startCameraBtn.classList.remove('hidden');
  }
});

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(t => t.stop());
    cameraStream = null;
  }
}

cameraForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!capturedBase64) return;

  showLoading();
  try {
    const data = await apiRequest('/api/recipes/from-image', {
      method: 'POST',
      body: JSON.stringify({
        image_base64: capturedBase64,
        additional_text: cameraExtra.value.trim(),
        n_results: 5,
      }),
    });

    if (data.error) {
      showError(data.error);
    } else {
      // Tanınan malzemeleri göster (asla input'a yazma!)
      detectedNames = data.detected_ingredients;
      detectedList.textContent = detectedNames.join(', ');
      addDetectedStatus.textContent = '';        // önceki fotoğrafın mesajı kalmasın
      addDetectedBtn.disabled = false;
      detectedBox.classList.remove('hidden');
      renderResults(data);
      // Fotoğrafın kendisi (base64) KAYDEDİLMİYOR — sessionStorage kotasını
      // doldurur. Tanınan malzemeler yeterli, kutu onlarla geri kuruluyor.
      saveSearchState({
        mode: 'camera', query: cameraExtra.value.trim(),
        data, commentary: null, detected: detectedNames, nutrition: null,
      });
      loadCommentary(data.combined_query, data.results);   // bilerek await edilmiyor
    }
  } catch (err) {
    showError('Could not reach the server.');
  } finally {
    hideLoading();
  }
});

// Sayfa kapatılırken kamerayı serbest bırak
window.addEventListener('beforeunload', stopCamera);


// ── Besin değeri (aynı fotoğraf, ikinci okuma) ───────────
// Tarif araması "bununla ne pişirebilirim", bu ise "bunda ne var" sorusunu
// cevaplıyor. Ayrı bir sayfa/çekim gerekmiyor: capturedBase64 zaten elimizde.
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
  results.classList.add('hidden');       // iki okuma aynı anda durmasın
  nutritionSource.textContent = SOURCE_LABELS[data.source] || SOURCE_LABELS.estimate;

  // Toplamlar
  nutritionTotals.innerHTML = MACRO_FIELDS.map(field => `
    <div class="nutrition-tile">
      <span class="nutrition-tile-value">${escapeHtml(macroValue(data.totals || {}, field))}<span class="nutrition-tile-unit">${field.unit}</span></span>
      <span class="nutrition-tile-label">${field.label}</span>
    </div>
  `).join('');

  // Öğe kırılımı
  nutritionItems.innerHTML = (data.items || []).map(item => {
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
    nutritionAttribution.textContent = data.attribution;
    nutritionAttribution.classList.remove('hidden');
  } else {
    nutritionAttribution.classList.add('hidden');
  }

  nutritionPanel.classList.remove('hidden');
}, 'renderNutrition', 'search', 100);

nutritionBtn.addEventListener('click', async () => {
  if (!capturedBase64) return;

  nutritionBtn.disabled = true;
  nutritionStatus.textContent = 'Analyzing…';
  showLoading();

  try {
    const data = await apiRequest('/api/nutrition/from-image', {
      method: 'POST',
      body: JSON.stringify({ image_base64: capturedBase64 }),
    });

    if (data.error) {
      showError(data.error);
      nutritionStatus.textContent = '';
    } else {
      renderNutrition(data);
      nutritionStatus.textContent = '';
      // Geri tuşunda korunsun (Faz 20 deseni). Fotoğrafın kendisi yine
      // SAKLANMIYOR — sessionStorage kotasını doldururdu.
      saveSearchState({ mode: 'camera', nutrition: data });
    }
  } catch (err) {
    showError('Could not reach the server.');
    nutritionStatus.textContent = '';
  } finally {
    hideLoading();
    nutritionBtn.disabled = false;
  }
});


// ── Dolaba ekleme (kameradan) ────────────────────────────
// Kamera özelliğini TEK SEFERLİK olmaktan çıkaran adım: tanınan malzemeler
// kaydedilince kullanıcı ertesi gün fotoğraf çekmeden arama yapabiliyor.
addDetectedBtn.addEventListener('click', async () => {
  if (detectedNames.length === 0) return;

  addDetectedBtn.disabled = true;
  addDetectedStatus.textContent = 'Saving…';

  try {
    const data = await apiRequest('/api/pantry', {
      method: 'POST',
      body: JSON.stringify({ names: detectedNames }),
    });

    if (data.error) {
      addDetectedStatus.textContent = data.error;
      addDetectedBtn.disabled = false;
      return;
    }

    const added   = (data.added || []).length;
    const skipped = (data.skipped || []).length;
    const invalid = (data.invalid || []).length;
    // Zaten dolapta olanlar hata değil, normal durum — sayıyı dürüstçe söyle.
    // invalid: Gemini'nin döndürdüğü kullanılamaz öğeler (boş/çok uzun); parti
    // düşmüyor, sadece o öğeler atlanıyor.
    const parts = [`${added} added to your pantry`];
    if (skipped) parts.push(`${skipped} already there`);
    if (invalid) parts.push(`${invalid} skipped`);
    addDetectedStatus.textContent = parts.join(' · ');

    pantryLoaded = false;   // özet bayatladı, dolap sekmesine girince tazelensin
  } catch (err) {
    addDetectedStatus.textContent = 'Could not save to your pantry.';
    addDetectedBtn.disabled = false;
  }
});


// ── Dolaptan arama ───────────────────────────────────────
async function loadPantrySummary() {
  try {
    const data = await apiRequest('/api/pantry');
    const items = data.items || [];
    pantryLoaded = true;

    if (items.length === 0) {
      pantrySummaryList.textContent = 'Empty — add ingredients first.';
      pantrySearchBtn.disabled = true;
    } else {
      pantrySummaryList.textContent = items.map(i => i.name).join(', ');
      pantrySearchBtn.disabled = false;
    }
  } catch (err) {
    pantrySummaryList.textContent = 'Could not load your pantry.';
    pantrySearchBtn.disabled = true;
  }
}

pantryForm.addEventListener('submit', async (e) => {
  e.preventDefault();

  showLoading();
  try {
    // Malzemeler gönderilmiyor — backend dolabı Firestore'dan kendisi okuyor
    // (istemcinin gönderdiği listeye göre arama kurulmuyor).
    const data = await apiRequest('/api/recipes/from-pantry', {
      method: 'POST',
      body: JSON.stringify({
        additional_text: pantryExtra.value.trim(),
        n_results: 5,
      }),
    });

    if (data.error) {
      showError(data.error);
    } else {
      renderResults(data);
      saveSearchState({
        mode: 'pantry', query: pantryExtra.value.trim(),
        data, commentary: null, detected: null, nutrition: null,
      });
      loadCommentary(data.combined_query, data.results);   // bilerek await edilmiyor
    }
  } catch (err) {
    showError('Could not reach the server.');
  } finally {
    hideLoading();
  }
});


// ── Web Speech API (voice search) ────────────────────────
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const micBtn = document.getElementById('mic-btn');
let recognition = null;
let isListening = false;

if (SpeechRecognition && micBtn) {
  recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onresult = (event) => {
  // Tüm parçaları birleştir (interim + final)
  let transcript = '';
  for (let i = 0; i < event.results.length; i++) {
    transcript += event.results[i][0].transcript;
  }
  textQuery.value = transcript.trim();
};

  recognition.onerror = (event) => {
    searchLog.warn(`Speech recognition error: ${event.error}`);
    stopListening();
  };

  recognition.onend = () => {
    stopListening();
  };

  micBtn.addEventListener('click', () => {
    if (isListening) {
      recognition.stop();
    } else {
      startListening();
    }
  });
} else if (micBtn) {
  // Tarayıcı desteklemiyorsa butonu gizle
  micBtn.classList.add('hidden');
}

function startListening() {
  try {
    recognition.start();
    isListening = true;
    micBtn.classList.add('is-listening');
    micBtn.setAttribute('aria-label', 'Stop listening');
  } catch (err) {
    searchLog.warn(`Could not start microphone: ${err.message || err}`);
  }
}

function stopListening() {
  isListening = false;
  micBtn.classList.remove('is-listening');
  micBtn.setAttribute('aria-label', 'Voice search');
}

// ── Önceki aramayı geri yükle (geri tuşu) ────────────────
// Dosyanın SONUNDA: renderResults / formatCommentary gibi fonksiyonların
// tanımlanmış olması gerekiyor.
//
// URL'de parametre varsa (ör. pantry.html'den gelen ?mode=pantry) geri yükleme
// YAPILMIYOR — o durumda kullanıcı yeni bir arama niyetiyle geliyor, eski
// sonuçları göstermek kafa karıştırır.
(async function restorePreviousSearch() {
  if (window.location.search) return;

  // authReady BEKLENMELİ: sayfa yüklenir yüklenmez `auth.currentUser` henüz
  // null olabilir (Firebase oturumu kalıcı depodan geri yüklüyor). Beklemezsek
  // sahiplik kontrolü tam da en gerekli olduğu anda — hesap değiştirildikten
  // sonraki ilk yüklemede — sessizce atlanırdı.
  try { await authReady; } catch { /* oturum belirlenemedi, yine de devam */ }

  const st = readSearchState();
  // Besin değeri TEK BAŞINA kaydedilmiş olabilir (kullanıcı fotoğraf çekip tarif
  // aramadan doğrudan besin değerine baktıysa), o yüzden `data` şart değil.
  if (!st || (!st.data && !st.nutrition)) return;

  // SAHİPLİK KONTROLÜ: kayıt başka bir kullanıcıya aitse geri yükleme ve sil.
  // Çıkışta zaten temizleniyor (api.js), ama çıkışın çalışmadığı yollar var:
  // 401 ile düşen oturum, sekmenin başka bir hesapla açılması, yarıda kalan
  // signOut. Ortak bilgisayarda başkasının aramasını göstermek kabul edilemez,
  // o yüzden iki katmanlı.
  const me = currentUserEmail();
  if (st.owner && me && st.owner !== me) {
    try { sessionStorage.removeItem(SEARCH_STATE_KEY); } catch {}
    searchLog.debug('Discarded search state saved by a different account');
    return;
  }

  // Mod sekmesi (tıklamak paneli de değiştiriyor, mantık tek yerde kalsın)
  if (st.mode && st.mode !== 'text') {
    const tab = document.querySelector(`.mode-tab[data-mode="${st.mode}"]`);
    if (tab) tab.click();
  }

  if (st.query) {
    if (st.mode === 'camera') cameraExtra.value = st.query;
    else if (st.mode === 'pantry') pantryExtra.value = st.query;
    else textQuery.value = st.query;
  }

  // Kamerada tanınan malzemeler (fotoğrafın kendisi saklanmıyor, o yüzden
  // "Add to pantry" butonu yeniden çekim isteyecek şekilde kapalı kalıyor)
  if (st.detected && st.detected.length) {
    detectedNames = st.detected;
    detectedList.textContent = detectedNames.join(', ');
    addDetectedBtn.disabled = false;
    detectedBox.classList.remove('hidden');
  }

  if (st.data) {
    renderResults(st.data);

    if (st.commentary) {
      llmSkeleton.classList.add('hidden');
      llmText.innerHTML = formatCommentary(st.commentary);
      llmBox.classList.remove('hidden');
    }
  }

  // renderNutrition sonuç panelini gizliyor, o yüzden tarif sonuçlarından SONRA:
  // ikisi de kaydedilmişse en son bakılan besin değeri ekranda kalır.
  if (st.nutrition) renderNutrition(st.nutrition);

  searchLog.debug('Restored previous search from this tab');
})();
