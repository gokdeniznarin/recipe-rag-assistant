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

def extract_diet_tags(ingredients_list, category=""):
    """Malzeme ve kategori üzerinden diyet etiketi çıkarır"""
    tags = []
    ingredients_text = " ".join(ingredients_list).lower()
    category_lower = str(category).lower()
    
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
    
    has_land_meat = (any(word in ingredients_text for word in land_meat)
                      or any(c in category_lower for c in meat_categories))
    has_seafood = (any(word in ingredients_text for word in seafood)
                   or any(c in category_lower for c in seafood_categories))
    
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

print("Loading recipes.csv ...")
df = pd.read_csv("recipes.csv")
print(f"Total recipes in dataset: {len(df)}")

df_sample = df.sample(n=5000, random_state=42).reset_index(drop=True)
print(f"Sampled {len(df_sample)} recipes for processing")

print("Cleaning fields...")
df_sample["name_clean"] = df_sample["Name"].apply(clean_text)
df_sample["ingredients_clean"] = df_sample["RecipeIngredientParts"].apply(parse_ingredients)
df_sample["cook_time_min"] = df_sample["CookTime"].apply(parse_duration_to_minutes)
df_sample["prep_time_min"] = df_sample["PrepTime"].apply(parse_duration_to_minutes)
df_sample["total_time_min"] = df_sample["TotalTime"].apply(parse_duration_to_minutes)
df_sample["diet_tags"] = df_sample.apply(
    lambda row: extract_diet_tags(row["ingredients_clean"], row["RecipeCategory"]),
    axis=1
)
df_sample["description_for_embedding"] = df_sample.apply(build_description, axis=1)

before = len(df_sample)
df_sample = df_sample[df_sample["ingredients_clean"].apply(len) > 0].reset_index(drop=True)
after = len(df_sample)
print(f"Removed {before - after} recipes with empty ingredients")

print(f"\n=== Summary ===")
print(f"Final recipe count: {len(df_sample)}")
print(f"With cook time: {df_sample['cook_time_min'].notna().sum()}")
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
print(f"\n✓ Cleaned data saved to: {output_path} ({len(df_sample)} recipes)")