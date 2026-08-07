/**
 * Pinterest/Google meta üretimi testi (Faz 29).
 *
 *   node scripts/test_seo_meta.js
 *
 * NEDEN VAR: bu etiketler sayfada GÖRÜNMÜYOR. Bozulduklarında uygulama
 * kusursuz çalışmaya devam eder, hiçbir hata çıkmaz — sadece pin'ler
 * görselsiz/başlıksız çıkar ve bunu ancak Pinterest'e bir şey pinleyip
 * bakınca fark ederiz. Yani gözle görülmeyen, sessizce bozulan bir yüzey:
 * `sw.js` harness'ının var olma sebebiyle birebir aynı.
 *
 * İki test özellikle kritik ve ikisi de "unutulunca sessiz" kategorisinde:
 *   - `suitableForDiet` YAZILMAMALI (ölçülmüş iki veri hatası var)
 *   - `</script>` kaçışı (JSON-LD'den HTML'e kaçış)
 */
const path = require('path');
const seo = require(path.join(__dirname, '..', 'frontend', 'api', '_seo.js'));

const ORIGIN = 'https://recipe-rag-assistant.vercel.app';

let pass = 0;
let failures = 0;
const check = (name, cond, extra) => {
  if (cond) { console.log('  ok    ' + name); pass++; }
  else { console.error('  FAIL  ' + name + (extra ? ' :: ' + extra : '')); failures++; }
};

// Gerçek veriden alınmış tarif (konteynerde `GET /api/recipes/25500`).
const RECIPE = {
  id: '25500',
  name: 'Cheesy Asparagus And Ham',
  category: 'Ham',
  total_time_min: 28.0,
  calories: 160.3,
  protein_content: 9.0,
  carbohydrate_content: 11.2,
  fat_content: 8.4,
  ingredients: ['butter', 'flour', 'milk', 'mild cheddar cheese', 'salt', 'pepper', 'asparagus', 'ham'],
  instructions: '1. Melt the butter. 2. Add the flour and stir. 3. Serve warm.',
  image_url: 'https://img.sndimg.com/food/image/upload/w_555/recipe.jpg',
  diet_tags: { nut_free: true, vegetarian: true, vegan: false },
};

// ── 1–4. Yol ayrıştırma: slug KİMLİK DEĞİL ───────────────
check('parses the id out of a full path',
      seo.parseRecipePath('/recipes/25500-cheesy-asparagus-and-ham') === '25500');
check('works without a slug at all',
      seo.parseRecipePath('/recipes/25500') === '25500');
// Tarif adı değişirse eski pin'ler ölmemeli: slug yanlış olsa da id tutuyor.
check('a stale slug still resolves',
      seo.parseRecipePath('/recipes/25500-some-old-name') === '25500');
check('rejects a non-recipe path',
      seo.parseRecipePath('/plan.html') === null);

// ── 5–7. Slug ───────────────────────────────────────────
check('slugifies a name', seo.slugify('Cheesy Asparagus And Ham') === 'cheesy-asparagus-and-ham');
check('drops punctuation and collapses gaps',
      seo.slugify("Grandma's  Best!! Pie") === 'grandma-s-best-pie');
check('an unsluggable name still yields a valid path',
      seo.recipePath('123', '???') === '/recipes/123');

// ── 8–10. ISO 8601 süre (schema.org'un istediği biçim) ───
check('minutes to ISO duration', seo.isoDuration(28) === 'PT28M');
check('over an hour splits correctly', seo.isoDuration(90) === 'PT1H30M');
check('zero yields no duration', seo.isoDuration(0) === '');

// ── 11–13. Açıklama ─────────────────────────────────────
const desc = seo.metaDescription(RECIPE);
check('description mentions the time', /28 minutes/.test(desc), desc);
check('description lists ingredients', /butter/.test(desc), desc);
check('description stays within the display limit', desc.length <= 156, String(desc.length));
// 🔴 Kalori çıplak bir sayı olarak yayınlanmıyor: veri setinde tabanı
// TUTARSIZ (medyan 309 kcal ama %6.9'u >1000, en yükseği 38.662 — bir kısmı
// porsiyon, bir kısmı tarifin tamamı) ve porsiyon sayısı ingest edilmedi.
// Bir arama sonucu özetinde "8024 calories" hem saçma hem yanıltıcı.
check('description never states a bare calorie count',
      !/calorie/i.test(desc) &&
      !/calorie/i.test(seo.metaDescription({ ...RECIPE, calories: 8024 })),
      desc);

