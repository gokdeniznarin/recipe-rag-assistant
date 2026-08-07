/**
 * Tarif sayfasının <head>'ini üreten SAF fonksiyonlar (Faz 29).
 *
 * NEDEN AYRI DOSYA: asıl handler (`recipe.js`) ağ çağrısı yapıyor ve Vercel'in
 * çalışma ortamına bağlı, yani yerelde çalıştırılamıyor. Buradaki fonksiyonların
 * hiçbirinin yan etkisi yok — `scripts/test_seo_meta.js` bunları doğrudan
 * koşturuyor. `stores.js` / `camera.js`'teki ayrımın aynısı.
 *
 * NEDEN ÖNEMLİ: Pinterest ve Google bir sayfadan SADECE bu etiketleri okuyor.
 * Sayfanın gövdesini JS dolduruyor ve kazıyıcılar JS'i güvenilir biçimde
 * çalıştırmıyor — yani burada üretilmeyen hiçbir bilgi dış dünyada YOK sayılır.
 */

/** HTML özniteliği içinde güvenli hale getir. */
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Tarif adından URL parçası üret: "Cheesy Asparagus And Ham" → "cheesy-asparagus-and-ham"
 *
 * Slug SADECE okunabilirlik için — kimlik `id`'de. Yani slug bozuk ya da eski
 * olsa bile sayfa açılır (bkz. `parseRecipePath`), çünkü tarif adı değişirse
 * eski linklerin ölmesini istemeyiz.
 */
function slugify(name) {
  return String(name || '')
    .toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')   // aksanları düşür
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
}

/**
 * "/recipes/25500-cheesy-asparagus" → "25500"
 *
 * Yalnızca baştaki rakamlar okunuyor: slug'ın doğru olması ŞART DEĞİL. Biri
 * linki elle kısaltıp `/recipes/25500` yazsa da çalışıyor, tarif adı değişse de
 * eski linkler ölmüyor. Eşleşme yoksa null.
 */
function parseRecipePath(pathname) {
  const m = /^\/recipes\/(\d+)(?:-|$)/.exec(String(pathname || '').split('?')[0]);
  return m ? m[1] : null;
}

/** Kanonik yol — bir tarifin TEK adresi. */
function recipePath(id, name) {
  const slug = slugify(name);
  return slug ? `/recipes/${id}-${slug}` : `/recipes/${id}`;
}

/**
 * Dakikayı ISO 8601 süresine çevir: 28 → "PT28M", 90 → "PT1H30M"
 *
 * 🔎 Bu, HAM VERİ SETİNDEKİ formatın ta kendisi (`PT24H45M`); `clean_data.py`
 * onu dakikaya çeviriyor, burada geri çeviriyoruz. schema.org'un istediği de bu.
 */
function isoDuration(minutes) {
  const total = Math.round(Number(minutes) || 0);
  if (total <= 0) return '';
  const h = Math.floor(total / 60);
  const m = total % 60;
  return 'PT' + (h ? `${h}H` : '') + (m ? `${m}M` : '');
}

/**
 * Arama sonucunda ve pin'de görünen açıklama.
 *
 * Veri setindeki `description` alanı KULLANILMIYOR: o metin embedding için
 * üretildi ("Name: X. Category: Y. Ingredients: ...") ve insana değil modele
 * hitap ediyor. Burada okunabilir bir cümle kuruluyor.
 */
function metaDescription(recipe) {
  const parts = [];
  const mins = Math.round(Number(recipe.total_time_min) || 0);
  if (mins > 0) parts.push(`Ready in ${mins} minutes`);

  // ⚠️ KALORİ BİLEREK YOK. Veri setindeki değerin porsiyon başına mı yoksa
  // tarifin tamamı için mi olduğu TUTARSIZ — 9.795 tarifte ölçüldü:
  // medyan 309 kcal, ama %6.9'u 1000'in, %1.1'i 3000'in üstünde ve en
  // yükseği 38.662 kcal. Porsiyon sayısı (`RecipeServings`) ingest
  // EDİLMEDİĞİ için hangisi olduğunu ayırt edemiyoruz.
  // Uygulamanın içinde bu sayı etiketiyle ve diğer makrolarla birlikte
  // görünüyor, yani bağlamı var. Arama sonucundaki tek satırlık bir
  // özette ise çıplak bir sayı — "8024 calories" yazan bir pound cake
  // hem saçma görünür hem yanıltıcıdır. Bkz. jsonLd'deki aynı karar.

  const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients : [];
  if (ingredients.length) parts.push(`Made with ${ingredients.slice(0, 4).join(', ')}`);

  let text = parts.join(' · ');
  // ~155 karakter: arama sonuçlarında gösterilen tipik sınır. Kelime ortasından
  // kesmemek için son boşluğa kadar geri sarılıyor.
  if (text.length > 155) {
    text = text.slice(0, 155);
    text = text.slice(0, text.lastIndexOf(' ')) + '…';
  }
  return text;
}

