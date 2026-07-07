import pandas as pd

# CSV dosyasını oku
df = pd.read_csv("recipes.csv")

# Kaç satır, kaç kolon var?
print("Veri boyutu (satır, kolon):", df.shape)

# Hangi kolonlar var?
print("\nKolon isimleri:")
print(df.columns.tolist())

# İlk 3 satırı göster
print("\nİlk 3 satır:")
print(df.head(3))



# Malzeme kolonunun tam içeriğini gör (bir örnek üzerinden)
print("\nÖrnek malzeme listesi (ham hali):")
print(df["RecipeIngredientParts"].iloc[0])

print("\nÖrnek talimat (ham hali):")
print(df["RecipeInstructions"].iloc[0])

print("\nÖrnek süre bilgileri:")
print(df[["CookTime", "PrepTime", "TotalTime"]].head(5))

print("\nRecipeCategory örnekleri:")
print(df["RecipeCategory"].value_counts().head(10))

print("\nMakro besin örnekleri:")
nutrition_cols = ["Calories", "FatContent", "SaturatedFatContent", "CholesterolContent",
                  "SodiumContent", "CarbohydrateContent", "FiberContent", "SugarContent", "ProteinContent"]
print(df[nutrition_cols].head(5))

print("\nMakro besin kolonlarında eksik veri oranı:")
print(df[nutrition_cols].isna().mean())