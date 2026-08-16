"""
Küratörlü, herkese açık tarif koleksiyonları (Faz 29).

NE İŞE YARIYOR: Pinterest'te pinlenen şey tek bir tarif değil, bir LİSTE
("30 Minute Dinners"). Pin'in indiği yer burası; oradan tek tek tariflere
geçiliyor. Yani bu modül büyüme hunisinin ilk basamağı.

⚡ FİLTRE, ARAMA DEĞİL — ve fark 2000 kat: koleksiyonlar ChromaDB'nin metadata
`where` filtresiyle çözülüyor (`collection.get`), semantic arama ile değil
(`collection.query`). Aynı konteynerde ölçülmüştü: `get` **2.6 ms**, `query`
**6.4 sn** — çünkü query sorgu metnini ONNX ile embed ediyor ve Render'da
0.1 vCPU var (Faz 17). Bir iniş sayfasının her ziyaretinde 6 saniye ödemek
kabul edilemezdi.

İkinci kazanç DETERMİNİZM: aynı slug her zaman aynı listeyi veriyor. Semantic
arama olsaydı sonuçlar model/veri değişiminde kayardı, oysa bir pin aylarca
dolaşıyor ve indiği sayfanın kararlı olması gerekiyor.

⚖️ DİYET ETİKETLERİNDE ÇİZİLEN SINIR — ve bu ikiye ayrılıyor:

  **TERCİH** (vegetarian, vegan, pescatarian) → koleksiyon KURULABİLİR.
  Adım A'da düzeltildi ve ölçüldü: içinde et geçen "vejetaryen" tarif sayısı
  **228 → 0**, fıstık içeren "nut_free" tarif sayısı **0**. Yanlış bir etiket
  burada can sıkar, zarar vermez.

  **ALERJEN** (gluten_free, dairy_free, nut_free) → koleksiyon KURULMAZ.
  Ölçüm iyileşti ama etiketler hâlâ KURAL BAZLI TAHMİN, ve buradaki hatanın
  sonucu kategorik olarak farklı: çölyak hastası ya da fıstık alerjisi olan
  biri için yanlış bir "Nut-Free Desserts" listesi sağlık riski. Uygulamanın
  içinde bu etiketlerin yanında "otomatik tahmin" uyarısı var; Pinterest'te
  pinlenen bir koleksiyon başlığında o uyarıyı basacak yer yok.

Aynı ayrım `_seo.js`'te de var: `suitableForDiet` hiçbir koşulda yayınlanmıyor.
"""