// ── 14–17. JSON-LD ──────────────────────────────────────
const ld = seo.jsonLd(RECIPE, ORIGIN + '/recipes/25500-x');
check('is typed as a Recipe', ld['@type'] === 'Recipe');
check('carries ingredients', Array.isArray(ld.recipeIngredient) && ld.recipeIngredient.length === 8);
check('splits instructions into steps',
      ld.recipeInstructions.length === 3 && ld.recipeInstructions[0].text === 'Melt the butter.',
      JSON.stringify(ld.recipeInstructions));
// 🔴 `nutrition` YAYINLANMIYOR — `suitableForDiet` kararının aynısı.
// schema.org'un NutritionInformation'ı teamülen PORSİYON BAŞINA; bizim
// değerlerimizin tabanı belirsiz ve `RecipeServings` ingest edilmedi.
// Yayınlamak, Google'ın bunu tarif kartında GERÇEK olarak göstermesi demek.
check('NEVER publishes unverified nutrition',
      !ld.nutrition && !/NutritionInformation/.test(JSON.stringify(ld)));

// ── 18. 🔴 Diyet etiketi YAYINLANMIYOR ───────────────────
// Karar 2026-08-07. Etiketlerimiz kural bazlı tahmin ve İKİ ölçülmüş hatası var:
// `nut_free` ("Pine Nut and Almond Cookies" fıstıksız sayılıyor, Faz 15b) ve
// `vegetarian` (228 tarif etli ama vejetaryen işaretli). Arayüzde yanlarında
// "otomatik tahmin" uyarısı var; yapılandırılmış veride uyarı yeri YOK.
// Bu test, birinin iyi niyetle "veri zaten elimizde, ekleyelim" demesini durduruyor.
const rendered = seo.buildHead(RECIPE, ORIGIN, {});
check('NEVER publishes suitableForDiet',
      !/suitableForDiet/i.test(rendered) && !/GlutenFree|NutFree|Vegetarian/i.test(rendered));

// ── 19–23. <head> etiketleri ────────────────────────────
check('sets a per-recipe title', /<title>Cheesy Asparagus And Ham — Recipe Assistant<\/title>/.test(rendered));
check('sets og:image', new RegExp('og:image" content="' + RECIPE.image_url).test(rendered));
check('sets a canonical url',
      /rel="canonical" href="https:\/\/[^"]*\/recipes\/25500-cheesy-asparagus-and-ham"/.test(rendered));
check('og:url matches the canonical url',
      (rendered.match(/\/recipes\/25500-cheesy-asparagus-and-ham/g) || []).length >= 2);
check('embeds the JSON-LD block', /<script type="application\/ld\+json">\{/.test(rendered));

// ── 24. Görselsiz tarif: BOZUK etiket basmıyor ──────────
// Boş bir og:image, etiketin hiç olmamasından kötü: Pinterest sayfayı
// pinlenebilir sanıp görselsiz bir pin üretir.
const noImage = seo.buildHead({ ...RECIPE, image_url: '' }, ORIGIN, {});
check('omits og:image entirely when there is no image', !/og:image/.test(noImage));

// ── 25–26. noindex varsayılanı ──────────────────────────
// Yön bilinçli: indekse EKLEMEK kolay, indeksten ÇIKARMAK aylar sürüyor.
check('defaults to noindex', /name="robots" content="noindex/.test(rendered));
check('curated recipes can be opened up',
      !/noindex/.test(seo.buildHead(RECIPE, ORIGIN, { indexable: true })));

// ── 27–29. 🔴 Kaçış ─────────────────────────────────────
// Veri seti 9.795 tarif adı taşıyor ve içlerinde tırnak/ve-işareti geçenler var.
const quoted = seo.buildHead(
  { ...RECIPE, name: 'Mom\'s "Best" Pie & Cream' }, ORIGIN, {});
check('escapes quotes so the attribute cannot break out',
      !/content="[^"]*"[^"=>]*"/.test(quoted.split('\n').find((l) => l.includes('og:title'))),
      quoted.split('\n').find((l) => l.includes('og:title')));
check('escapes ampersands', /&amp;/.test(quoted));

// JSON string'inin İÇİNDE bile olsa, ham "</script>" etiketi ERKEN KAPATIR ve
// kalan metin çalıştırılabilir HTML'e dönüşür. JSON.stringify bunu kaçırmaz.
const hostile = seo.buildHead(
  { ...RECIPE, name: 'Pie</script><img src=x onerror=alert(1)>' }, ORIGIN, {});
check('no raw </script> can escape the JSON-LD block',
      !/<\/script><img/.test(hostile),
      hostile.slice(hostile.indexOf('ld+json'), hostile.indexOf('ld+json') + 160));

// ── 30–34. Şablona enjeksiyon (GERÇEK recipe.html'e karşı) ──
const fs = require('fs');
const template = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'recipe.html'), 'utf8');

