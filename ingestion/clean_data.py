import pandas as pd
import re
import html
import unicodedata

# ============ CLEANING FUNCTIONS ============

def clean_text(text):
    """HTML kaçış karakterlerini temizler (&ldquo; → " gibi)"""
    if pd.isna(text):
        return ""
    return html.unescape(str(text))

def parse_ingredients(raw_string):
    """c("chicken", "pepper") formatını ["chicken", "pepper"] listesine çevirir"""
    if pd.isna(raw_string):
        return []
    return re.findall(r'"([^"]+)"', raw_string)

def parse_instructions(raw_string):
    """c("adım1", "adım2") formatını numaralı, okunaklı bir metne çevirir"""
    if pd.isna(raw_string):
        return ""
    steps = re.findall(r'"([^"]+)"', raw_string)
    return " ".join(f"{i+1}. {step}" for i, step in enumerate(steps))

def parse_image_url(raw_string):
    """R vector formatındaki görsel listesinden İLK URL'yi alır.

    Ham veri: c("https://.../a.jpg", "https://.../b.jpg") — bir tarifin birden
    çok fotoğrafı olabiliyor, kart için ilki yeterli. Görsel yoksa alan
    "character(0)" ya da boş geliyor; o durumda boş dize dönüyor.

    NOT: miktar kolonu (RecipeIngredientQuantities) bilerek KULLANILMIYOR —
    ölçüldü: malzeme ve miktar dizileri kaynak veride yalnızca %27 hizalı,
    yani eşleştirme %73 yanlış miktar gösterirdi. Görsel alanı tek başına
    durduğu için bu sorundan etkilenmiyor.
    """
    if pd.isna(raw_string):
        return ""
    text = str(raw_string)
    urls = re.findall(r'"(https?://[^"]+)"', text)
    if urls:
        return urls[0]
    # Bazı satırlarda tırnaksız tek URL olabiliyor
    stripped = text.strip()
    return stripped if stripped.startswith("http") else ""


def has_image(raw_string):
    """Tarifin kullanılabilir bir görseli var mı (örnekleme filtresi)."""
    return bool(parse_image_url(raw_string))


def parse_duration_to_minutes(iso_duration):
    """PT24H45M formatını dakikaya çevirir (örn: 1485)"""
    if pd.isna(iso_duration):
        return None
    
    hours = re.search(r'(\d+)H', iso_duration)
    minutes = re.search(r'(\d+)M', iso_duration)
    
    total_minutes = 0
    if hours:
        total_minutes += int(hours.group(1)) * 60
    if minutes:
        total_minutes += int(minutes.group(1))
    
    return total_minutes if total_minutes > 0 else None

def parse_servings(value):
    """
    `RecipeServings` → int (bilinmiyorsa 0).

    Veri setinde ~%36'sı boş, ayrıca "4.0" gibi ondalıklı geliyor. Uçuk
    değerler eleniyor: veri setinde 1'den küçük ve 100'den büyük porsiyon
    sayıları veri hatası (porsiyon başına bölme yapılırsa saçma sayı üretir).
    0 dönmek "bilinmiyor" demek — TAHMİN ÜRETİLMİYOR, çünkü uydurulmuş bir
    porsiyon sayısı, bugün yayınlamadığımız besin değerlerini yanlış bir
    güvenle yayınlanabilir gösterirdi.
    """
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= 100 else 0


def fold_accents(text):
    """Küçük harfe indirir ve aksanları düşürür: `Carñitas` -> `carnitas`.

    NFD ayrıştırması harfi ve birleşen işareti ayırıyor; `Mn` (nonspacing mark)
    kategorisindekileri atınca geriye ASCII taban harf kalıyor. Diyet
    etiketlemesindeki bütün metin karşılaştırmaları buradan geçmeli.
    """
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text).lower())
        if unicodedata.category(c) != "Mn"
    )


