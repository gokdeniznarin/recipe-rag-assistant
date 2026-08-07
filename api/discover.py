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

🔴 DİYET ETİKETLİ KOLEKSİYON YOK — ve bu geçici bir eksik değil, ölçüme
dayanan bir karar. Etiketlerimiz kural bazlı tahmin ve iki hatası ölçüldü:
`vegetarian` 228 tarifte yanlış (içinde ham/sausage/prosciutto var —
`clean_data.py`'deki `land_meat` listesi eksik) ve `nut_free` Faz 15b'den beri
bilinen bir açık taşıyor. "Vegetarian Dinners" diye pinlenen bir listeye
jambonlu tarif koymak, kazanılacak trafikten çok daha pahalıya mal olur.
Etiketler düzeltilip yeniden ingestion yapılınca (adım A) buraya diyet bazlı
koleksiyonlar eklemek tek sözlük girdisi kadar iş.
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
}

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


def sort_key(card: dict):
    """
    Listeleme sırası: önce süresi bilinen ve KISA olanlar.

    Sıra keyfi bırakılamaz — ChromaDB `get` ekleme sırasında döndürüyor, yani
    liste veri her yeniden yüklendiğinde değişirdi. Bir pin aylarca dolaşıyor;
    indiği sayfanın kararlı olması gerekiyor.
    """
    minutes = card.get("total_time_min")
    if minutes is None:
        return (1, 0.0, card.get("name", ""))
    return (0, float(minutes), card.get("name", ""))
