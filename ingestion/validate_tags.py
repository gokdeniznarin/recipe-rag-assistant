import pandas as pd
import ast

# Temizlenmiş veriyi oku
df = pd.read_csv("recipes_cleaned.csv")

# diet_tags kolonu CSV'de string olarak kayıtlı (["gluten_free", ...] gibi),
# onu tekrar Python listesine çeviriyoruz
df["diet_tags"] = df["diet_tags"].apply(ast.literal_eval)

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

print("\n" + "="*60)
print("Note: These are POTENTIAL issues, not definitely wrong.")
print("Some may be legitimate (e.g. gluten-free cornbread).")