check('recipe.html still carries the injection marker', template.includes('<!--seo-->'),
      'işaret silinmiş — etiketler </head> yedeğine düşer');

const page = seo.inject(template, rendered, { __RECIPE_ID__: '25500' });
// İki <title> kalsaydı hangisinin okunacağı kazıyıcıya göre değişirdi ve
// sayfa kusursuz çalışmaya devam ettiği için kimse fark etmezdi.
check('exactly one <title> survives',
      (page.match(/<title>/g) || []).length === 1,
      String((page.match(/<title>/g) || []).length));
check('the surviving title is the recipe one',
      /<title>Cheesy Asparagus And Ham/.test(page));
// `/recipes/25500-slug` adresinde sorgu dizisi yok; bu olmadan recipe.js'in
// `params.get('id')` okuması boş döner ve sayfa gövdesi hiç dolmaz.
check('injects the recipe id for the client', /__RECIPE_ID__ = "25500"/.test(page));

const noMarker = seo.inject(
  template.replace('<!--seo-->', ''), rendered, { __RECIPE_ID__: '25500' });
check('falls back to </head> when the marker is gone',
      /og:title/.test(noMarker) && noMarker.indexOf('og:title') < noMarker.indexOf('</head>'));

// ── 35–37. 🔴 Enjeksiyon şablonun GERİ KALANINI bozmuyor ──
// İlk sürüm bozuyordu ve bunu SAYMA testleri kaçırdı: yorumun içine yazılmış
// belge amaçlı bir "<title>" kelimesi, gevşek regex yüzünden gerçek </title>'a
// kadar her şeyi sildi — `<!--seo-->` işaretini ve arkasındaki <link>
// etiketlerini kapanmamış bir yorumun içinde bıraktı. Sayfa stilsiz açılırdı,
// ve etiketler yedek yoldan yine basıldığı için testler YEŞİL kalmıştı.
check('the stylesheet link survives injection',
      /<link rel="stylesheet" href="css\/style\.css"/.test(page));
check('every HTML comment is closed',
      (page.match(/<!--/g) || []).length === (page.match(/-->/g) || []).length,
      `${(page.match(/<!--/g) || []).length} açılış / ${(page.match(/-->/g) || []).length} kapanış`);
// İşaret duruyorsa yedek yola HİÇ düşülmemeli — düşülürse yukarıdaki testler
// yine geçer ama şablonun bir kısmı yenmiş olur.
check('the marker path is used, not the fallback',
      !page.includes('<!--seo-->') && page.indexOf('og:title') < page.indexOf('preconnect'));

// ── 38–39. Asıl koruma: bir YORUM içindeki etiket enjeksiyonu bozmamalı ──
// Yukarıdaki testler gerçek recipe.html'e bakıyor, yani bugünkü yorumun ne
// yazdığına bağlılar. Bu ikisi kuralın KENDİSİNİ ölçüyor: biri ileride
// dosyaya belge amaçlı bir etiket yazarsa (tam olarak bunu yapmıştım) sayfa
// bozulmamalı. Sentetik şablon kullanılıyor ki koruma recipe.html'in
// bugünkü metninden bağımsız olsun.
const trap = [
  '<head>',
  '  <!-- burada belge amacli bir <title> etiketi geciyor, sonra </head> de -->',
  '  <!--seo-->',
  '  <title>Static — Recipe Assistant</title>',
  '  <link rel="stylesheet" href="css/style.css" />',
  '</head>',
].join('\n');
const trapped = seo.inject(trap, '<title>Real</title>', {});
check('a tag written inside a comment does not eat the template',
      /<link rel="stylesheet"/.test(trapped) &&
      (trapped.match(/<!--/g) || []).length === (trapped.match(/-->/g) || []).length,
      trapped);
check('the static title is still the one removed',
      /<title>Real<\/title>/.test(trapped) && !/Static — Recipe/.test(trapped));

