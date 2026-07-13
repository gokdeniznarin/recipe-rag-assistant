// ── DOM elemanları ───────────────────────────────────────
const textPanel      = document.getElementById('text-panel');
const cameraPanel    = document.getElementById('camera-panel');
const textForm       = document.getElementById('text-form');
const textQuery      = document.getElementById('text-query');
const loading        = document.getElementById('loading');
const results        = document.getElementById('results');
const llmText        = document.getElementById('llm-text');
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

let cameraStream    = null;
let capturedBase64  = null;

// ── Mode tabs ────────────────────────────────────────────
document.querySelectorAll('.mode-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const mode = btn.dataset.mode;
    textPanel.classList.toggle('hidden', mode !== 'text');
    cameraPanel.classList.toggle('hidden', mode !== 'camera');

    // Kamera sekmesinden çıkıldığında stream'i kapat
    if (mode !== 'camera' && cameraStream) {
      stopCamera();
    }
  });
});

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

function renderResults(data) {
  llmText.textContent = data.answer || 'No suggestion available.';
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

    recipeList.appendChild(card);
  });

  results.classList.remove('hidden');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
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
});

retakeBtn.addEventListener('click', async () => {
  capturedBase64 = null;
  cameraCanvas.classList.add('hidden');
  cameraPreview.classList.remove('hidden');
  retakeBtn.classList.add('hidden');
  cameraForm.classList.add('hidden');
  detectedBox.classList.add('hidden');

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
      detectedList.textContent = data.detected_ingredients.join(', ');
      detectedBox.classList.remove('hidden');
      renderResults(data);
    }
  } catch (err) {
    showError('Could not reach the server.');
  } finally {
    hideLoading();
  }
});

// Sayfa kapatılırken kamerayı serbest bırak
window.addEventListener('beforeunload', stopCamera);


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
    console.warn('Speech recognition error:', event.error);
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
    console.warn(err);
  }
}

function stopListening() {
  isListening = false;
  micBtn.classList.remove('is-listening');
  micBtn.setAttribute('aria-label', 'Voice search');
}