/**
 * schema.org/Recipe — Pinterest'in "Rich Pin"i ve Google'ın tarif kartı
 * aynı işaretlemeyi okuyor. Tek iş, iki kanal.
 *
 * ⚠️ `suitableForDiet` BİLEREK YAZILMIYOR (karar: 2026-08-07).
 * Diyet etiketlerimiz kural bazlı TAHMİN ve iki ölçülmüş hatası var:
 *   - `nut_free`: "Pine Nut and Almond Cookies" fıstıksız işaretli (Faz 15b,
 *     xfail testi olarak kayıtlı, henüz düzeltilmedi)
 *   - `vegetarian`: 228 tarif vejetaryen işaretli ama içinde et var — `land_meat`
 *     listesinde `ham`/`sausage`/`prosciutto` yok (2026-08-07'de ölçüldü)
 * Arayüzde bu etiketlerin yanında "otomatik tahmin" uyarısı var. YAPILANDIRILMIŞ
 * VERİDE UYARI YERİ YOK — makine okur, "bu tarif fıstıksızdır" diye gösterir.
 * Alerji söz konusu olduğunda bu kabul edilebilir bir risk değil.
 */
function jsonLd(recipe, absoluteUrl) {
  const data = {
    '@context': 'https://schema.org',
    '@type': 'Recipe',
    name: recipe.name || '',
    url: absoluteUrl,
  };

  if (recipe.image_url) data.image = recipe.image_url;
  if (recipe.category) data.recipeCategory = recipe.category;

  const duration = isoDuration(recipe.total_time_min);
  if (duration) data.totalTime = duration;

  const ingredients = Array.isArray(recipe.ingredients) ? recipe.ingredients : [];
  if (ingredients.length) data.recipeIngredient = ingredients;

  const steps = splitInstructions(recipe.instructions);
  if (steps.length) {
    data.recipeInstructions = steps.map((text) => ({ '@type': 'HowToStep', text }));
  }

  // ⚠️ `nutrition` BİLEREK YAZILMIYOR — `suitableForDiet` kararının aynısı,
  // üçüncü kez uygulanıyor: arkasında duramayacağımız makine okunur bir
  // iddiayı yayınlamıyoruz.
  //
  // schema.org'un `NutritionInformation`'ı teamülen PORSİYON BAŞINA. Bizim
  // değerlerimizin tabanı belirsiz: 9.795 tarifte medyan 309 kcal (porsiyon
  // gibi duruyor) ama %6.9'u 1000, %1.1'i 3000 kcal üstünde ve en yükseği
  // 38.662 — yani bir kısmı açıkça tarifin TAMAMI için. `RecipeServings`
  // kolonu veri setinde %64 dolu ama ingest EDİLMEDİ, dolayısıyla bölüp
  // porsiyona indiremiyoruz.
  //
  // Sayılar uygulamanın içinde etiketleriyle görünmeye devam ediyor (orada
  // bağlam var). Burada yayınlamak, Google'ın bir tarif kartında "160 kalori"
  // diye GERÇEK olarak göstermesi demek.
  //
  // AÇILIŞ YOLU: adım A'daki yeniden ingestion'da `RecipeServings` de
  // eklenirse (zaten et etiketi hatası için ingestion yapılacak), porsiyon
  // başına değer hesaplanabilir ve bu blok gerçek veriyle geri gelebilir.

  // Veri atfı: CC0 olduğu için hukuken zorunlu DEĞİL, ama kaynağı göstermek
  // hem dürüst hem de "bu veri nereden geliyor?" sorusunun hazır cevabı.
  data.creditText = 'Food.com recipe data (CC0)';

  return data;
}

/**
 * "1. Adım bir. 2. Adım iki." → ["Adım bir.", "Adım iki."]
 * `recipe.js`'teki `parseInstructions`'ın sunucu tarafındaki kardeşi.
 */
function splitInstructions(raw) {
  return String(raw || '')
    .split(/\s*\d+\.\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 3 && /[a-z]/i.test(s));
}