# Her koleksiyon: ChromaDB metadata filtresi + sunum metni.
# `where` doğrudan `collection.get`'e gidiyor — yalnızca skaler karşılaştırma
# destekleniyor (ChromaDB metadata'da liste tutamıyor), o yüzden malzeme
# bazlı koleksiyon YOK: "chicken içerenler" bir alt-dizi araması ister ve
# `where` bunu ifade edemez.
COLLECTIONS = {
    "30-minute-dinners": {
        "title": "30-Minute Dinners",
        "description": "Real dinners you can get on the table in half an hour.",
        "where": {
            "$and": [
                {"total_time_min": {"$lte": 30}},
                {"category": {"$in": ["One Dish Meal", "Chicken", "Chicken Breast", "Meat", "Pork"]}},
            ]
        },
    },
    "15-minute-recipes": {
        "title": "15-Minute Recipes",
        "description": "For the nights when cooking has to be quick.",
        "where": {"total_time_min": {"$lte": 15}},
    },
    "easy-desserts": {
        "title": "Easy Desserts",
        "description": "Sweet things that do not take an afternoon.",
        "where": {"$and": [{"category": {"$eq": "Dessert"}}, {"total_time_min": {"$lte": 45}}]},
    },
    "breakfast-ideas": {
        "title": "Breakfast Ideas",
        "description": "Ways to start the day that are not cereal.",
        "where": {"category": {"$eq": "Breakfast"}},
    },
    "chicken-dinners": {
        "title": "Chicken Dinners",
        "description": "The weeknight staple, done a lot of different ways.",
        "where": {"category": {"$in": ["Chicken", "Chicken Breast"]}},
    },
    "one-pot-meals": {
        "title": "One-Pot Meals",
        "description": "Everything in one dish, and one dish to wash.",
        "where": {"category": {"$eq": "One Dish Meal"}},
    },
    "homemade-bread": {
        "title": "Homemade Bread",
        "description": "Loaves, quick breads and everything in between.",
        "where": {"category": {"$in": ["Breads", "Yeast Breads", "Quick Breads"]}},
    },
    "cookies": {
        "title": "Cookies",
        "description": "Drop cookies, bars, and the rest of the jar.",
        "where": {"category": {"$in": ["Drop Cookies", "Bar Cookie"]}},
    },
    "vegetable-sides": {
        "title": "Vegetable Sides",
        "description": "The part of the plate that usually gets ignored.",
        "where": {"category": {"$eq": "Vegetable"}},
    },
    "potato-recipes": {
        "title": "Potato Recipes",
        "description": "Roasted, mashed, baked and fried.",
        "where": {"category": {"$eq": "Potato"}},
    },
    "lunch-and-snacks": {
        "title": "Lunch & Snacks",
        "description": "Midday food worth looking forward to.",
        "where": {"category": {"$eq": "Lunch/Snacks"}},
    },
    "drinks": {
        "title": "Drinks",
        "description": "Hot, cold, and everything you can put in a glass.",
        "where": {"category": {"$eq": "Beverages"}},
    },
    # Adım A'dan SONRA eklendi. Pinterest'te en çok aranan iki başlık ve
    # düzeltmeden önce kurulamazlardı: 228 tarif etli olduğu hâlde
    # vejetaryen etiketliydi.
    "vegetarian-dinners": {
        "title": "Vegetarian Dinners",
        "description": "Meat-free meals that are actually dinner, not a side salad.",
        "where": {
            "$and": [
                {"vegetarian": {"$eq": True}},
                {"category": {"$in": ["One Dish Meal", "Vegetable", "Potato", "Lunch/Snacks"]}},
            ]
        },
    },
    "vegan-recipes": {
        "title": "Vegan Recipes",
        "description": "No meat, no dairy, no eggs — and nothing that tastes like a compromise.",
        # ⚠️ KATEGORİ FİLTRESİ OPSİYONEL DEĞİL — kardeşi `vegetarian-dinners`'ta
        # baştan vardı, burada unutulmuştu ve sonucu ölçüldü (2026-08-17):
        # filtresiz hâlde 1.762 vegan tarifin ilk 24'ü ne gelirse o basılıyordu,
        # yani sayfanın tepesinde İKİ KOKTEYL, bir salsa ve bir ekşi maya
        # başlatıcısı vardı. Pinterest'ten "vegan yemek" için gelen ziyaretçiye
        # koşulan sayfa buydu. Filtreyle liste gerçek yemeğe dönüyor (marul
        # dürümü, portobello sandviç, tofu meatloaf, barbekü mercimek).
        # Yan kazanç: `Liver Bread` (kategorisi `< 30 Mins`) kendiliğinden düştü.
        # ⚠️ `Vegetable`/`Potato`/`Lunch/Snacks` BİLEREK YOK — ölçüldü: o üç
        # kategori garnitür ve meze ağırlıklı (`Vegetable` tek başına 194
        # tarif) ve sayfayı jicama çubuğu, lahana salatası, turşu salatalığa
        # çeviriyordu. Vejetaryen sayfasında aynı kategoriler kalabiliyor
        # çünkü orada havuz çok daha geniş; vegan havuzu dar olduğu için
        # garnitürler oranı ele geçiriyor.
        "where": {
            "$and": [
                {"vegan": {"$eq": True}},
                {"category": {"$in": ["One Dish Meal", "Beans", "Black Beans", "Rice",
                                      "Curries", "Stew", "Chowders", "Lentil",
                                      "Soy/Tofu", "Grains", "Pasta Shells"]}},
            ]
        },
    },
}

