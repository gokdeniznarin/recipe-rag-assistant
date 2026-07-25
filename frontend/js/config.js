/**
 * Ortama göre backend (API) adresini seçer. api.js'ten ÖNCE yüklenir; global
 * `window.API_BASE`'i kurar.
 *
 * - Yerel/LAN geliştirme (localhost, 127.0.0.1 veya bir IP): backend aynı makinede,
 *   8080 portunda. Telefondan LAN IP'siyle test de bu dala düşer.
 * - Onun dışında (canlı — Vercel domain'i): backend Render'da.
 */
(function () {
  const host = window.location.hostname;
  const isLocalOrLan =
    host === 'localhost' ||
    host === '127.0.0.1' ||
    /^\d{1,3}(\.\d{1,3}){3}$/.test(host); // LAN IP (örn. 10.240.100.10)

  window.API_BASE = isLocalOrLan
    ? `http://${host}:8080`
    : 'https://recipe-rag-assistant-api-7g6a.onrender.com';
})();

/**
 * Alışveriş listesi "Shop this list" / satır-başına "bul" hedefi (Faz 19).
 * Migros Sanal Market araması. Malzemeler İngilizce; stores.js Türkçe'ye
 * çevirip buraya veriyor.
 *
 * GELİR KAPISI — affiliate. `mode: 'off'` iken link tertemiz bir arama:
 * ortada sahte hiçbir şey yok, sadece kullanıcıyı markete götürüyor. Gerçek bir
 * affiliate hesabı açılınca kod değişmeden gelir akmaya başlar:
 *   - Ağ tarzı (Migros'un affiliate ağının verdiği redirect linki):
 *       mode: 'wrap', wrap: 'https://ag.example/click?url={url}'
 *   - Amazon tarzı (URL'ye etiket parametresi eklemek):
 *       mode: 'append', append: '&tag=SENIN-ID'
 * `{q}` arama terimi, `{url}` ise kaçışlanmış hedef URL ile değiştiriliyor.
 */
window.SHOP = {
  store: 'Migros',
  // searchUrl: tek ürün araması (satır-başına link). Migros Cloudflare ile dış
  // deep-link'leri challenge edebiliyor; `rel="noreferrer"` ile referrer'sız
  // gidince geçme şansı artıyor. Kesin çözüm production'da affiliate-ağ linki
  // (aşağıdaki wrap) — o Migros'un beklediği meşru trafik.
  searchUrl: 'https://www.migros.com.tr/arama?q={q}',
  // homeUrl: büyük "Shop at ..." CTA'sının hedefi. Anasayfa asla bloklanmaz.
  homeUrl: 'https://www.migros.com.tr/',
  affiliate: { mode: 'off', append: '', wrap: '' },
};