def has_word(text, words):
    """
    `words`'ten herhangi biri `text` içinde TAM KELİME olarak geçiyor mu?

    ⚠️ DÜZ ALT-DİZİ ARAMASI KULLANILAMAZ ve bunun bedeli ölçüldü (Faz 29):
    `"ham" in text` kontrolü 9.795 tarifte **graham** (101 kez — graham
    cracker'lı tatlılar), champagne (11), chambord (9), bechamel (3) ve
    bahama (3) kelimelerine takılıyordu. Yani "ham"i et listesine düz
    eklemek, 101 tatlıyı "et içeriyor" saymak demekti — düzeltmeye
    çalıştığımızdan daha kötü bir hata.

    Çoğul hâller de eşleşiyor (`\\bhams?\\b`): veri setinde hem "sausage"
    hem "sausages" geçiyor.
    """
    return any(re.search(r"\b" + re.escape(w) + r"s?\b", text) for w in words)


def extract_diet_tags(ingredients_list, category="", name=""):
    """Malzeme, kategori VE tarif adı üzerinden diyet etiketi çıkarır"""
    tags = []
    # ⚠️ AKSAN KATLAMA ŞART. `Crockpot Carñitas` **ñ** ile yazılmış ve
    # `\bcarnitas?\b` onu bulamıyor — tarif domuz eti içerdiği hâlde vegan
    # etiketliydi. Bu, kelime listesinden BAĞIMSIZ bir eksiklik: liste ne
    # kadar uzarsa uzasın, aksanlı yazım hepsini atlatır.
    ingredients_text = fold_accents(" ".join(ingredients_list))
    category_lower = fold_accents(category)
    name_lower = fold_accents(name)

    # Tarif adında "vegan/vegetarian/plant-based" gibi bir işaret var mı?
    # Varsa adındaki et kelimeleri bitki bazlı taklit üründür (örn. "Vegan Chicken Nuggets")
    # `tofu` Faz 29'da eklendi: aşağıda `meatloaf`/`meatball` et listesine
    # girince "Tofu Meatloaf" yanlışlıkla etli sayılıyordu. Taklit ürünlerin
    # en yaygın işareti bu.
    # ⚠️ `veggie` FAZ 29'DA ÇIKARILDI. Bu liste "addaki et kelimesi taklit
    # üründür" demek için var (örn. "Vegan Chicken Nuggets"), ama `veggie`
    # o iddiayı taşımıyor — çoğunlukla sadece "sebzeli" demek. Ölçüldü:
    # adında hem "veggie" hem et geçen 9 tarif var ve 3'ü bu yüzden
    # vejetaryen sayılıyordu (`Sausage and Veggie Skillet Supper`,
    # `Quinoa With Veggies and Grilled Chicken Breast`, `Veggie Chicken Wraps`).
    # Gerçek taklit ürünler ("Veggie Burger") adlarında zaten et kelimesi
    # taşımıyor, yani çıkarmanın ölçülen bir bedeli yok.
    plant_based_signals = ["vegan", "vegetarian", "plant-based", "plant based",
                           "meatless", "meat-free", "tofu",
                           # 2026-08-17: `steak` et listesine girdi ve ölçümde
                           # TEK bir yanlış pozitif üretti — sebzeden yapılan
                           # "steak"ler. Kelimeyi listeden çıkarmak 42 gerçek
                           # biftekli tarifi vejetaryen bırakırdı; onun yerine
                           # bu bir avuç ifade taklit ürün sayılıyor.
                           "cabbage steak", "cauliflower steak",
                           "eggplant steak", "portobello steak",
                           "portabella steak", "mushroom steak"]
    is_plant_based_by_name = any(sig in name_lower for sig in plant_based_signals)
    
    # --- Gluten-free ---
    # ⚠️ Kelime sınırlı eşleştirmeye geçildi (Faz 29), ve bu bir DÜZELTME:
    # düz alt-dizi aramasında "oat" kelimesi **"goat"** içinde eşleşiyordu,
    # yani keçi peyniri kullanan her tarif "gluten içeriyor" sayılıyordu.
    # Karşılığında "oatmeal"/"rolled oats" gibi bileşik hâllerin listeye
    # AÇIKÇA yazılması gerekiyor — kelime sınırı onları da eliyor.
    gluten_words = ["flour", "wheat", "bread", "pasta", "barley", "rye",
                    "spaghetti", "macaroni", "noodle", "roll", "rolled oats",
                    "dough", "biscuit", "cracker", "tortilla", "bun", "bagel",
                    "cereal", "oat", "oatmeal", "couscous", "breadcrumb",
                    "bread crumb", "crouton", "pretzel", "pastry", "pita",
                    "pizza", "semolina", "farro", "bulgur", "seitan", "orzo",
                    "penne", "linguine", "fettuccine", "lasagna", "ravioli"]
    gluten_categories = ["bread", "pasta", "pizza", "pie", "cookie", "cake", "pastry"]
    is_labeled_gf = "gluten" in category_lower and "free" in category_lower

    has_gluten = (has_word(ingredients_text, gluten_words)
                  or any(c in category_lower for c in gluten_categories)
                  or has_word(name_lower, gluten_words)) and not is_labeled_gf
    if not has_gluten:
        tags.append("gluten_free")
    
    # --- Et / deniz ürünü ---
    #
    # 🔴 BU LİSTE FAZ 29'DA GENİŞLETİLDİ. Öncesinde yalnızca
    # ["chicken","beef","pork","meat","bacon","turkey","lamb"] vardı ve
    # ölçüldü ki **228 tarif** vejetaryen etiketliyken içinde et geçiyordu:
    # ham 123, sausage 68, prosciutto 13, pancetta 7, veal/duck 10,
    # salami/venison 7. Adında açıkça "Ham" geçen tarif bile vejetaryen
    # sayılıyordu (`Cheesy Asparagus And Ham`, id 25500).
    #
    # `hamburger` AYRI bir girdi: kelime sınırı yüzünden `\bhams?\b` onu
    # yakalamıyor (46 tarifte geçiyor ve hepsi gerçekten et).
    land_meat = [
        "chicken", "beef", "pork", "meat", "bacon", "turkey", "lamb",
        "ham", "hamburger", "sausage", "kielbasa", "prosciutto", "pancetta", "salami",
        "pepperoni", "veal", "duck", "venison", "chorizo", "bratwurst",
        "sirloin", "brisket", "ribeye", "pastrami", "mutton", "goose",
        # ⚠️ BİLEŞİK HÂLLER AYRI YAZILMAK ZORUNDA. Kelime sınırına geçince
        # `\bmeats?\b` artık "meatball"/"meatloaf" içinde eşleşmiyor ve ölçüm
        # bunu yakaladı: `Meatball Casserole` vejetaryen sayılmaya başlamıştı.
        # (Düz alt-dizi aramasının tesadüfen doğru yaptığı tek şey buydu.)
        "meatball", "meatloaf",
        # ── 2026-08-17'de eklenenler ────────────────────────────────
        # Hepsi gerçek veride ölçüldü; hiçbiri tahminle eklenmedi. Bunlar
        # herkese açık "Vegan Recipes" sayfasında görünüyordu.
        "liver",      # 9 eşleşme; `Liver Bread`in malzemesi düpedüz `liver`.
                      # `\blivers?\b` "liverwurst"a TAKILMIYOR (sonrasında
                      # kelime sınırı yok) — ayrıca yazmaya gerek kalmadı.
        "carnitas",   # 9; `Crockpot Carñitas` ÑILE yazılmış → aksan katlama şart
        "brat",       # 2 (`Beer Brats`, `BBQ Brats 'n Beer`). `bratwurst`
                      # listede vardı ama kısaltması yoktu.
        "bologna",    # 2; `\bbolognas?\b` "bolognese"e takılmıyor
        "quail", "pheasant", "spam", "gizzard", "oxtail",   # 1-2'şer, hepsi gerçek
        # ⚠️ `steak` EN BÜYÜK EKLEME (148 eşleşme) ve hafızada "dikkat" notu
        # vardı. Ölçüldü: adında geçen 115 tarifin yalnızca **1'i** etsiz
        # (`Garlic Rubbed Roasted Cabbage Steaks`) — o da aşağıdaki bitkisel
        # sinyalle korunuyor. Geri kalan "şüpheli"ler ya gerçek et (Salisbury
        # Steak, Cube Steak — adında "mushroom" geçtiği için şüpheli görünmüştü)
        # ya da balık (swordfish/tuna steak, onların da etiketlenmesi DOĞRU).
        # Eklemezsek 42 vejetaryen etiketli tarifte gerçek biftek kalıyor.
        "steak",
        # `\bsteaks?\b` BİLEŞİK HÂLLERİ yakalamıyor (aynı `meatball` dersi):
        # `Philly Cheesesteak Sandwiches` ve `Grilled Philly Cheesesteak
        # Tacos` vejetaryen etiketliydi.
        "cheesesteak",
        # Adı eti söylüyor ama malzeme listesi yazmıyor — hepsi vejetaryen
        # etiketliydi ve malzemesinde yalnızca garnitür var:
        #   `Melissa's Crock Pot Pot Roast` -> patates, soğan, biber, tuz
        #   `Chuck Roast`                   -> havuç, patates, kereviz, su
        #   `Marinated Filet Mignon`        -> zeytinyağı, sarımsak
        # ⚠️ ÇIPLAK `roast` EKLENEMEZ: adında geçen 75 tarifin çoğu patates
        # ve havuç (`Crispy Roast Potatoes`, `Roast Carrots With a Twist`).
        # Yalnızca et kesimiyle birleşen hâlleri güvenli.
        "pot roast", "chuck roast", "rump roast", "beef roast", "filet mignon",
        # 4 eşleşme, 3'ü gerçekten kıymalı. Dördüncüsü `Unsloppy Joes (Easy
        # VEGETARIAN Sloppy Joes)` ve adındaki "vegetarian" onu zaten koruyor.
        "sloppy joe",
    ]
    # ⚠️ SADECE MALZEMEDE aranan et kelimeleri. Ada bakan ağa konulamazlar
    # çünkü ad içinde başka bir şey demek olabiliyorlar.
    land_meat_ingredient_only = [
        "rabbit",     # 3 eşleşme, 1'i `Frijole Rabbit (Mexican Rarebit)` —
                      # peynirli bir yemek, "rarebit"in bozulmuş yazımı.
                      # Malzemede geçen 2 tarifte gerçekten tavşan var.
    ]
    # ⚠️ SADECE ADDA aranan, üstelik bir ŞART listesi olan et kelimeleri.
    # Veri setinin malzeme alanı ana proteini sık sık hiç yazmıyor (hot dog'da
    # sosis yok), o yüzden ad tek savunma — ama adda geçmesi de yetmiyor:
    # 12 eşleşmenin 3'ü SOSİS DEĞİL SOS/EKMEK (`All-In-One Hot Dog Mustard`,
    # `Hot Dog Sauce`, `Whole Wheat Burger/Hot Dog Buns`). Faz 29'daki
    # "Mincemeat (Suet-FREE)" dersinin aynısı: kelime var, madde yok.
    # ⚠️ `dog` ÇIPLAK HÂLİYLE gerekiyor: `Kansas City Dogs` adında "hot dog"
    # ifadesi GEÇMİYOR, yalnızca "Dogs" var — ve o tarif vegan etiketliydi.
    land_meat_name_only = ["hot dog", "dog"]
    # Aşağıdaki liste YALNIZCA yukarıdaki şartlı kelimeler için geçerli, yani
    # `dog` eşleştiğinde devreye giriyor. Bu yüzden liberal olabiliyor:
    # "pie" burada Shepherd's Pie'ı etkilemiyor, çünkü onda `dog` yok.
    # Tamamı gerçek veriden okundu — adında `dog` geçen 24 tarifin tümü
    # gözden geçirildi, aşağıdakiler sosis DEĞİL:
    #   Hot Dog Mustard / Hot Dog Sauce / Hot Dog Buns   -> sos, ekmek
    #   Whoopie Pies (Or Devil Dogs)                     -> PASTA
    #   Butterscotch Caramel Salty Dogs                  -> KOKTEYL
    #   Dog Cookies / Good Doggie Dog Bones              -> KÖPEK MAMASI
    not_actually_meat = ["mustard", "sauce", "bun", "relish", "seasoning", "spice",
                         "devil", "whoopie", "pie", "cookie", "biscuit", "bone",
                         "salty", "doggie", "caramel"]

    seafood = ["fish", "shrimp", "salmon", "tuna", "cod", "crab", "lobster",
               "anchovy", "sardine", "scallop", "mussel", "clam", "oyster",
               "halibut", "tilapia", "trout", "prawn", "calamari", "squid",
               # Aynı sebep: `\bfishs?\b` "catfish"i yakalamıyor ve
               # `Crispy Fried Catfish Nuggets` vejetaryene düşmüştü.
               "catfish", "swordfish", "monkfish", "shellfish", "whitefish",
               # ── 2026-08-17: hafızadaki "seafood listesi eksik" notu.
               # Hepsi ölçüldü, hepsi gerçek balık, yanlış pozitif yok.
               "sole", "flounder", "mackerel", "haddock", "herring",
               "octopus", "bass", "perch", "snapper",
               # `plaice` bir yassı balık; `talapia` ise TİLAPYANIN VERİ
               # SETİNDEKİ YANLIŞ YAZIMI (`Seasoned Talapia Fillets`) —
               # doğru yazımı listede olduğu hâlde kaçıyordu. Kural bazlı
               # etiketlemenin sınırı burada çıplak görünüyor: yazım hatası
               # kelime listesini tamamen atlatıyor.
               "plaice", "talapia"]
    meat_categories = ["chicken", "beef", "pork", "poultry", "meat", "lamb", "turkey",
                       "veal", "duck", "ham"]
    seafood_categories = ["fish", "seafood", "salmon", "tuna", "crab", "lobster"]

    # `hot dog` gibi ad-şartlı kelimeler: adda geçmeli AMA yanında onu bir
    # soğuk yemeğe değil sosa/ekmeğe çeviren bir kelime OLMAMALI.
    name_has_conditional_meat = (
        not is_plant_based_by_name
        and has_word(name_lower, land_meat_name_only)
        and not any(w in name_lower for w in not_actually_meat)
    )

    # Tarif adında et kelimesi var mı? (sadece bitki bazlı sinyal YOKSA sayılır)
    name_has_land_meat = not is_plant_based_by_name and (
        has_word(name_lower, land_meat) or name_has_conditional_meat
    )
    name_has_seafood = not is_plant_based_by_name and has_word(name_lower, seafood)

    has_land_meat = (has_word(ingredients_text, land_meat)
                      or has_word(ingredients_text, land_meat_ingredient_only)
                      or any(c in category_lower for c in meat_categories)
                      or name_has_land_meat)
    has_seafood = (has_word(ingredients_text, seafood)
                   or any(c in category_lower for c in seafood_categories)
                   or name_has_seafood)
    
    if not has_land_meat and has_seafood:
        tags.append("pescatarian")
    if not has_land_meat and not has_seafood:
        tags.append("vegetarian")
    
    # --- Dairy-free ---
    dairy_words = ["milk", "cheese", "butter", "yogurt", "cream", "whey", "casein",
                   "brie", "cheddar", "mozzarella", "parmesan", "feta", "ricotta",
                   "gouda", "provolone", "cottage", "custard", "ghee", "buttermilk",
                   "mascarpone"]
    dairy_categories = ["cheese", "cream", "custard", "milk"]

    has_dairy = (has_word(ingredients_text, dairy_words)
                 or any(c in category_lower for c in dairy_categories)
                 or has_word(name_lower, dairy_words))
    if not has_dairy:
        tags.append("dairy_free")
    
    # --- Vegan (vejetaryen + süt yok + yumurta/bal yok) ---
    #
    # 🔴 BURADA ÜÇ AYRI HATA VARDI, üçü de 2026-08-17'de ölçüldü. İkisi vegan
    # havuzunu HAKSIZ YERE DARALTIYORDU — yani "vegan sayfasında iyi tarif
    # çıkmıyor" şikayetinin doğrudan sebebi:
    #
    # 1. `any(word in ingredients_text ...)` KELİME SINIRSIZDI → **`eggplant`
    #    "yumurta" sayılıyordu.** 51 tarif gerçekte yumurtasız olduğu hâlde
    #    vegan olamıyordu; ölçüm bunu kesinleştirdi: 1.762 vegan tarifin
    #    HİÇBİRİNDE patlıcan yok (0). Baba ganuş, sarımsak soslu patlıcan,
    #    nar ekşili patlıcan — hepsi dışarıdaydı.
    # 2. Aynı sebeple `honeydew` (kavun) "bal" sayılıyordu (2 tarif).
    # 3. Kategori kontrolü de alt-dizi olduğu için **`"Egg Free"` kategorisi
    #    "yumurta içeriyor" demek oluyordu** — tam tersi.
    #
    # Ayrıca ada bakan güvenlik ağı yumurta için HİÇ YOKTU: `Sauteed Crookneck
    # Squash and Egg Noodles` malzemesinde eriştesi yazmadığı için vegandı.
    # (Faz 15b'de `nut_free` için bulunan kök sebebin aynısı, dördüncü kez.)
    egg_honey = ["egg", "honey"]
    egg_name_words = ["egg noodle", "egg white", "egg yolk"]
    # Kategori artık TAM eşleşme: `in` yerine `==`. "Egg Free" böylece dışarıda
    # kalıyor, "Egg Free" adı zaten yumurtasızlığın kendisi.
    egg_categories = {"egg", "eggs", "custard", "meringue"}

    has_egg_honey = (has_word(ingredients_text, egg_honey)
                     or category_lower.strip() in egg_categories
                     or (not is_plant_based_by_name
                         and has_word(name_lower, egg_name_words)))

    if "vegetarian" in tags and not has_dairy and not has_egg_honey:
        tags.append("vegan")
    
    # --- Nut-free ---
    #
    # 🔴 KÖK SEBEP FAZ 15B'DE BULUNDU, FAZ 29'DA DÜZELTİLDİ. Ete bakan
    # güvenlik ağı tarif ADINI da kontrol ediyordu; nut/dairy/gluten için
    # o ağ HİÇ YOKTU. Sonuç: `Pine Nut and Almond Cookies` — malzeme listesi
    # sadece ["flour","sugar"] olduğu için `nut_free: True` etiketleniyordu,
    # oysa ad açıkça söylüyor. Aynı açık `wheat free peanut butter cookies`'te
    # de vardı.
    #
    # ⚠️ Genel bir "nut" kelimesi EKLENEMEZ: coconut, nutmeg, butternut ve
    # doughnut'a takılırdı. Liste bilerek belirli fındık adlarından oluşuyor;
    # `pine nut` iki kelimelik bir ifade olarak güvenle eklenebiliyor.
    nut_words = ["almond", "walnut", "pecan", "cashew", "peanut", "hazelnut",
                 "pistachio", "macadamia", "pine nut", "praline", "nutella",
                 "marzipan", "brazil nut", "hickory nut"]
    nut_categories = ["almond", "peanut", "cashew", "walnut", "pecan", "hazelnut",
                      "pistachio", "macadamia", "nut"]

    has_nuts = (has_word(ingredients_text, nut_words)
                or any(c in category_lower for c in nut_categories)
                or has_word(name_lower, nut_words))
    if not has_nuts:
        tags.append("nut_free")

    return tags

