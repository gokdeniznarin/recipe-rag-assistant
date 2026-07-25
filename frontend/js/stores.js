/**
 * Alışveriş listesi ↔ mağaza adaptörü (Faz 19).
 *
 * Tek iş: affiliate config'ini uygulayıp gidilecek URL'yi kurmak. Mağaza
 * `window.SHOP`'tan (config.js) geliyor, buraya gömülü değil — mağaza
 * değiştirmek tek config satırı.
 *
 * ÇEVİRİ KATMANI KALDIRILDI (Migros döneminden kalmıştı): malzemeler İngilizce
 * ve mağaza artık amazon.com, yani adlar katalogla doğrudan eşleşiyor. EN→TR
 * sözlüğü çağrılmayan ölü koda dönüştüğü için silindi; gerekirse git
 * geçmişinde (Faz 19, Migros commit'leri).
 *
 * SAF + node-test edilebilir: tarayıcı global'i kullanmıyor, config'i parametre
 * olarak alıyor. Alttaki module.exports yalnızca test içindir (tarayıcıda
 * `Stores` global'i klasik script paylaşımıyla kullanılıyor, Logger gibi).
 */
const Stores = (function () {

  // Affiliate config'ini bir URL'ye uygular.
  //   'append' → parametre ekle (Amazon `tag=...`). Ayıraç OTOMATİK: URL'de
  //              zaten '?' varsa '&', yoksa '?' — arama URL'si ile anasayfa
  //              aynı fonksiyondan geçtiği için bu şart.
  //   'wrap'   → affiliate ağının redirect'iyle sar.
  function _applyAffiliate(url, aff) {
    aff = aff || {};
    if (aff.mode === 'append' && aff.param) {
      return url + (url.indexOf('?') === -1 ? '?' : '&') + aff.param;
    }
    if (aff.mode === 'wrap' && aff.wrap) {
      return aff.wrap.replace('{url}', encodeURIComponent(url));
    }
    return url;
  }

  // Tek ürün araması URL'si (satır-başına link).
  function buildUrl(query, cfg) {
    cfg = cfg || {};
    const tmpl = cfg.searchUrl || 'https://www.google.com/search?q={q}';
    return _applyAffiliate(tmpl.replace('{q}', encodeURIComponent(query)), cfg.affiliate);
  }

  // Mağaza anasayfası URL'si (büyük CTA).
  function storeHome(cfg) {
    cfg = cfg || {};
    const home = cfg.homeUrl || (cfg.searchUrl || 'https://www.google.com/').split('?')[0];
    return _applyAffiliate(home, cfg.affiliate);
  }

  return { buildUrl, storeHome };
})();

// Yalnızca node testi için (tarayıcıda `typeof module` undefined, zararsız).
if (typeof module !== 'undefined') module.exports = Stores;
