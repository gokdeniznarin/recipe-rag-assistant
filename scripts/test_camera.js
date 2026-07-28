/**
 * frontend/js/camera.js davranış testleri (sahte DOM, tarayıcı gerekmiyor).
 *
 *   node scripts/test_camera.js
 *
 * NEDEN KALICI BİR TESTİ VAR: camera.js iki sayfa tarafından paylaşılıyor
 * (search.html ve nutrition.html) ve içinde bir durum makinesi var — aç, çek,
 * yükle, sıfırla. Şimdiye kadar burada İKİ gerçek hata çıktı:
 *   1. mode tab'ı silinmiş bir değişkene bakıyordu → ReferenceError
 *   2. "Use a different photo" yüklenen bir fotoğraftan sonra KAMERAYI açıyordu
 * İkisi de sessiz: sayfa normal görünüyor, kullanıcı beklemediği bir şey
 * yaşıyor. Sözdizimi kontrolü bunları yakalayamaz, davranış testi yakalar.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failures = 0;
const check = (label, cond) => {
  console.log((cond ? '  ok    ' : '  FAIL  ') + label);
  if (!cond) failures++;
};

// ── Sahte DOM ────────────────────────────────────────────
function element() {
  const classes = new Set();
  const handlers = {};
  return {
    _classes: classes, _handlers: handlers,
    classList: {
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      contains: c => classes.has(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    addEventListener: (event, handler) => { handlers[event] = handler; },
    getAttribute: () => null,
    setAttribute: () => {},
    width: 0, height: 0, videoWidth: 640, videoHeight: 480,
    getContext: () => ({ drawImage() {} }),
    toDataURL: () => 'data:image/jpeg;base64,FAKE',
  };
}

function build({ cameraFails = false } = {}) {
  const stopped = [];
  const sandbox = {
    Logger: { get: () => ({ warn() {}, error() {}, debug() {}, info() {} }) },
    navigator: {
      mediaDevices: {
        getUserMedia: async () => {
          if (cameraFails) throw new Error('permission denied');
          return { getTracks: () => [{ stop() { stopped.push(1); } }] };
        },
      },
    },
    window: { addEventListener() {} },
    // Çalışan sahteler: böylece gerçek loadFile yolu test ediliyor, üretim
    // koduna test için bir kanca açmak gerekmiyor.
    FileReader: function () {
      const self = this;
      self.readAsDataURL = function () {
        self.result = 'data:image/jpeg;base64,SRC';
        if (self.onload) self.onload();
      };
    },
    Image: function () {
      const self = this;
      self.width = 2000;          // MAX_EDGE (1280) üstünde → küçültülmeli
      self.height = 1000;
      Object.defineProperty(self, 'src', {
        set() { if (self.onload) self.onload(); },
      });
    },
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, '..', 'frontend', 'js', 'camera.js'), 'utf8') +
      '\nglobalThis.Camera = Camera;',
    sandbox
  );

  const el = {
    preview: element(), canvas: element(),
    startBtn: element(), captureBtn: element(), retakeBtn: element(),
  };
  const events = { captured: null, resets: 0, error: null };
  const camera = sandbox.Camera.attach({
    ...el,
    onCapture: d => { events.captured = d; },
    onReset: () => { events.resets++; },
    onError: m => { events.error = m; },
  });
  return { camera, el, events, stopped };
}

// ── Kameradan çekme ──────────────────────────────────────
(async () => {
  {
    const { camera, el, events, stopped } = build();
    await el.startBtn._handlers.click();
    check('opening hides start and shows capture',
      el.startBtn._classes.has('hidden') && !el.captureBtn._classes.has('hidden'));

    el.captureBtn._handlers.click();
    check('capture reports the photo', events.captured === 'data:image/jpeg;base64,FAKE');
    check('capture stores the photo', camera.getPhoto() === 'data:image/jpeg;base64,FAKE');
    check('capture shows the canvas and hides the preview',
      !el.canvas._classes.has('hidden') && el.preview._classes.has('hidden'));
    check('capture releases the camera stream', stopped.length === 1);
    check('canvas takes the video dimensions', el.canvas.width === 640 && el.canvas.height === 480);

    await el.retakeBtn._handlers.click();
    check('retake notifies the caller', events.resets === 1);
    check('retake clears the photo', camera.getPhoto() === null);
    check('retake reopens the camera', !el.captureBtn._classes.has('hidden'));
  }

  // ── Dosyadan yükleme (REGRESYON) ───────────────────────
  {
    const { camera, el, events } = build();
    camera.loadFile({ type: 'image/jpeg' });

    check('uploaded photo is stored', camera.getPhoto() === 'data:image/jpeg;base64,FAKE');
    check('uploaded photo hides start button', el.startBtn._classes.has('hidden'));
    check('uploaded photo shows the canvas', !el.canvas._classes.has('hidden'));
    // 2000x1000 → uzun kenar 1280'e iniyor, oran korunuyor
    check('a large upload is scaled down',
      el.canvas.width === 1280 && el.canvas.height === 640);

    await el.retakeBtn._handlers.click();
    check('REGRESSION: reset after an upload does NOT open the camera',
      el.captureBtn._classes.has('hidden'));
    check('reset after an upload restores the start button',
      !el.startBtn._classes.has('hidden'));
    check('reset after an upload clears the photo', camera.getPhoto() === null);
    check('reset after an upload notifies the caller', events.resets === 1);
  }

  // ── Hata yolları ───────────────────────────────────────
  {
    const { el, events } = build({ cameraFails: true });
    await el.startBtn._handlers.click();
    check('denied camera reports an error', /camera/i.test(events.error || ''));
    check('denied camera keeps the start button', !el.startBtn._classes.has('hidden'));
  }
  {
    const { camera, events } = build();
    camera.loadFile({ type: 'application/pdf' });
    check('a non-image file is rejected', /not an image/i.test(events.error || ''));
    camera.stop(); camera.stop();
    check('stop is safe to call twice', true);
  }

  console.log(failures === 0 ? '\ncamera checks passed' : `\n${failures} problem(s)`);
  process.exit(failures === 0 ? 0 : 1);
})();
