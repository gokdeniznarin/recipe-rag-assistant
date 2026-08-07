/**
 * Tarif sayfasını <head>'i DOLU olarak sunan Vercel fonksiyonu (Faz 29).
 *
 * NEDEN GEREKLİ: `recipe.html` statik bir dosya ve gövdesini JS dolduruyor.
 * Pinterest ve Google kazıyıcıları JS'i güvenilir biçimde çalıştırmıyor, yani
 * onlar için sayfa bugün BOŞ: 9.795 tarifin hepsinde aynı başlık, sıfır görsel,
 * sıfır açıklama. Bu fonksiyon aradaki farkı kapatıyor.
 *
 * NEDEN STATİK ÜRETİM DEĞİL: alternatif, build sırasında 9.795 HTML dosyası
 * üretip repoya koymaktı. İki sebeple elendi — (1) `recipes_cleaned.csv`
 * `.gitignore`'da ve repoda YOK, yani Vercel'de build edecek veri yok
 * (Faz 8'de `chroma_data`'yı commit'lemeye zorlayan problemin aynısı),
 * (2) ~100 MB üretilmiş HTML repoya girerdi.
 */

const { parseRecipePath, buildHead, inject } = require('./_seo');
const { loadTemplate, fetchJson, originOf, sendHtml } = require('./_render');

module.exports = async function handler(req, res) {
  const origin = originOf(req);
  const recipeId = parseRecipePath(req.url);

  if (!recipeId) {
    res.statusCode = 404;
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    return res.end('<!doctype html><title>Not found</title><p>Recipe not found.');
  }

  let template;
  try {
    template = await loadTemplate('recipe.html', origin);
  } catch (_) {
    res.statusCode = 500;
    return res.end('Could not load the recipe page.');
  }

  const recipe = await fetchJson(`/api/recipes/${encodeURIComponent(recipeId)}`);

  if (!recipe) {
    // Etiketsiz sürüm indekslenmemeli: içeriği olmayan bir sayfayı Google'a
    // vermek, hiç vermemekten kötü. Önbelleğe de alınmıyor — API'nin geçici
    // bir arızası bir saat boyunca boş sayfa servis ettirmemeli.
    return sendHtml(res, inject(
      template,
      '<title>Recipe — Recipe Assistant</title>\n  <meta name="robots" content="noindex" />',
      { __RECIPE_ID__: String(recipeId) }
    ), false);
  }

  // Tarif verisi de gömülüyor: istemci ikinci bir istek atmıyor ve — asıl
  // kazanç — `apiRequest`'in `authReady` beklemesini (canlıda ~975 ms,
  // Faz 13b) hiç ödemiyor.
  const html = inject(template, buildHead({ ...recipe, id: recipeId }, origin, {}), {
    __RECIPE_ID__: String(recipeId),
    __RECIPE_DATA__: { ...recipe, id: recipeId },
  });
  sendHtml(res, html, true);
};
