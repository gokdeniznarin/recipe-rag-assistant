/**
 * Örtü (`auth-pending`) teşhisi — geçici tanı aracı (Faz 29).
 *
 * NEDEN VAR: korumalı bir sayfada örtünün ne zaman ve KİM TARAFINDAN
 * kaldırıldığı yalnızca cihazda görülebiliyor. iPhone'da çakma sürüyor ama
 * Android'de sürmüyor; üç turdur sebebi TAHMİN ederek arıyorum ve üçü de
 * yanlış çıktı. Faz 26b'nin dersi tam buydu: cihazda yaşanan bir hatada
 * tarifi yorumlamak yerine ölçüm almak çok daha ucuz.
 *
 * NASIL ÇALIŞIYOR: `classList.remove('auth-pending')` sarmalanıyor ve çağıran
 * yığın izi kaydediliyor. Sayfa hemen yönlendiği için kayıt `sessionStorage`'a
 * yazılıyor ve VARIŞ sayfasında (index.html) ekrana basılıyor — telefonda
 * konsol okumak kablo istiyor.
 *
 * AÇMA/KAPAMA: `?debug=1` / `?debug=0` (Faz 26b'deki `debug_auth` bayrağının
 * aynısı — kurulu PWA'da adres çubuğu olmadığı için bayrak KALICI).
 *
 * ⚠️ GEÇİCİ. Sebep bulunup düzeltildiğinde bu dosya ve onu yükleyen satırlar
 * silinmeli.
 */
(function () {
  var KEY = 'auth_trace_v1';
  var FLAG = 'debug_auth';

  function debugOn() {
    try {
      var q = window.location.search;
      if (q.indexOf('debug=1') !== -1) { localStorage.setItem(FLAG, '1'); return true; }
      if (q.indexOf('debug=0') !== -1) { localStorage.removeItem(FLAG); return false; }
      return localStorage.getItem(FLAG) === '1';
    } catch (e) { return false; }
  }

  if (!debugOn()) return;

  var t0 = Date.now();
  var page = window.location.pathname.split('/').pop() || '/';
  var log = [];

  function add(what) {
    log.push((Date.now() - t0) + 'ms ' + what);
    try { sessionStorage.setItem(KEY, JSON.stringify({ page: page, log: log })); } catch (e) {}
  }

  add('load ' + page);

  // ── Örtüyü kaldıran KİM? ────────────────────────────────
  var root = document.documentElement;
  var realRemove = root.classList.remove.bind(root.classList);
  root.classList.remove = function () {
    for (var i = 0; i < arguments.length; i++) {
      if (arguments[i] === 'auth-pending') {
        var who = 'bilinmiyor';
        try {
          // Yığın izinin 2. satırı çağıranı gösteriyor.
          who = (new Error().stack || '').split('\n')[2] || '';
          who = who.trim().slice(0, 90);
        } catch (e) {}
        add('COVER REMOVED by ' + who);
      }
    }
    return realRemove.apply(null, arguments);
  };

  // ── Yönlendirmeler ──────────────────────────────────────
  var realReplace = window.location.replace.bind(window.location);
  try {
    window.location.replace = function (url) { add('replace -> ' + url); return realReplace(url); };
  } catch (e) { add('replace sarmalanamadi'); }

  // ── authReady ne zaman, hangi sonuçla ───────────────────
  // `authReady` bu dosyadan SONRA tanımlanıyor (firebase.js), o yüzden
  // bir sonraki tik'te bakılıyor.
  setTimeout(function () {
    if (typeof authReady === 'undefined') { add('authReady TANIMSIZ'); return; }
    authReady.then(function (u) {
      add('authReady -> ' + (u ? 'user ' + (u.email || '?') : 'null'));
    }, function (e) { add('authReady REDDEDILDI ' + e.message); });
  }, 0);

  // Örtü hâlâ duruyor mu, aralıklarla bak (sayfa görünür oldu mu).
  var ticks = 0;
  var iv = setInterval(function () {
    ticks++;
    if (!root.classList.contains('auth-pending')) {
      add('cover GONE (sayfa gorunur)');
      clearInterval(iv);
    }
    if (ticks > 40) clearInterval(iv);
  }, 250);

  // ── Varış sayfasında kaydı göster ───────────────────────
  window.addEventListener('DOMContentLoaded', function () {
    var raw;
    try { raw = sessionStorage.getItem(KEY); } catch (e) { return; }
    if (!raw) return;
    var prev;
    try { prev = JSON.parse(raw); } catch (e) { return; }
    // Kendi sayfamızın kaydını gösterme; ÖNCEKİ sayfanınkini göster.
    if (prev.page === page) return;

    var box = document.createElement('pre');
    box.style.cssText = 'position:fixed;left:6px;right:6px;bottom:6px;z-index:99999;'
      + 'background:#111;color:#0f0;font:11px/1.45 monospace;padding:8px;'
      + 'border-radius:6px;max-height:45vh;overflow:auto;white-space:pre-wrap;';
    box.textContent = '[' + prev.page + ']\n' + prev.log.join('\n');
    document.body.appendChild(box);
    try { sessionStorage.removeItem(KEY); } catch (e) {}
  });
})();
