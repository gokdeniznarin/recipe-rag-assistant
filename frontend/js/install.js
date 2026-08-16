/**
 * "Install app" butonu — PWA kurulumunu GÖRÜNÜR kılan katman.
 *
 * NEDEN VAR: uygulama Faz 26'dan beri kurulabiliyordu ama kurulum yolu tamamen
 * tarayıcının kendi arayüzüne bırakılmıştı — masaüstü Chrome'da bu adres
 * çubuğunun içinde küçük bir simge, Android'de ekranın altından çıkıp kaybolan
 * bir çubuk. Yani özellik vardı, keşfedilmiyordu.
 *
 * ÜÇ FARKLI DÜNYA VAR ve üçü de ayrı ele alınıyor:
 *
 *   1. Chrome / Edge / Samsung  -> `beforeinstallprompt` olayı geliyor.
 *      Olay saklanıp buton gösteriliyor; tıklanınca tarayıcının KENDİ kurulum
 *      penceresi açılıyor (kendi penceremizi çizemeyiz, tarayıcı izin vermiyor).
 *
 *   2. iOS / iPadOS -> `beforeinstallprompt` YOK, hiçbir tarayıcıda. Orada
 *      kurulum elle: Paylaş -> Ana Ekrana Ekle. Buton yerine kısa bir yönerge
 *      gösteriliyor. (Buton gösterseydik basan hiçbir şey olmadığını görürdü.)
 *
 *   3. Masaüstü Firefox -> kurulum diye bir şey yok. Ne olay geliyor ne iOS,
 *      dolayısıyla İKİSİ DE gizli kalıyor. Sessizlik burada doğru davranış:
 *      yapılamayacak bir şeyi önermek, çalışmayan bir buton kadar kötü.
 *
 * Zaten kurulu olan uygulamanın İÇİNDE hiçbir şey gösterilmiyor — kurulu
 * uygulamada "Install app" görmek kafa karıştırır.
 *
 * ⚠️ `preventDefault()` opsiyonel değil: çağrılmazsa Chrome kendi çubuğunu
 * gösterir ve olay bizde saklanamaz, yani butonumuz hiç çalışmaz.
 *
 * ⚠️ Olay TEK KULLANIMLIK. `prompt()` çağrıldıktan sonra aynı nesne yeniden
 * kullanılamıyor; kullanıcı vazgeçse bile atılıyor ve buton gizleniyor. Chrome
 * uygun gördüğünde olayı yeniden yolluyor, o zaman buton yeniden görünüyor.
 *
 * BİLİNEN SINIR: olay bu dosya yüklenmeden ÖNCE tetiklenirse kaçırılır ve buton
 * o ziyarette çıkmaz. Script'ler gövdenin sonunda, `load` olayından önce
 * çalıştığı için pratikte görülmedi; kaçırıldığında da tarayıcının kendi
 * kurulum yolu duruyor, yani kayıp görünürlük — işlev değil.
 */
(function () {
  const log =
    typeof Logger !== 'undefined' && Logger.get ? Logger.get('install') : console;

  const btn = document.getElementById('install-btn');
  const hint = document.getElementById('install-hint');
  if (!btn && !hint) return;

  // Kurulu uygulamanın içinde miyiz? `display-mode` standart yol; iOS onu
  // desteklemediği için `navigator.standalone` ile tamamlanıyor.
  const standalone =
    (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
    window.navigator.standalone === true;
  if (standalone) return;

  let deferred = null;

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferred = event;
    if (hint) hint.classList.add('hidden');
    if (btn) btn.classList.remove('hidden');
    log.info('Install prompt is available');
  });

  if (btn) {
    btn.addEventListener('click', async () => {
      if (!deferred) return;
      const prompt = deferred;
      deferred = null;
      btn.classList.add('hidden');
      try {
        prompt.prompt();
        const { outcome } = await prompt.userChoice;
        log.info('Install prompt ' + outcome);
      } catch (err) {
        // Kullanıcı hızlıca gezinirse tarayıcı pencereyi iptal edebiliyor.
        log.warn('Install prompt failed: ' + err.message);
      }
    });
  }

  window.addEventListener('appinstalled', () => {
    deferred = null;
    if (btn) btn.classList.add('hidden');
    if (hint) hint.classList.add('hidden');
    log.info('App installed');
  });

  // iOS/iPadOS. iPadOS 13+ kendini masaüstü Safari gibi tanıttığı için
  // `platform` tek başına yetmiyor; dokunmatik nokta sayısı ayırt ediyor.
  const ios =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  if (hint && ios) hint.classList.remove('hidden');
})();
