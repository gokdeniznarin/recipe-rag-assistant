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

// Dolap elemanları
const pantryForm        = document.getElementById('pantry-form');
const pantryExtra       = document.getElementById('pantry-extra');
const pantrySummaryList = document.getElementById('pantry-summary-list');
const pantrySearchBtn   = document.getElementById('pantry-search-btn');

let detectedNames    = [];      // son fotoğrafta tanınanlar (dolaba eklemek için)
let pantryLoaded     = false;   // dolap özeti bir kez çekilsin (lazy)

// ── Kamera ───────────────────────────────────────────────
// getUserMedia / canvas / retake mantığı ortak Camera modülünde (js/camera.js) —
// besin değeri sayfası da aynısını kullanıyor, iki yere kopyalanmadı.
// Buradaki geri çağrılar yalnızca BU sayfaya özel olanı yapıyor.
const camera = Camera.attach({
  preview: cameraPreview,
  canvas: cameraCanvas,
  startBtn: startCameraBtn,
  captureBtn: captureBtn,
  retakeBtn: retakeBtn,
  onCapture: () => {
    cameraForm.classList.remove('hidden');
  },
  onReset: () => {
    cameraForm.classList.add('hidden');
    detectedBox.classList.add('hidden');
    detectedNames = [];

    // Retake ekrandaki fotoğraf türevlerini siliyor; KAYIT da aynısını yapmalı.
    // Yoksa eski fotoğrafın tarif sonuçları ve malzemeleri geri tuşunda yeniden
    // görünüyordu (saveSearchState merge yaptığı için alanlar hayatta kalıyor).
    // Yalnızca KAMERA kaydı temizleniyor: kullanıcı önce metin/dolap araması
    // yapıp sonra kameraya geçtiyse o sonuçlar korunmalı.
    const saved = readSearchState();
    if (saved && saved.mode === 'camera') {
      saveSearchState({ data: null, commentary: null, detected: null });
    }
  },
  onError: showError,
});

function stopCamera() {
  camera.stop();
}

// ── Mode tabs ────────────────────────────────────────────
document.querySelectorAll('.mode-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const mode = btn.dataset.mode;
    textPanel.classList.toggle('hidden', mode !== 'text');
    cameraPanel.classList.toggle('hidden', mode !== 'camera');
    pantryPanel.classList.toggle('hidden', mode !== 'pantry');

    // Kamera sekmesinden çıkıldığında stream'i kapat (Camera.stop kendisi
    // açık akış olup olmadığına bakıyor, ayrıca kontrol gerekmiyor)
    if (mode !== 'camera') stopCamera();

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
    card.href = `/recipes/${encodeURIComponent(recipe.id)}`;
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
      // commentary: null — yeni arama, öncekinin yorumunu taşımasın
      saveSearchState({ mode: 'text', query, data, commentary: null, detected: null });
      loadCommentary(query, data.results);   // bilerek await edilmiyor
    }
  } catch (err) {
    showError('Could not reach the server.');
  } finally {
    hideLoading();
  }
});

cameraForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const capturedBase64 = camera.getPhoto();
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
        data, commentary: null, detected: detectedNames,
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
        data, commentary: null, detected: null,
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
  if (!st || !st.data) return;

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

  renderResults(st.data);

  if (st.commentary) {
    llmSkeleton.classList.add('hidden');
    llmText.innerHTML = formatCommentary(st.commentary);
    llmBox.classList.remove('hidden');
  }

  searchLog.debug('Restored previous search from this tab');
})();
