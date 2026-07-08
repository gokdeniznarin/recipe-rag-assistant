import pandas as pd
import ast

# Temizlenmiş veriyi oku
df = pd.read_csv("recipes_cleaned.csv")

# diet_tags ve ingredients_clean kolonları CSV'de string olarak kayıtlı,
# onları tekrar Python listesine çeviriyoruz
df["diet_tags"] = df["diet_tags"].apply(ast.literal_eval)
df["ingredients_clean"] = df["ingredients_clean"].apply(ast.literal_eval)

print(f"Total recipes: {len(df)}\n")

# --- ÇELİŞKİ 1: Et kategorisi ama vegetarian/vegan tag'i ---
meat_cats = ["chicken", "beef", "pork", "meat", "poultry", "turkey", "lamb", "fish", "seafood"]
suspicious_veg = df[
    df["RecipeCategory"].str.lower().str.contains("|".join(meat_cats), na=False) &
    df["diet_tags"].apply(lambda x: "vegetarian" in x or "vegan" in x)
]
print(f"⚠️  Meat category but tagged vegetarian/vegan: {len(suspicious_veg)}")
if len(suspicious_veg) > 0:
    for _, row in suspicious_veg.head(10).iterrows():
        print(f"   - {row['name_clean']} | Category: {row['RecipeCategory']} | Tags: {row['diet_tags']}")

# --- ÇELİŞKİ 2: Cheese/dairy kategorisi ama dairy_free tag'i ---
dairy_cats = ["cheese", "cream", "milk", "yogurt", "custard"]
suspicious_dairy = df[
    df["RecipeCategory"].str.lower().str.contains("|".join(dairy_cats), na=False) &
    df["diet_tags"].apply(lambda x: "dairy_free" in x)
]
print(f"\n⚠️  Dairy category but tagged dairy_free: {len(suspicious_dairy)}")
if len(suspicious_dairy) > 0:
    for _, row in suspicious_dairy.head(10).iterrows():
        print(f"   - {row['name_clean']} | Category: {row['RecipeCategory']} | Tags: {row['diet_tags']}")

# --- ÇELİŞKİ 3: Bread kategorisi ama gluten_free tag'i ---
suspicious_gluten = df[
    df["RecipeCategory"].str.lower().str.contains("bread", na=False) &
    df["diet_tags"].apply(lambda x: "gluten_free" in x)
]
print(f"\n⚠️  Bread category but tagged gluten_free: {len(suspicious_gluten)}")
if len(suspicious_gluten) > 0:
    for _, row in suspicious_gluten.head(10).iterrows():
        print(f"   - {row['name_clean']} | Category: {row['RecipeCategory']} | Tags: {row['diet_tags']}")

# --- ÇELİŞKİ 4: Kuruyemiş kategorisi ama nut_free tag'i ---
nut_cats = ["almond", "peanut", "walnut", "pecan", "cashew", "pistachio", "hazelnut", "macadamia"]
suspicious_nut = df[
    df["RecipeCategory"].str.lower().str.contains("|".join(nut_cats), na=False) &
    df["diet_tags"].apply(lambda x: "nut_free" in x)
]
print(f"\n⚠️  Nut category but tagged nut_free: {len(suspicious_nut)}")
if len(suspicious_nut) > 0:
    for _, row in suspicious_nut.head(10).iterrows():
        print(f"   - {row['name_clean']} | Category: {row['RecipeCategory']} | Tags: {row['diet_tags']}")

# --- ÇELİŞKİ 5: Süre tutarlılığı (cook_time + prep_time ≈ total_time) ---
df_with_times = df.dropna(subset=["cook_time_min", "prep_time_min", "total_time_min"])
inconsistent_time = df_with_times[
    abs((df_with_times["cook_time_min"] + df_with_times["prep_time_min"]) - df_with_times["total_time_min"]) > 5
]
print(f"\n⚠️  Inconsistent time calculation (cook+prep ≠ total): {len(inconsistent_time)}")
if len(inconsistent_time) > 0:
    for _, row in inconsistent_time.head(10).iterrows():
        print(f"   - {row['name_clean']} | Cook: {row['cook_time_min']} + Prep: {row['prep_time_min']} "
              f"≠ Total: {row['total_time_min']}")

# --- ÇELİŞKİ 6: Malzeme sayısı anomalisi ---
df["ingredient_count"] = df["ingredients_clean"].apply(len)
too_few = df[df["ingredient_count"] <= 1]
too_many = df[df["ingredient_count"] >= 25]
print(f"\n⚠️  Recipes with 1 or fewer ingredients: {len(too_few)}")
if len(too_few) > 0:
    for _, row in too_few.head(10).iterrows():
        print(f"   - {row['name_clean']} | Ingredients: {row['ingredients_clean']}")

print(f"\n⚠️  Recipes with 25+ ingredients: {len(too_many)}")
if len(too_many) > 0:
    for _, row in too_many.head(5).iterrows():
        print(f"   - {row['name_clean']} | Ingredient count: {row['ingredient_count']}")

print("\n" + "="*60)
print("Note: These are POTENTIAL issues, not definitely wrong.")
print("Some may be legitimate (e.g. gluten-free cornbread).")