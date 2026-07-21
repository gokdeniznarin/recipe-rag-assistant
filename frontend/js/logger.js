/**
 * Frontend logging + süre ölçümü — api/logger.py'nin tarayıcı tarafındaki eşi.
 *
 * NEDEN AYRI BİR DOSYA: backend'deki logger.py bir Python modülü, container'da
 * çalışıyor ve stdout'a yazıyor. Buradaki kod kullanıcının tarayıcısında
 * çalışıyor. İki farklı çalışma ortamı, hatta iki farklı makine — aynı modül
 * paylaşılamaz. Ortak olan tasarım: aynı satır biçimi, aynı seviyeler, aynı
 * "yavaşsa sarı" kuralı. Böylece iki tarafın logları yan yana okunabiliyor.
 *
 * NEDEN ÖLÇÜYORUZ: backend "search_recipes took 572 ms" diyor ama kullanıcının
 * beklediği süre bu değil — token alma, ağ gecikmesi, JSON parse ve render onun
 * dışında. Buradaki ölçüm kullanıcının gerçekten beklediği süreyi veriyor;
 * ikisi arasındaki fark ağ + istemci maliyeti oluyor.
 *
 * Seviye ayarı (tarayıcıda ortam değişkeni yok, localStorage kullanıyoruz):
 *     localStorage.setItem('log_level', 'debug')   // debug|info|warn|error|off
 *     localStorage.setItem('slow_ms', '500')       // "yavaş" eşiği
 * Sayfayı yenileyince geçerli olur.
 *
 * ⚠ DevTools'ta "Preserve log" AÇIK OLMALI. Bu bir MPA: giriş yapınca sayfa
 * search.html'e gidiyor ve konsol varsayılan olarak temizleniyor — yani
 * "sign in took ..." satırı basılıyor ama görülemiyor. Sunumdan önce
 * Console sekmesinde bu kutuyu işaretle.
 */

