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
