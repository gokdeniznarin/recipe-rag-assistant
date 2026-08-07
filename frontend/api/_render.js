/**
 * Statik bir HTML şablonunu okuyup Render'daki API'den veri çeken ortak
 * yardımcılar (Faz 29).
 *
 * `recipe.js` ve `discover.js` aynı üç işi yapıyor: şablonu bul, API'yi
 * anahtarla çağır, hata olursa yut. Üçünü de iki dosyaya kopyalamak,
 * projedeki "aynı kuralı iki yere yazma" ilkesine aykırı olurdu (Faz 15d/19).
 */

const fs = require('fs');
const path = require('path');

const API_BASE =
  process.env.RECIPE_API_BASE || 'https://recipe-rag-assistant-api-7g6a.onrender.com';

const templates = new Map();

/**
 * Şablonu oku.
 *
 * ⚠️ YERELDE DOĞRULANAMAYAN tek parça: bir Vercel fonksiyonunun paketlenmiş
 * hâlinde statik dosyanın hangi yola düştüğü dağıtım ortamına bağlı ve burada
 * `vercel dev` çalıştıramıyoruz. Birden fazla aday yol deneniyor; hiçbiri
 * tutmazsa dosya KENDİ ORIGIN'İMİZDEN HTTP ile çekiliyor — bu son yol her
 * koşulda çalışır, çünkü Vercel şablonu zaten statik olarak sunuyor. Yani
 * kötü ihtimalde fonksiyon yavaşlar; sessizce bozulmaz.
 */
async function loadTemplate(name, origin) {
  if (templates.has(name)) return templates.get(name);

  for (const candidate of [
    path.join(process.cwd(), name),
    path.join(__dirname, '..', name),
  ]) {
    try {
      const html = fs.readFileSync(candidate, 'utf8');
      templates.set(name, html);
      return html;
    } catch (_) { /* sıradaki adaya geç */ }
  }

  const response = await fetch(`${origin}/${name}`);
  if (!response.ok) throw new Error(`template fetch failed: ${response.status}`);
  const html = await response.text();
  templates.set(name, html);
  return html;
}

/**
 * API'den JSON çek. Hata olursa null — çağıran sayfayı yine sunuyor.
 *
 * Sert hata vermemek bilinçli: API erişilemezse kazıyıcı zengin etiketleri
 * kaçırır ama ZİYARETÇİ normal sayfayı görür (gövdeyi istemci dolduruyor).
 * 500 döndürmek bütün siteyi bozuk gösterirdi.
 */
async function fetchJson(apiPath) {
  try {
    const headers = {};
    // Hız sınırı muafiyeti: bu çağrılar Vercel'in IP'lerinden geliyor, yani
    // muafiyet olmadan tüm ziyaretçilerin trafiği birkaç IP'de toplanır ve
    // bu yol tam da trafik geldiği anda kendi kendini 429'a düşürür.
    if (process.env.INTERNAL_API_KEY) {
      headers['X-Internal-Key'] = process.env.INTERNAL_API_KEY;
    }
    const response = await fetch(`${API_BASE}${apiPath}`, {
      headers,
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const body = await response.json();
    return body && body.error ? null : body;
  } catch (_) {
    return null;
  }
}

function originOf(req) {
  return `https://${req.headers['x-forwarded-host'] || req.headers.host}`;
}

function sendHtml(res, html, cacheable) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  // Önbelleklenebilir: yanıt tamamen salt-okunur, kamu malı tarif verisi ve
  // kullanıcıya özel HİÇBİR ŞEY içermiyor. (Faz 26'daki "API yanıtlarını asla
  // önbelleğe alma" kuralı burada geçerli değil — o kural kullanıcı verisini
  // korumak içindi; buradaki sayfa zaten herkese aynı.)
  res.setHeader(
    'Cache-Control',
    cacheable ? 'public, s-maxage=3600, stale-while-revalidate=86400' : 'no-store'
  );
  res.end(html);
}

module.exports = { API_BASE, loadTemplate, fetchJson, originOf, sendHtml };
