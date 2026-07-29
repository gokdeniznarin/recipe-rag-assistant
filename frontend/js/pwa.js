/**
 * Service worker kaydı (Faz 26 — PWA).
 *
 * Her sayfada yükleniyor, ama PAYLAŞILAN dosyalardan farklı olarak hiçbir DOM
 * elemanına dokunmuyor — tek işi service worker'ı kaydetmek.
 *
 * BAĞIMSIZ olmak zorunda: `privacy.html` hiç script yüklemiyor (ne firebase, ne
 * logger), dolayısıyla burada `Logger`'ın var olduğu VARSAYILAMAZ. O yüzden
 * feature-detect ile console'a düşülüyor.
 *
 * Kayıt yalnızca güvenli bağlamda (https ya da localhost) çalışır; tarayıcı
 * bunu kendisi zorluyor, hata yutulup uygulama normal web sayfası gibi devam
 * ediyor — PWA katmanı hiçbir koşulda uygulamayı düşürmemeli (Faz 13b'de
 * logger.js'in localStorage yüzünden uygulamayı düşürmesinin dersi).
 *
 * YEREL GELİŞTİRME NOTU: service worker + nginx bind-mount önbelleği üst üste
 * binince "değişikliğim neden görünmüyor?" hatası ikiye katlanır. sw.js
 * network-first olduğu için çevrimiçiyken taze dosya hep kazanır; yine de
 * takılırsan DevTools → Application → Service Workers → "Bypass for network".
 */
(function () {
  const log =
    typeof Logger !== 'undefined' && Logger.get ? Logger.get('pwa') : console;

  if (!('serviceWorker' in navigator)) {
    log.debug('Service workers not supported; skipping PWA setup');
    return;
  }

  window.addEventListener('load', async () => {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      log.info('Service worker registered');

      // Yeni sürüm indiğinde SAYFAYI OTOMATİK YENİLEMİYORUZ: kullanıcı yarım
      // kalmış bir arama ya da doldurulmuş bir form üzerinde olabilir. Yeni
      // sürüm bir sonraki normal sayfa geçişinde zaten devreye giriyor.
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing;
        if (!sw) return;
        sw.addEventListener('statechange', () => {
          if (sw.state === 'installed' && navigator.serviceWorker.controller) {
            log.info('A new version is ready; it will apply on the next page load');
          }
        });
      });
    } catch (err) {
      log.warn('Service worker registration failed: ' + err.message);
    }
  });
})();
