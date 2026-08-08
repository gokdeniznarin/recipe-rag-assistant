/**
 * `sitemap.xml` (Faz 29, adım 7).
 *
 * NEDEN FONKSİYON, STATİK DOSYA DEĞİL: koleksiyon listesi backend'de
 * (`api/discover.py`) yaşıyor. Statik bir XML dosyası tutulsa, yeni bir
 * koleksiyon eklendiğinde onu güncellemeyi unutmak SESSİZ bir kayıp olurdu —
 * sayfa çalışır, Google onu hiç bulmaz. Burada liste her istekte kaynaktan
 * okunuyor, yani ayrışamıyor.
 *
 * ⚠️ TARİF SAYFALARI SİTEMAP'TE YOK ve bu bilinçli — gerekçe `_seo.js`'teki
 * `buildSitemap`'te yazılı: onlar `noindex` ile çıkıyor ve `noindex` bir
 * sayfayı sitemap'e koymak Google'a aynı anda "indeksle" ve "indeksleme"
 * demek olurdu.
 */

const { buildSitemap } = require('./_seo');
const { fetchJson, originOf } = require('./_render');

module.exports = async function handler(req, res) {
  const origin = originOf(req);
  const index = await fetchJson('/api/discover');

  res.setHeader('Content-Type', 'application/xml; charset=utf-8');

  if (!index) {
    // API erişilemiyor: BOŞ ama geçerli bir sitemap dön ve önbelleğe ALMA.
    // Hata döndürmek Google'ın sitemap'i "kırık" işaretlemesine yol açar ve
    // o işaret geçici bir arızadan çok daha uzun sürer.
    res.setHeader('Cache-Control', 'no-store');
    return res.end(buildSitemap([], origin));
  }

  res.setHeader('Cache-Control', 'public, s-maxage=3600, stale-while-revalidate=86400');
  res.end(buildSitemap(index.collections, origin));
};