def build_description(row):
    """Embedding için zengin açıklama metni oluşturur"""
    ingredients_str = ", ".join(row["ingredients_clean"])
    time_str = f"{row['total_time_min']} minutes" if row["total_time_min"] else "unknown time"
    tags_str = ", ".join(row["diet_tags"]) if row["diet_tags"] else "no specific diet"
    
    return (
        f"{row['name_clean']}. "
        f"Category: {row['RecipeCategory']}. "
        f"Ingredients: {ingredients_str}. "
        f"Total time: {time_str}. "
        f"Diet: {tags_str}."
    )


# ============ MAIN PIPELINE ============

# Pipeline bir fonksiyonun içinde ve `if __name__ == "__main__"` ile korunuyor.
# Önceden modül seviyesindeydi, yani `import clean_data` demek tüm pipeline'ı
# çalıştırmak demekti: 522k satır okunuyor ve recipes_cleaned.csv ÜZERİNE
# yazılıyordu. Testler yukarıdaki saf fonksiyonları import edebilsin diye
# ayrıldı. (filters.py ve llm.py'de bu guard zaten vardı.)
# Çalıştırma şekli değişmedi: python clean_data.py

SAMPLE_SIZE = 10000


def main():
    print("Loading recipes.csv ...")
    df = pd.read_csv("recipes.csv")
    print(f"Total recipes in dataset: {len(df)}")

    # GÖRSELİ OLANLARDAN örnekliyoruz — örneklemeden ÖNCE filtrelemek şart,
    # yoksa sette görselli oran ~%32 olduğu için kartların üçte ikisi fotoğrafsız
    # kalırdı. Havuz bol: 522.517 tarifin 165.896'sında görsel var (ölçüldü).
    with_images = df[df["Images"].apply(has_image)]
    print(f"Recipes with a usable image: {len(with_images)} "
          f"({100 * len(with_images) / len(df):.1f}%)")

    df_sample = with_images.sample(n=SAMPLE_SIZE, random_state=42).reset_index(drop=True)
    print(f"Sampled {len(df_sample)} recipes for processing")

    print("Cleaning fields...")
    df_sample["image_url"] = df_sample["Images"].apply(parse_image_url)
    df_sample["name_clean"] = df_sample["Name"].apply(clean_text)
    df_sample["ingredients_clean"] = df_sample["RecipeIngredientParts"].apply(parse_ingredients)
    df_sample["instructions_clean"] = df_sample["RecipeInstructions"].apply(parse_instructions)
    df_sample["cook_time_min"] = df_sample["CookTime"].apply(parse_duration_to_minutes)
    df_sample["prep_time_min"] = df_sample["PrepTime"].apply(parse_duration_to_minutes)
    df_sample["total_time_min"] = df_sample["TotalTime"].apply(parse_duration_to_minutes)
    # Faz 29: porsiyon sayısı. NEDEN GEREKLİ — besin değerlerinin tabanı
    # belirsizdi: 9.795 tarifte kalori medyanı 309 kcal ama %6.9'u 1000'in,
    # %1.1'i 3000'in üstünde, en yükseği 38.662. Yani bazıları porsiyon
    # başına, bazıları tarifin tamamı ve ayırt edecek veri yoktu. Bu kolon
    # veri setinde ~%64 dolu; dolu olduğu yerde porsiyon başına değer
    # hesaplanabiliyor. (Dolu olmadığında `servings` 0 kalıyor ve tüketen
    # taraf "bilinmiyor" olarak davranmak zorunda — uydurmuyoruz.)
    df_sample["servings"] = df_sample["RecipeServings"].apply(parse_servings)
    df_sample["diet_tags"] = df_sample.apply(
            lambda row: extract_diet_tags(row["ingredients_clean"], row["RecipeCategory"], row["name_clean"]),
            axis=1
        )
    df_sample["description_for_embedding"] = df_sample.apply(build_description, axis=1)

    before = len(df_sample)
    df_sample = df_sample[df_sample["ingredients_clean"].apply(len) >= 2].reset_index(drop=True)
    after = len(df_sample)
    print(f"Removed {before - after} recipes with empty ingredients")

    print(f"\n=== Summary ===")
    print(f"Final recipe count: {len(df_sample)}")
    print(f"With cook time: {df_sample['cook_time_min'].notna().sum()}")
    print(f"With image: {(df_sample['image_url'] != '').sum()} (should be all)")
    print()
    print("Diet tag distribution:")
    for tag in ["gluten_free", "dairy_free", "nut_free", "vegetarian", "pescatarian", "vegan"]:
        count = df_sample["diet_tags"].apply(lambda x: tag in x).sum()
        percentage = (count / len(df_sample)) * 100
        print(f"  {tag:15} : {count:5} ({percentage:.1f}%)")

    print("\n=== Sample descriptions ===")
    for i in range(3):
        print(f"\n--- Recipe {i+1} ---")
        print(df_sample["description_for_embedding"].iloc[i])
        print(f"Tags: {df_sample['diet_tags'].iloc[i]}")

    output_path = "recipes_cleaned.csv"
    df_sample.to_csv(output_path, index=False)
    # Düz metin: Windows konsolu (cp1254) '✓' karakterinde UnicodeEncodeError
    # veriyor ve script tam bitmişken çöküyordu. Aynı sorun load_to_chromadb.py'de
    # de yaşanmıştı.
    print(f"\n[OK] Cleaned data saved to: {output_path} ({len(df_sample)} recipes)")


if __name__ == "__main__":
    main()