# Yanlış etiketlenmiş tarifler için 2026-08-17'de GEÇİCİ bir kara liste vardı
# (Liver Bread, Crockpot Carñitas, Kansas City Dogs, Hot Dog Bake, Octopus).
# Aynı gün yapılan yeniden ingestion kök sebebi kapattı — `clean_data.py`'deki
# et/deniz ürünü/yumurta kelime listeleri genişletildi ve aksan katlama eklendi
# — böylece beşi de kaynağında düzeldi ve liste kaldırıldı. Boş bırakılıyor
# çünkü `main.py` limiti buna göre hesaplıyor; ileride yine gerekirse yeri hazır.
EXCLUDED_IDS = frozenset()

# Bir sayfada gösterilecek tarif sayısı. 24 bilinçli: Pinterest'ten gelen
# ziyaretçi taramak için geliyor, ama sayfayı sonsuz uzatmak hem yükleme
# süresini hem de gömülü verinin boyutunu şişirir.
PAGE_SIZE = 24


def get_definition(slug: str) -> dict | None:
    """Koleksiyon tanımı, yoksa None."""
    return COLLECTIONS.get(slug)


def list_definitions() -> list[dict]:
    """Dizin sayfası için hafif liste (tarifler olmadan)."""
    return [
        {"slug": slug, "title": entry["title"], "description": entry["description"]}
        for slug, entry in COLLECTIONS.items()
    ]


# Ağırlıklı puanın "önceki gözlem" ağırlığı. 5 yorum = veri setinin genel
# ortalaması kadar kanıt sayılıyor.
RATING_PRIOR_COUNT = 5
# Veri setinin genel puan ortalaması (9.795 tarifte ölçüldü: 4.73). Puanı
# olmayan ya da az yorumlu tarifler buraya çekiliyor.
RATING_PRIOR_MEAN = 4.73


def quality_score(card: dict) -> float:
    """Ağırlıklı puan — IMDB'nin klasik formülü.

        (v / (v+m)) * R  +  (m / (v+m)) * C

    ⚠️ HAM PUANLA SIRALAMAK YANLIŞ OLURDU ve bu ölçüldü: veri setinde tek
    yorumlu bir sürü 5.0 var, oysa `Baja Black Beans, Corn and Rice`
    **247 yorumla** 5.0 tutuyor. Ham puan ikisini eşit sayar ve sayfanın
    tepesine kimsenin denemediği tarifi koyar — sosyal kanıt tam da burada,
    yani bir iniş sayfasında, en çok gereken şey.

    Puanı olmayan tarif (veri setinin ~%17'si) 0 değil ORTALAMA sayılıyor:
    "puanlanmamış" ile "kötü" aynı şey değil, ama az yorumlu bir kayıt da
    çok yorumlu iyi bir kaydın önüne geçmemeli.
    """
    rating = float(card.get("rating") or 0.0)
    votes = int(card.get("review_count") or 0)
    if rating <= 0:
        return RATING_PRIOR_MEAN * 0.5   # hiç puanlanmamış: ortalamanın altı
    m = RATING_PRIOR_COUNT
    return (votes / (votes + m)) * rating + (m / (votes + m)) * RATING_PRIOR_MEAN


def sort_key(card: dict):
    """
    Listeleme sırası: EN BEĞENİLEN önce (ağırlıklı puan), eşitlikte kısa olan.

    ⚠️ ÖNCEDEN SÜREYE GÖRE ARTAN sıralanıyordu ve bunun bedeli ölçüldü: en
    kısa tarif her zaman en az "yemek" olan şey oluyordu, yani sayfa 5
    dakikalık bir atıştırmalıkla açılıyordu. Aynı havuzda 247 yorumlu 5.0
    puanlı bir yemek dururken.

    Sıra hâlâ TAMAMEN DETERMİNİSTİK — asıl şart oydu: bir pin aylarca
    dolaşıyor, indiği sayfanın kararlı olması gerekiyor. Ad son ayırıcı
    olarak duruyor ki eşit puan+süredeki tarifler de sabit sırayla gelsin.
    """
    minutes = card.get("total_time_min")
    minutes = float(minutes) if minutes is not None else 10_000.0
    return (-quality_score(card), minutes, card.get("name", ""))
