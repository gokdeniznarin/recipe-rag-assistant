import pandas as pd
import re
import html

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

def extract_diet_tags(ingredients_list, category="", name=""):
    """Malzeme ve kategori üzerinden diyet etiketi çıkarır"""
    tags = []
    ingredients_text = " ".join(ingredients_list).lower()
    category_lower = str(category).lower()


    name_lower = str(name).lower()

    # Tarif adında "vegan/vegetarian/plant-based" gibi bir işaret var mı?
    # Varsa adındaki et kelimeleri bitki bazlı taklit üründür (örn. "Vegan Chicken Nuggets")
    plant_based_signals = ["vegan", "vegetarian", "plant-based", "plant based",
                           "meatless", "meat-free", "veggie"]
    is_plant_based_by_name = any(sig in name_lower for sig in plant_based_signals)
    
    # --- Gluten-free ---
    gluten_words = ["flour", "wheat", "bread", "pasta", "barley", "rye",
                    "spaghetti", "macaroni", "noodle", "roll", "dough", "biscuit",
                    "cracker", "tortilla", "bun", "bagel", "cereal", "oat", "couscous",
                    "breadcrumb", "crouton", "pretzel", "pastry", "pita", "pizza"]
    gluten_categories = ["bread", "pasta", "pizza", "pie", "cookie", "cake", "pastry"]
    is_labeled_gf = "gluten" in category_lower and "free" in category_lower
    
    has_gluten = (any(word in ingredients_text for word in gluten_words)
                  or any(c in category_lower for c in gluten_categories)) and not is_labeled_gf
    if not has_gluten:
        tags.append("gluten_free")
    
    # --- Et / deniz ürünü ---
    land_meat = ["chicken", "beef", "pork", "meat", "bacon", "turkey", "lamb"]
    seafood = ["fish", "shrimp", "salmon", "tuna", "cod", "crab", "lobster", "anchovy"]
    meat_categories = ["chicken", "beef", "pork", "poultry", "meat", "lamb", "turkey"]
    seafood_categories = ["fish", "seafood", "salmon", "tuna"]
    
    # Tarif adında et kelimesi var mı? (sadece bitki bazlı sinyal YOKSA sayılır)
    name_has_land_meat = (not is_plant_based_by_name
                          and any(word in name_lower for word in land_meat))
    name_has_seafood = (not is_plant_based_by_name
                        and any(word in name_lower for word in seafood))

    has_land_meat = (any(word in ingredients_text for word in land_meat)
                      or any(c in category_lower for c in meat_categories)
                      or name_has_land_meat)
    has_seafood = (any(word in ingredients_text for word in seafood)
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
    
    has_dairy = (any(word in ingredients_text for word in dairy_words)
                 or any(c in category_lower for c in dairy_categories))
    if not has_dairy:
        tags.append("dairy_free")
    
    # --- Vegan (vejetaryen + süt yok + yumurta/bal yok) ---
    egg_honey = ["egg", "honey"]
    egg_categories = ["egg", "custard", "meringue"]
    has_egg_honey = (any(word in ingredients_text for word in egg_honey)
                     or any(c in category_lower for c in egg_categories))
    
    if "vegetarian" in tags and not has_dairy and not has_egg_honey:
        tags.append("vegan")
    
    # --- Nut-free ---
    nut_words = ["almond", "walnut", "pecan", "cashew", "peanut", "hazelnut",
                 "pistachio", "macadamia"]
    nut_categories = ["almond", "peanut", "cashew", "walnut", "pecan", "hazelnut",
                      "pistachio", "macadamia"]
    
    has_nuts = (any(word in ingredients_text for word in nut_words)
                or any(c in category_lower for c in nut_categories))
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