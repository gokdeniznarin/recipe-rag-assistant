/**
 * Örtü (`auth-pending`) teşhisi — geçici tanı aracı (Faz 29).
 *
 * NEDEN VAR: iPhone'da korumalı sayfa örtüye rağmen bir an görünüyor,
 * Android'de görünmüyor. Sebebi üç turdur TAHMİN ederek aradım, üçü de yanlış
 * çıktı. Faz 26b'nin dersi buydu: cihazda yaşanan bir hatada tarifi
 * yorumlamak yerine ölçüm almak çok daha ucuz.
 *
 * ⚠️ EN ÖNEMLİ ÖLÇÜM `body-visibility`. İki ihtimali ayırıyor:
 *   - `hidden` iken sayfa görünüyorsa  → CSS uygulanıyor ama iOS onu
 *     çizmeye devam ediyor (WebKit tarafı)
 *   - `visible` ise                     → kural hiç uygulanmıyor; örtü sınıfı
 *     var ama işe yaramıyor
 * Bu ikisi tamamen farklı düzeltme gerektiriyor.
 *
 * Sayfa hemen yönlendiği için kayıt `sessionStorage`'a yazılıyor ve VARIŞ
 * sayfasında ekrana basılıyor — telefonda konsol okumak kablo istiyor.
 *
 * AÇMA/KAPAMA: `?debug=1` / `?debug=0` (Faz 26b'deki kalıcı bayrağın aynısı).
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

  // ⚠️ ÖNCEKİ SAYFANIN KAYDI EN BAŞTA OKUNUYOR. İlk sürümdeki hata buydu:
  // kendi kaydımızı yazınca öncekini eziyorduk ve kutuda hiçbir şey
  // görünmüyordu. Okuma, yazmadan ÖNCE olmak zorunda.
  var previous = null;
  try {
    var raw = sessionStorage.getItem(KEY);
    if (raw) previous = JSON.parse(raw);
    sessionStorage.removeItem(KEY);
  } catch (e) { /* yoksay */ }

  var t0 = Date.now();
  var page = window.location.pathname.split('/').pop() || '/';
  var log = [];
  var root = document.documentElement;

  function add(what) {
    log.push((Date.now() - t0) + 'ms ' + what);
    try { sessionStorage.setItem(KEY, JSON.stringify({ page: page, log: log })); } catch (e) {}
  }

  add('load ' + page);

  // ── Örtüyü kaldıran KİM? ────────────────────────────────
  var realRemove = root.classList.remove.bind(root.classList);
  root.classList.remove = function () {
    for (var i = 0; i < arguments.length; i++) {
      if (arguments[i] === 'auth-pending') {
        var who = '?';
        try { who = ((new Error().stack || '').split('\n')[2] || '').trim().slice(0, 80); } catch (e) {}
        add('COVER REMOVED <- ' + who);
      }
    }
    return realRemove.apply(null, arguments);
  };

  try {
    var realReplace = window.location.replace.bind(window.location);
    window.location.replace = function (u) { add('replace -> ' + u); return realReplace(u); };
  } catch (e) { add('replace sarmalanamadi'); }

  setTimeout(function () {
    if (typeof authReady === 'undefined') { add('authReady TANIMSIZ'); return; }
    authReady.then(
      function (u) { add('authReady -> ' + (u ? 'user' : 'null')); },
      function (e) { add('authReady RED ' + e.message); }
    );
  }, 0);

  // ── 🔑 Örtü GERÇEKTEN gizliyor mu ───────────────────────
  var ticks = 0;
  var iv = setInterval(function () {
    ticks++;
    var hasClass = root.classList.contains('auth-pending');
    var vis = '?';
    var sheets = '?';
    try { vis = document.body ? getComputedStyle(document.body).visibility : 'no-body'; } catch (e) {}
    try { sheets = document.styleSheets.length; } catch (e) {}
    if (ticks === 1 || ticks === 3 || ticks === 8) {
      add('t' + ticks + ' class=' + hasClass + ' body-visibility=' + vis + ' sheets=' + sheets);
    }
    if (!hasClass) { add('class GONE'); clearInterval(iv); }
    if (ticks > 40) clearInterval(iv);
  }, 250);

  // ── Varış sayfasında önceki kaydı göster ────────────────
  function render() {
    if (!previous || !document.body) return;
    var box = document.createElement('pre');
    box.style.cssText = 'position:fixed;left:4px;right:4px;top:4px;z-index:2147483647;'
      + 'background:#000;color:#0f0;font:11px/1.4 monospace;padding:8px;'
      + 'border-radius:6px;max-height:60vh;overflow:auto;white-space:pre-wrap;';
    box.textContent = '[' + previous.page + ']\n' + previous.log.join('\n');
    document.body.appendChild(box);
    previous = null;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render);
  } else {
    render();
  }
})();