// ── 40–43. Gömülü tarif verisi (Faz 29, adım 3) ──────────
// Bunun amacı ağ turunu kurtarmak DEĞİL: `apiRequest` önce `authReady`'yi
// bekliyor ve o bekleme bir sayfanın ilk isteğinde canlıda ~975 ms ölçüldü
// (Faz 13b). Pinterest'ten gelen ziyaretçi için bu, hiçbir şey görmeden
// geçen bir saniye demekti.
const withData = seo.inject(template, rendered, { __RECIPE_ID__: '25500', __RECIPE_DATA__: RECIPE });
check('embeds the recipe payload', /__RECIPE_DATA__ = \{/.test(withData));
check('the embedded payload is valid JSON', (() => {
  const m = /__RECIPE_DATA__ = ([\s\S]*?);<\/script>/.exec(withData);
  try { return JSON.parse(m[1]).name === RECIPE.name; } catch { return false; }
})());
// Veri yoksa (API erişilemedi) blok HİÇ basılmamalı — boş/yarım bir
// `window.__RECIPE_DATA__` istemcide sessizce boş sayfa üretirdi.
check('omits the payload entirely when there is no recipe',
      !/__RECIPE_DATA__/.test(seo.inject(template, rendered, { __RECIPE_ID__: '25500', __RECIPE_DATA__: null })));
// JSON-LD bir VERİ bloğu, bu ise ÇALIŞAN bir script — kaçış burada daha kritik.
const hostilePayload = seo.inject(
  template, rendered, { __RECIPE_DATA__: { ...RECIPE, name: 'X</script><img src=x onerror=alert(1)>' } });
check('no raw </script> can escape the payload block',
      !/<\/script><img/.test(hostilePayload));

// ── 44–54. Koleksiyon iniş sayfaları (Faz 29, adım 4) ────
const COLLECTION = {
  slug: '30-minute-dinners',
  title: '30-Minute Dinners',
  description: 'Real dinners you can get on the table in half an hour.',
  recipes: [
    { id: '25500', name: 'Cheesy Asparagus And Ham', total_time_min: 28, image_url: 'https://img.example/a.jpg' },
    { id: '170022', name: 'Mexican Chocolate Pound Cake', total_time_min: 70, image_url: '' },
  ],
};

check('parses a collection slug', seo.parseCollectionPath('/discover/30-minute-dinners') === '30-minute-dinners');
check('tolerates a trailing slash', seo.parseCollectionPath('/discover/cookies/') === 'cookies');
check('rejects a recipe path', seo.parseCollectionPath('/recipes/25500-x') === null);

const collHead = seo.buildCollectionHead(COLLECTION, ORIGIN, {});
check('sets the collection title', /<title>30-Minute Dinners — Recipe Assistant<\/title>/.test(collHead));
check('sets a canonical url', /canonical" href="[^"]*\/discover\/30-minute-dinners"/.test(collHead));
// Kendi tipografik pin görselimiz burada KULLANILAMAZ: bu etiket sayfayı
// BAŞKASI paylaştığında ne görüneceğini belirliyor, orada gerçek bir yemek
// fotoğrafı tek anlamlı seçenek. İlk GÖRSELİ OLAN tarif seçiliyor.
check('uses the first recipe image as the cover',
      /og:image" content="https:\/\/img\.example\/a\.jpg"/.test(collHead));
// Tarif sayfalarının TERSİ: koleksiyonlar 12 tane ve elle küratörlü, yani
// "9.795 sayfa kamu malı metin" riski burada yok.
check('collections are indexable by default', !/noindex/.test(collHead));
check('but can be closed off explicitly',
      /noindex/.test(seo.buildCollectionHead(COLLECTION, ORIGIN, { indexable: false })));

const itemList = JSON.parse(/ld\+json">([\s\S]*?)<\/script>/.exec(collHead)[1]);
check('marks the page up as an ItemList',
      itemList['@type'] === 'ItemList' && itemList.numberOfItems === 2);
// Tariflerin KENDİ Recipe işaretlemesi burada tekrarlanmıyor: her tarifin
// kanonik sayfası zaten var, aynı Recipe'i iki yerde ilan etmek Google'a
// çelişkili sinyal gönderirdi.
check('does not re-declare the recipes themselves',
      !/"@type":"Recipe"/.test(JSON.stringify(itemList)));
check('links each item to its canonical recipe url',
      itemList.itemListElement[0].url === `${ORIGIN}/recipes/25500-cheesy-asparagus-and-ham`,
      itemList.itemListElement[0].url);

// ── 55–57. discover.html şablonu ────────────────────────
const discoverTpl = fs.readFileSync(
  path.join(__dirname, '..', 'frontend', 'discover.html'), 'utf8');
check('discover.html carries the injection marker', discoverTpl.includes('<!--seo-->'));

const discoverPage = seo.inject(discoverTpl, collHead, {
  __COLLECTION_SLUG__: COLLECTION.slug,
  __COLLECTION_DATA__: COLLECTION,
});
check('exactly one <title> survives on the collection page',
      (discoverPage.match(/<title>/g) || []).length === 1,
      String((discoverPage.match(/<title>/g) || []).length));
check('embeds the collection payload',
      /__COLLECTION_DATA__ = \{/.test(discoverPage) &&
      /__COLLECTION_SLUG__ = "30-minute-dinners"/.test(discoverPage));

console.log(failures === 0
  ? `\nseo meta checks passed (${pass})`
  : `\n${failures} problem(s)`);
process.exit(failures === 0 ? 0 : 1);
