/**
 * Küratörlü koleksiyon iniş sayfası (Faz 29) — Pinterest pin'lerinin hedefi.
 *
 * `recipe.js`'in kardeşi ve aynı gerekçeyle var: sayfanın gövdesini JS
 * dolduruyor, kazıyıcılar JS çalıştırmıyor, dolayısıyla <head> sunucuda
 * dolmazsa pin başlıksız ve görselsiz çıkıyor.
 *
 * Tarif sayfasından bir farkı var: bu sayfalar İNDEKSLENEBİLİR. 12 tane,
 * elle küratörlü ve her biri kendi metnini taşıyor; tarif sayfalarındaki
 * "9.795 sayfa kamu malı metin" riski burada yok.
 */

const {
  parseCollectionPath, buildCollectionHead, buildIndexHead, inject,
} = require('./_seo');
const { loadTemplate, fetchJson, originOf, sendHtml } = require('./_render');

module.exports = async function handler(req, res) {
  const origin = originOf(req);
  const slug = parseCollectionPath(req.url);

  let template;
  try {
    template = await loadTemplate('discover.html', origin);
  } catch (_) {
    res.statusCode = 500;
    return res.end('Could not load the collection page.');
  }

  // Slug YOK → `/discover` dizini. Koleksiyon sayfalarının sonundaki
  // "More collections" çipleri buraya bağlıydı ve burası 404 veriyordu.
  if (!slug) {
    const index = await fetchJson('/api/discover');
    if (!index) {
      return sendHtml(res, inject(
        template,
        '<title>Recipe collections — Recipe Assistant</title>\n  <meta name="robots" content="noindex" />',
        {}
      ), false);
    }
    return sendHtml(res, inject(
      template,
      buildIndexHead(index.collections, origin),
      { __COLLECTION_INDEX__: index.collections }
    ), true);
  }

  const data = await fetchJson(`/api/discover/${encodeURIComponent(slug)}`);

  if (!data) {
    return sendHtml(res, inject(
      template,
      '<title>Recipe collections — Recipe Assistant</title>\n  <meta name="robots" content="noindex" />',
      { __COLLECTION_SLUG__: slug }
    ), false);
  }

  const html = inject(template, buildCollectionHead(data, origin, {}), {
    __COLLECTION_SLUG__: slug,
    __COLLECTION_DATA__: data,
  });
  sendHtml(res, html, true);
};
