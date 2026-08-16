import os
import pandas as pd
import ast
import chromadb

# Script'i hangi klasörden çalıştırırsan çalıştır dosyalar bulunsun
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "recipes_cleaned.csv")
# Tarifler salt-okunur veri (bir kez yazılır, sonra sadece okunur) — ayrı bir
# ChromaDB sunucusuna değil, API image'ına gömülecek klasöre yazılıyor.
# Bkz. CLAUDE.md → "şekil sorunu".
CHROMA_PATH = os.path.join(BASE_DIR, "..", "api", "chroma_data")

print("Loading cleaned data...")
df = pd.read_csv(CSV_PATH)

# CSV'de string olarak saklanan liste kolonlarını tekrar Python listesine çevir
df["ingredients_clean"] = df["ingredients_clean"].apply(ast.literal_eval)
df["diet_tags"] = df["diet_tags"].apply(ast.literal_eval)

print(f"Total recipes to load: {len(df)}")

# Kalıcı ChromaDB klasörünü aç (sunucu gerekmiyor, dosyaya yazıyor)
print(f"Writing to persistent ChromaDB: {os.path.normpath(CHROMA_PATH)}")
client = chromadb.PersistentClient(path=CHROMA_PATH)

# Koleksiyon oluştur (varsa üzerine yaz)
try:
    client.delete_collection("recipes")
    print("Deleted existing collection")
except Exception:
    pass

collection = client.create_collection("recipes")
print("Created new collection: recipes")

# Embedding üretme ve yükleme (toplu / batch halinde, performans için).
# Embedding'i ChromaDB kendi varsayılan fonksiyonuyla üretiyor (all-MiniLM-L6-v2,
# ONNX) — ayrıca sentence-transformers/torch kurmaya gerek yok.
batch_size = 100
total = len(df)

for start in range(0, total, batch_size):
    end = min(start + batch_size, total)
    batch = df.iloc[start:end]

    documents = batch["description_for_embedding"].tolist()

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
            # Porsiyon sayısı (Faz 29). 0 = BİLİNMİYOR (veri setinde ~%36'sı
            # boş). Yukarıdaki besin değerlerinin tabanı belirsizdi — 9.795
            # tarifte kalori medyanı 309 kcal ama en yükseği 38.662, yani bir
            # kısmı porsiyon başına, bir kısmı tarifin tamamı. Bu alan dolu
            # olduğunda porsiyona bölmek mümkün; boş olduğunda tüketen taraf
            # "bilinmiyor" olarak davranmak ZORUNDA — 0'ı 1 saymak, tarifin
            # tamamını tek porsiyon ilan etmek olurdu.
            "servings": int(row.get("servings", 0) or 0),
            # ── Puan ve yorum sayısı (2026-08-17) ──────────────────────
            # Veri setinde baştan beri vardı ama HİÇ yüklenmemişti, ve bunun
            # bedeli ölçüldü: herkese açık koleksiyon sayfaları "eşleşen ilk
            # 24 tarif"i gösteriyordu — yani rastgele. Vegan sayfasının
            # tepesinde 5 dakikalık bir jicama çubuğu vardı, oysa aynı havuzda
            # **247 yorumlu 5.0 puanlı** `Baja Black Beans, Corn and Rice`
            # duruyordu. Sıralamayı buna çevirmek, sayfayı "rastgele 24"ten
            # "en beğenilen 24"e taşıyor.
            #
            # 0.0 = PUANLANMAMIŞ (veri setinin %17'si). `rating` tek başına
            # sıralama ölçütü OLAMAZ: tek yorumlu bir 5.0, 247 yorumlu bir
            # 4.8'i yener. Ağırlıklandırma tüketen tarafta (`discover.py`)
            # yapılıyor — ham veri burada, politika orada.
            "rating": float(row["AggregatedRating"]) if pd.notna(row.get("AggregatedRating")) else 0.0,
            "review_count": int(row["ReviewCount"]) if pd.notna(row.get("ReviewCount")) else 0,
            "gluten_free": "gluten_free" in row["diet_tags"],
            "dairy_free": "dairy_free" in row["diet_tags"],
            "nut_free": "nut_free" in row["diet_tags"],
            "vegetarian": "vegetarian" in row["diet_tags"],
            "pescatarian": "pescatarian" in row["diet_tags"],
            "vegan": "vegan" in row["diet_tags"],
            "instructions": str(row["instructions_clean"])[:1000],  # çok uzunsa kısalt
            # Tarif fotoğrafı (Faz 20). Örneklem artık YALNIZCA görseli olan
            # tariflerden alınıyor, dolayısıyla bu alan her kayıtta dolu. Yine de
            # frontend bozuk/ölü linke karşı yedekli çalışıyor (görsel yüklenmezse
            # kart metin hâline düşüyor) — linkler Food.com CDN'inde ve dış bir
            # servise bağlıyız.
            "image_url": str(row.get("image_url", "") or ""),
            # Malzeme listesi (Faz 17 — Pantry). Önceden malzemeler YALNIZCA
            # description_for_embedding metninin içindeydi, yani yapılandırılmamış
            # düz yazıydı; "bu tarif dolabımdaki kaç malzemeyi kullanıyor"
            # sorusunu ancak metin ayrıştırarak, kusurlu biçimde cevaplayabilirdik.
            #
            # ChromaDB metadata'sı yalnızca SKALER kabul ediyor (str/int/float/bool),
            # liste konulamıyor — bu yüzden ayraçlı metin olarak saklanıyor.
            # Ayraç `|`: gerçek veride ölçüldü (400 tariflik örneklemde 3230
            # malzemenin 7'si virgül içeriyor, HİÇBİRİ `|` içermiyor), yani virgül
            # kullanılsaydı o malzemeler bölünüp veri bozulacaktı.
            "ingredients": "|".join(row["ingredients_clean"]),
        })

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )

    print(f"Loaded {end}/{total} recipes...")

print(f"\nSuccessfully loaded {total} recipes into ChromaDB!")
print(f"Collection count: {collection.count()}")