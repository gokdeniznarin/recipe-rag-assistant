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

const { parseCollectionPath, buildCollectionHead, inject } = require('./_seo');
const { loadTemplate, fetchJson, originOf, sendHtml } = require('./_render');

module.exports = async function handler(req, res) {
  const origin = originOf(req);
  const slug = parseCollectionPath(req.url);

  if (!slug) {
    res.statusCode = 404;
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    return res.end('<!doctype html><title>Not found</title><p>Collection not found.');
  }

  let template;
  try {
    template = await loadTemplate('discover.html', origin);
  } catch (_) {
    res.statusCode = 500;
    return res.end('Could not load the collection page.');
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
