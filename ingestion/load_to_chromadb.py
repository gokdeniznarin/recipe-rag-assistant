import pandas as pd
import ast
import chromadb
from sentence_transformers import SentenceTransformer

print("Loading cleaned data...")
df = pd.read_csv("recipes_cleaned.csv")

# CSV'de string olarak saklanan liste kolonlarını tekrar Python listesine çevir
df["ingredients_clean"] = df["ingredients_clean"].apply(ast.literal_eval)
df["diet_tags"] = df["diet_tags"].apply(ast.literal_eval)

print(f"Total recipes to load: {len(df)}")

# Embedding modelini yükle (ilk çalıştırmada internetten indirir, ~90MB)
print("Loading embedding model...")
model = SentenceTransformer('all-MiniLM-L6-v2')

# ChromaDB'ye bağlan (Docker'da çalışan sunucuya)
print("Connecting to ChromaDB...")
client = chromadb.HttpClient(host='localhost', port=8000)

# Koleksiyon oluştur (varsa üzerine yaz)
try:
    client.delete_collection("recipes")
    print("Deleted existing collection")
except Exception:
    pass

collection = client.create_collection("recipes")
print("Created new collection: recipes")

# Embedding üretme ve yükleme (toplu / batch halinde, performans için)
batch_size = 100
total = len(df)

for start in range(0, total, batch_size):
    end = min(start + batch_size, total)
    batch = df.iloc[start:end]

    documents = batch["description_for_embedding"].tolist()
    embeddings = model.encode(documents).tolist()

    ids = batch["RecipeId"].astype(str).tolist()

    metadatas = []
    for _, row in batch.iterrows():
        metadatas.append({
            "name": row["name_clean"],
            "category": str(row["RecipeCategory"]),
            "prep_time_min": float(row["prep_time_min"]) if pd.notna(row["prep_time_min"]) else -1,
            "cook_time_min": float(row["cook_time_min"]) if pd.notna(row["cook_time_min"]) else -1,
            "total_time_min": float(row["total_time_min"]) if pd.notna(row["total_time_min"]) else -1,
            "calories": float(row["Calories"]),
            "fat_content": float(row["FatContent"]),
            "saturated_fat_content": float(row["SaturatedFatContent"]),
            "cholesterol_content": float(row["CholesterolContent"]),
            "sodium_content": float(row["SodiumContent"]),
            "carbohydrate_content": float(row["CarbohydrateContent"]),
            "fiber_content": float(row["FiberContent"]),
            "sugar_content": float(row["SugarContent"]),
            "protein_content": float(row["ProteinContent"]),
            "gluten_free": "gluten_free" in row["diet_tags"],
            "dairy_free": "dairy_free" in row["diet_tags"],
            "nut_free": "nut_free" in row["diet_tags"],
            "vegetarian": "vegetarian" in row["diet_tags"],
            "pescatarian": "pescatarian" in row["diet_tags"],
            "vegan": "vegan" in row["diet_tags"],
            "instructions": str(row["instructions_clean"])[:1000],  # çok uzunsa kısalt
        })

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas
    )

    print(f"Loaded {end}/{total} recipes...")

print(f"\n✓ Successfully loaded {total} recipes into ChromaDB!")
print(f"Collection count: {collection.count()}")