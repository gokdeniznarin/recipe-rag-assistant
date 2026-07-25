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
 * Alışveriş listesi mağaza adaptörü (Faz 19).
 *
 * MAĞAZA = AMAZON.COM. Migros'tan buraya geçildi çünkü uygulama baştan sona
 * İNGİLİZCE (dataset, arayüz, kullanıcı girdisi): malzeme adları amazon.com'un
 * kataloğuyla doğrudan eşleşiyor, araya çeviri katmanı girmiyor ve arama
 * isabeti yüksek oluyor. (Migros denendi ve çalışıyordu, ama Türkçe katalog
 * için EN→TR sözlüğü gerekiyordu; Amazon.com.tr ise hem çeviri isterdi hem
 * taze ürün satmıyor — iki dünyanın kötüsü olurdu. Gerekçe CLAUDE.md Faz 19.)
 *
 * GELİR KAPISI — affiliate etiketi CANLI. Amazon Associates `tag` parametresini
 * URL'ye ekliyor; nitelikli satışta komisyon bu etikete işleniyor.
 *   mode: 'off'    → etiket yok, tertemiz arama linki
 *   mode: 'append' → URL'ye parametre ekle (Amazon tarzı; ?/& ayıracı otomatik)
 *   mode: 'wrap'   → affiliate ağının redirect'iyle sar (ör. bir TR ağı)
 * `{q}` arama terimi, `{url}` kaçışlanmış hedef URL ile değiştiriliyor.
 *
 * ⚠️ Etiket kullanıldığı sürece sitede Amazon Associates AÇIKLAMASI görünmek
 * ZORUNDA (Associates Program Operating Agreement şartı) — shopping.html'de.
 */
window.SHOP = {
  store: 'Amazon',
  // Tek ürün araması (satır-başına link) — `i=grocery` aramayı market
  // kategorisiyle sınırlıyor, yoksa "butter" mutfak gereci de getiriyor.
  searchUrl: 'https://www.amazon.com/s?k={q}&i=grocery',
  // Büyük CTA'nın hedefi: market KATEGORİSİ. Anasayfa değil (o Migros'un
  // Cloudflare engeli yüzünden seçilmişti, Amazon'da öyle bir kısıt yok) ve
  // tüm listeyi tek aramaya doldurmak da değil — Amazon araması terimlerin
  // HEPSİNİ içeren ürün aradığı için 12 malzemelik sorgu boş/çöp döner.
  homeUrl: 'https://www.amazon.com/s?i=grocery',
  affiliate: { mode: 'append', param: 'tag=recipeassista-20', wrap: '' },
};