const Logger = (function () {
  const LEVELS = { debug: 10, info: 20, warn: 30, error: 40, off: 100 };

  // localStorage'a erişmek HER ZAMAN güvenli değil: Safari gizli modda ve site
  // verileri engellendiğinde okumak bile SecurityError fırlatıyor. Bu kod modül
  // kurulumunda çalıştığı için, korumasız bırakılırsa `Logger` hiç tanımlanmaz
  // ve onu kullanan api.js komple çöker — yani log sistemi uygulamayı düşürür.
  // Ayar okunamıyorsa varsayılana dönmek doğru davranış.
  function setting(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  const level = LEVELS[setting('log_level')] || LEVELS.info;
  // Backend'in varsayılanı 1000 ms; aynı eşiği kullanıyoruz ki iki taraftaki
  // "slow" işaretleri aynı anlama gelsin.
  const SLOW_MS = Number(setting('slow_ms')) || 1000;

  // console.log'un %c biçimlendiricisi: backend'deki ANSI renklerinin karşılığı.
  const STYLES = {
    debug: 'color:#00bcd4',
    info: 'color:#4caf50',
    warn: 'color:#ff9800;font-weight:bold',
    error: 'color:#f44336;font-weight:bold',
  };

  function stamp() {
    return new Date().toTimeString().slice(0, 8); // HH:MM:SS — backend ile aynı
  }

  // Backend "WARNING" yazıyor, JS tarafında seviye anahtarı "warn". İki tarafın
  // logları yan yana okunacağı için ekrana basılan ad da aynı olmalı.
  const DISPLAY = { debug: 'DEBUG', info: 'INFO', warn: 'WARNING', error: 'ERROR' };

  function write(lvl, scope, message, extra) {
    if (LEVELS[lvl] < level) return;
    // Genişlikler backend'deki ColorFormatter ile birebir aynı (8 ve 10) —
    // iki tarafın logları yan yana konduğunda sütunlar hizalansın diye.
    const line = `${stamp()} | ${DISPLAY[lvl].padEnd(8)} | ${String(scope).padEnd(10)} | ${message}`;
    // error/warn'ı console.error/warn'a veriyoruz: tarayıcının kendi filtreleri
    // (Console sekmesindeki Errors/Warnings) çalışsın diye.
    const sink = lvl === 'error' ? console.error : lvl === 'warn' ? console.warn : console.log;
    if (extra !== undefined) sink(`%c${line}`, STYLES[lvl], extra);
    else sink(`%c${line}`, STYLES[lvl]);
  }

  function make(scope) {
    return {
      debug: (m, e) => write('debug', scope, m, e),
      info: (m, e) => write('info', scope, m, e),
      warn: (m, e) => write('warn', scope, m, e),
      error: (m, e) => write('error', scope, m, e),
    };
  }

  function fmt(ms) {
    return ms < 1000 ? `${ms.toFixed(1)} ms` : `${(ms / 1000).toFixed(2)} s`;
  }

  /** Ölçülmüş bir süreyi seviye kuralına göre yazar (backend'deki log_duration). */
  function duration(scope, label, ms, slowMs) {
    const threshold = slowMs || SLOW_MS;
    if (ms >= threshold) make(scope).warn(`${label} took ${fmt(ms)} (slow, >${fmt(threshold)})`);
    else make(scope).info(`${label} took ${fmt(ms)}`);
  }

  /**
   * Backend'deki @timed decorator'ının JS karşılığı.
   *
   * Python'da `@timed` sözdizimi var; tarayıcıda çalışan sade JS'te decorator
   * sözdizimi yok (henüz standart değil ve derleyici ister). Ama FİKİR aynı:
   * fonksiyonu bir zarfla sarmalayıp ölçümü dışarıda tutmak — yani bu bir
   * higher-order function, decorator'ın sözdizimsel şekeri olmayan hâli.
   *
   *     const search = Logger.timed(doSearch, 'doSearch', 'search');
   *
   * Hem senkron hem Promise dönen fonksiyonlarla çalışır; hata yutulmaz,
   * ERROR olarak yazılıp yukarı fırlatılır (backend ile birebir aynı kural).
   */
  function timed(fn, label, scope, slowMs) {
    const name = label || fn.name || 'anonymous';
    return function (...args) {
      const start = performance.now();
      try {
        const result = fn.apply(this, args);
        if (result && typeof result.then === 'function') {
          return result.then(
            (value) => {
              duration(scope || 'timing', name, performance.now() - start, slowMs);
              return value;
            },
            (err) => {
              make(scope || 'timing').error(
                `${name} failed after ${fmt(performance.now() - start)}: ${err.message || err}`
              );
              throw err;
            }
          );
        }
        duration(scope || 'timing', name, performance.now() - start, slowMs);
        return result;
      } catch (err) {
        make(scope || 'timing').error(
          `${name} failed after ${fmt(performance.now() - start)}: ${err.message || err}`
        );
        throw err;
      }
    };
  }

  return { get: make, timed, duration, fmt, SLOW_MS };
})();

// Sayfanın kendi yüklenme süresi. Navigation Timing API tarayıcının kendi
// ölçümü — bizim kodumuz çalışmadan önce geçen süreyi de kapsıyor (DNS, TLS,
// HTML+CSS+JS indirme). Backend logunda bunun hiç izi yoktur.
//
// setTimeout ŞART: `duration` = loadEventEnd - startTime, ve loadEventEnd
// "load olayı TAMAMLANDIKTAN sonra" yazılıyor. Doğrudan load handler'ının
// içinde okunursa henüz 0'dır ve her sayfa için "0.0 ms" basardık. Bir tik
// bekleyip okuyoruz; yine de dolmamışsa performance.now()'a düşüyoruz.
window.addEventListener('load', () => {
  setTimeout(() => {
    const nav = performance.getEntriesByType('navigation')[0];
    const ms = nav && nav.loadEventEnd ? nav.duration : performance.now();
    Logger.duration('page', `page load (${document.title})`, ms, 3000);
  }, 0);
});
