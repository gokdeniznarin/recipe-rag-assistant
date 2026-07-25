/**
 * Alışveriş listesi ↔ market köprüsü (Faz 19).
 *
 * İki iş: (1) İngilizce malzeme adını market araması için Türkçe'ye çevirmek,
 * (2) affiliate config'ini uygulayıp gidilecek URL'yi kurmak.
 *
 * NEDEN ÇEVİRİ: tarif verisi İngilizce (dataset öyle), ama Migros Türkçe —
 * "olive oil" araması boş döner, "zeytinyağı" döndürür. Sözlük yaklaşımı
 * bilinçli: malzeme adları tekrar eden sınırlı bir küme, tam çeviri servisine
 * (maliyet/kota) gerek yok. Eşleşmezse İngilizce ada düşülüyor (arama kötü
 * olur ama kırılmaz).
 *
 * SAF + node-test edilebilir: tarayıcı global'i kullanmıyor, config'i parametre
 * olarak alıyor. Alttaki module.exports yalnızca test içindir (tarayıcıda
 * `Stores` global'i klasik script paylaşımıyla kullanılıyor, Logger gibi).
 */
const Stores = (function () {
  // Anahtar İngilizce (küçük harf), değer Türkçe. Uzun anahtar önce eşleşir
  // (aşağıdaki longest-match): "chicken breast" > "chicken", "peanut butter" >
  // "butter", "tomato paste" > "tomato".
  const TR = {
    // Proteinler
    'chicken breast': 'tavuk göğsü', 'chicken thigh': 'tavuk but',
    'chicken': 'tavuk', 'ground beef': 'kıyma', 'ground turkey': 'hindi kıyma',
    'beef': 'dana eti', 'steak': 'biftek', 'pork': 'domuz eti', 'bacon': 'bacon',
    'ham': 'jambon', 'sausage': 'sosis', 'turkey': 'hindi', 'lamb': 'kuzu eti',
    'salmon': 'somon', 'tuna': 'ton balığı', 'shrimp': 'karides', 'fish': 'balık',
    'egg': 'yumurta', 'eggs': 'yumurta',
    // Süt ürünleri
    'cream cheese': 'krem peynir', 'sour cream': 'ekşi krema',
    'heavy cream': 'krema', 'cream': 'krema', 'milk': 'süt', 'butter': 'tereyağı',
    'parmesan': 'parmesan', 'mozzarella': 'mozzarella', 'cheddar': 'çedar peyniri',
    'feta': 'beyaz peynir', 'cheese': 'peynir', 'yogurt': 'yoğurt', 'yoghurt': 'yoğurt',
    // Sebze / meyve
    'green onion': 'yeşil soğan', 'onion': 'soğan', 'garlic': 'sarımsak',
    'tomato paste': 'salça', 'tomatoes': 'domates', 'tomato': 'domates',
    'potato': 'patates', 'carrot': 'havuç', 'celery': 'kereviz',
    'bell pepper': 'dolmalık biber', 'red pepper': 'kırmızı biber',
    'mushroom': 'mantar', 'spinach': 'ıspanak', 'lettuce': 'marul',
    'cucumber': 'salatalık', 'zucchini': 'kabak', 'eggplant': 'patlıcan',
    'broccoli': 'brokoli', 'cauliflower': 'karnabahar', 'corn': 'mısır',
    'peas': 'bezelye', 'green beans': 'taze fasulye', 'lemon': 'limon',
    'lime': 'lime', 'apple': 'elma', 'banana': 'muz', 'avocado': 'avokado',
    'ginger': 'zencefil', 'parsley': 'maydanoz', 'cilantro': 'kişniş',
    'basil': 'fesleğen', 'mint': 'nane', 'dill': 'dereotu',
    // Kiler
    'flour': 'un', 'brown sugar': 'esmer şeker', 'powdered sugar': 'pudra şekeri',
    'sugar': 'şeker', 'salt': 'tuz', 'black pepper': 'karabiber',
    'olive oil': 'zeytinyağı', 'vegetable oil': 'ayçiçek yağı', 'oil': 'sıvı yağ',
    'rice': 'pirinç', 'pasta': 'makarna', 'spaghetti': 'spagetti',
    'noodles': 'erişte', 'bread': 'ekmek', 'breadcrumbs': 'galeta unu',
    'baking powder': 'kabartma tozu', 'baking soda': 'karbonat',
    'vanilla': 'vanilya', 'honey': 'bal', 'vinegar': 'sirke',
    'soy sauce': 'soya sosu', 'tomato sauce': 'domates sosu',
    'chicken broth': 'tavuk suyu', 'chicken stock': 'tavuk suyu',
    'beef broth': 'et suyu', 'cornstarch': 'mısır nişastası', 'oats': 'yulaf',
    'cocoa': 'kakao', 'chocolate': 'çikolata', 'almonds': 'badem',
    'walnuts': 'ceviz', 'peanut butter': 'fıstık ezmesi', 'peanuts': 'yer fıstığı',
    'cinnamon': 'tarçın', 'cumin': 'kimyon', 'paprika': 'toz kırmızı biber',
    'oregano': 'kekik', 'thyme': 'kekik', 'bay leaf': 'defne yaprağı',
    'curry': 'köri', 'mustard': 'hardal', 'mayonnaise': 'mayonez',
    'ketchup': 'ketçap', 'wine': 'şarap', 'water': 'su', 'chickpeas': 'nohut',
    'lentils': 'mercimek', 'kidney beans': 'barbunya', 'beans': 'fasulye',
  };

  function _escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // Malzeme adı içinde geçen EN UZUN sözlük anahtarını bulup Türkçesini döner;
  // hiçbiri yoksa orijinal (İngilizce) adı döner. Kelime sınırı (\b) şart:
  // "ham" -> "graham" içinde eşleşmesin, "egg" -> yanlış yakalamasın.
  function toTurkish(name) {
    const low = (name || '').toLowerCase();
    let best = null;
    for (const key in TR) {
      if (best && key.length <= best.length) continue;
      if (new RegExp('\\b' + _escapeRe(key) + '\\b').test(low)) best = key;
    }
    return best ? TR[best] : (name || '');
  }

  // Arama terimini market URL'sine gömer, affiliate config'ini uygular.
  // cfg = window.SHOP. mode 'off' → düz arama; 'append' → parametre ekle;
  // 'wrap' → ağ redirect'iyle sar.
  function buildUrl(query, cfg) {
    cfg = cfg || {};
    const tmpl = cfg.searchUrl || 'https://www.google.com/search?q={q}';
    const base = tmpl.replace('{q}', encodeURIComponent(query));
    const aff = cfg.affiliate || {};
    if (aff.mode === 'append' && aff.append) return base + aff.append;
    if (aff.mode === 'wrap' && aff.wrap) return aff.wrap.replace('{url}', encodeURIComponent(base));
    return base;
  }

  return { TR, toTurkish, buildUrl };
})();

// Yalnızca node testi için (tarayıcıda `typeof module` undefined, zararsız).
if (typeof module !== 'undefined') module.exports = Stores;