/**
 * <head>'e enjekte edilecek etiketlerin tamamı.
 *
 * `indexable` VARSAYILAN OLARAK FALSE — yani her tarif `noindex` ile çıkıyor,
 * yalnızca küratörlü olanlar açılıyor. Yön bilinçli: 9.795 sayfayı Google'a
 * indeksletmek kolay, indeksten ÇIKARMAK aylar sürüyor. Hepsi kamu malı ve
 * aynı metin başka sitelerde de var, yani toplu indeksleme "içerik çiftliği"
 * profili çizip domainin itibarını düşürebilir.
 * ⚠️ `noindex` Pinterest'i ENGELLEMEZ (o ayrı bir direktif, `nopin`) — zaten
 * pinlediğimiz tarifler küratörlü listede olacağı için soru pratikte doğmuyor.
 */
function buildHead(recipe, origin, options) {
  const opts = options || {};
  const path = recipePath(recipe.id, recipe.name);
  const url = `${origin}${path}`;
  const description = metaDescription(recipe);
  const title = recipe.name ? `${recipe.name} — Recipe Assistant` : 'Recipe Assistant';

  const tags = [
    `<title>${escapeHtml(title)}</title>`,
    `<meta name="description" content="${escapeHtml(description)}" />`,
    `<link rel="canonical" href="${escapeHtml(url)}" />`,
  ];

  if (!opts.indexable) {
    tags.push('<meta name="robots" content="noindex, follow" />');
  }

  tags.push(
    '<meta property="og:type" content="article" />',
    `<meta property="og:title" content="${escapeHtml(recipe.name || '')}" />`,
    `<meta property="og:description" content="${escapeHtml(description)}" />`,
    `<meta property="og:url" content="${escapeHtml(url)}" />`,
    '<meta name="twitter:card" content="summary_large_image" />'
  );

  // Görsel yoksa etiket HİÇ basılmıyor: boş bir og:image, Pinterest'in
  // sayfayı "pinlenemez" saymasından daha kötü — bozuk bir pin üretir.
  if (recipe.image_url) {
    tags.push(`<meta property="og:image" content="${escapeHtml(recipe.image_url)}" />`);
  }

  // ⚠️ `</script>` kaçışı: tarif adı veri setinden geliyor ve içinde "</script>"
  // geçen bir ad, JSON string'i içinde bile olsa etiketi ERKEN KAPATIR ve
  // kalan metin çalıştırılabilir HTML'e dönüşür. JSON.stringify bunu kaçırmaz.
  const ld = JSON.stringify(jsonLd(recipe, url)).replace(/</g, '\\u003c');
  tags.push(`<script type="application/ld+json">${ld}</script>`);

  return tags.join('\n  ');
}

/** "/discover/30-minute-dinners" → "30-minute-dinners" */
function parseCollectionPath(pathname) {
  const m = /^\/discover\/([a-z0-9-]+)\/?$/.exec(String(pathname || '').split('?')[0]);
  return m ? m[1] : null;
}

/**
 * Koleksiyon iniş sayfasının <head>'i.
 *
 * Tarif sayfasından iki farkı var ve ikisi de bilinçli:
 *
 * 1. `og:image` KOLEKSİYONUN İLK TARİFİNDEN geliyor. Kendi tipografik pin
 *    görselimiz burada KULLANILAMAZ çünkü onlar Pinterest'e elle yüklenecek;
 *    bu etiket, sayfayı BAŞKASI paylaştığında ne görüneceğini belirliyor ve
 *    orada gerçek bir yemek fotoğrafı tek anlamlı seçenek.
 *
 * 2. `indexable` VARSAYILAN OLARAK TRUE — tarif sayfalarının tersi. Sebep:
 *    koleksiyonlar 12 tane, elle küratörlü ve her biri kendi metnini taşıyor,
 *    yani "içerik çiftliği" riski yok. Tarif sayfalarında ise 9.795 sayfa
 *    kamu malı metin var ve toplu indeksleme domainin itibarını düşürebilir.
 */
function buildCollectionHead(data, origin, options) {
  const opts = options || {};
  const url = `${origin}/discover/${data.slug}`;
  const title = `${data.title} — Recipe Assistant`;
  const recipes = Array.isArray(data.recipes) ? data.recipes : [];
  const description = recipes.length
    ? `${data.description} ${recipes.length} recipes to browse.`
    : data.description;

  const tags = [
    `<title>${escapeHtml(title)}</title>`,
    `<meta name="description" content="${escapeHtml(description)}" />`,
    `<link rel="canonical" href="${escapeHtml(url)}" />`,
  ];

  if (opts.indexable === false) {
    tags.push('<meta name="robots" content="noindex, follow" />');
  }

  tags.push(
    '<meta property="og:type" content="website" />',
    `<meta property="og:title" content="${escapeHtml(data.title)}" />`,
    `<meta property="og:description" content="${escapeHtml(description)}" />`,
    `<meta property="og:url" content="${escapeHtml(url)}" />`,
    '<meta name="twitter:card" content="summary_large_image" />'
  );

  const cover = recipes.find((r) => r && r.image_url);
  if (cover) {
    tags.push(`<meta property="og:image" content="${escapeHtml(cover.image_url)}" />`);
  }

  // schema.org/ItemList — Google'a "bu bir liste sayfası" diyor. Tariflerin
  // KENDİ işaretlemesi burada tekrarlanmıyor: her tarifin kanonik sayfası
  // zaten var ve aynı Recipe'i iki yerde ilan etmek çelişkili sinyal olurdu.
  const itemList = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: data.title,
    description: data.description,
    url,
    numberOfItems: recipes.length,
    itemListElement: recipes.map((r, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: r.name,
      url: `${origin}${recipePath(r.id, r.name)}`,
    })),
  };
  tags.push(
    `<script type="application/ld+json">${
      JSON.stringify(itemList).replace(/</g, '\\u003c')}</script>`
  );

  return tags.join('\n  ');
}

/**
 * Etiketleri `recipe.html` şablonuna yerleştir.
 *
 * Statik <title> ÖNCE SİLİNİYOR: yoksa sayfada iki başlık kalır ve hangisinin
 * okunacağı kazıyıcıya göre değişir — bazı yerlerde tarif adı, bazı yerlerde
 * "Recipe — Recipe Assistant" görünürdü. Sayfa yine kusursuz çalıştığı için de
 * kimse fark etmezdi; o yüzden teste bağlı.
 *
 * Tarif ID'si de burada enjekte ediliyor: `/recipes/25500-slug` adresinde
 * sorgu dizisi YOK, yani `recipe.js`'in `params.get('id')` okuması boş dönerdi.
 */
function inject(template, headTags, globals) {
  // `globals`: sayfaya gömülecek window değişkenleri. Tarif sayfası
  // `__RECIPE_ID__`/`__RECIPE_DATA__`, koleksiyon sayfası
  // `__COLLECTION_SLUG__`/`__COLLECTION_DATA__` gönderiyor — enjeksiyon
  // mekanizması ikisi için de aynı, o yüzden ikiye kopyalanmıyor.
  //
  // ⚠️ `</script>` kaçışı BURADA DA ŞART, ve buradaki JSON-LD'dekinden
  // TEHLİKELİ: orası bir veri bloğu, burası ÇALIŞAN bir script. `<`
  // kaçırılmazsa tarif adının içindeki bir etiket script'i erken kapatır ve
  // kalan metin çalıştırılabilir HTML'e dönüşür.
  //
  // `undefined` değerler ATLANIYOR: yarım bir `window.__X__ = undefined`
  // istemcide "veri var" sanılıp sessizce boş sayfa üretirdi.
  const scripts = Object.entries(globals || {})
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([name, value]) =>
      `<script>window.${name} = ${JSON.stringify(value).replace(/</g, '\\u003c')};</script>`)
    .join('\n  ');

  const block = scripts ? `${headTags}\n  ${scripts}` : headTags;

  // ⚠️ `[^<]*` BİLEREK, `[\s\S]*?` DEĞİL. Gerçek bir <title> içinde asla `<`
  // olmaz; buna karşılık bir HTML YORUMU içinde geçen "<title>" kelimesi
  // (belge amaçlı) neredeyse her zaman peşinden başka etiket taşır. Gevşek
  // desen yorumdaki kelimeden GERÇEK </title>'a kadar her şeyi siliyordu:
  // yorumun kapanışını, `<!--seo-->` işaretini ve arkasından gelen <link>
  // etiketlerini kapanmamış bir yorumun içinde bırakıyordu — yani sayfa
  // stilsiz açılırdı. Testle yakalandı, teste bağlandı.
  const withoutTitle = template.replace(/[ \t]*<title>[^<]*<\/title>\n?/, '');

  if (withoutTitle.includes('<!--seo-->')) {
    return withoutTitle.replace('<!--seo-->', block);
  }
  // İşaret silinmişse sessizce başlıksız sayfa sunmak yerine </head>'in önüne
  // koy — özelliğin tamamı bu etiketlere bağlı, kaybolmasına izin verilemez.
  return withoutTitle.replace('</head>', `  ${block}\n</head>`);
}

module.exports = {
  escapeHtml,
  slugify,
  parseRecipePath,
  parseCollectionPath,
  recipePath,
  isoDuration,
  metaDescription,
  splitInstructions,
  jsonLd,
  buildHead,
  buildCollectionHead,
  inject,
};
