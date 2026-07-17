"""
Gömülü tarif veritabanına karşı arama testleri.

Image'a gömülü veriye karşı çalıştır — repodaki `api/chroma_data/` klasörünü
hedefleme:

    docker run --rm -v "$PWD/ingestion:/ingestion:ro" \
      -e CHROMA_PATH=/app/chroma_data recipe-rag-assistant-api \
      python /ingestion/test_search.py

Sebep: `PersistentClient` bir klasörü **açarken bile** `chroma.sqlite3`'e yazıyor
(işletim sisteminden bağımsız; salt-okunur mount'ta doğrudan hata veriyor). Repodaki
klasöre yöneltirsen commit edilmiş 28MB'lık dosya kirlenir ve git'te sahte bir
değişiklik çıkar (veri bozulmaz, `git checkout` ile geri alınır). Image'ın içindeki
kopya ise container'ın yazılabilir katmanında olduğu için güvenle kullanılır.
"""
import os
import chromadb

# Gömülü tarif veritabanını aç (ChromaDB sunucusu yok — Faz 8).
# Embedding'i ChromaDB kendi varsayılan fonksiyonuyla üretiyor (ONNX — Faz 7).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_PATH = os.getenv("CHROMA_PATH", os.path.join(BASE_DIR, "..", "api", "chroma_data"))

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_collection("recipes")

print(f"Total recipes in collection: {collection.count()}\n")

def search(query_text, n_results=5, where=None):
    return collection.query(
        query_texts=[query_text],
        n_results=n_results,
        where=where
    )

# --- TEST 1: Basit semantic arama ---
print("=" * 60)
print("TEST 1: 'quick chicken dinner'")
print("=" * 60)
results = search("quick chicken dinner")
for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
    print(f"\n{i+1}. {meta['name']}")
    print(f"   Time: {meta['total_time_min']} min | Calories: {meta['calories']}")
    print(f"   Doc: {doc[:100]}...")

# --- TEST 2: Diyet filtresi ile arama ---
print("\n" + "=" * 60)
print("TEST 2: 'dessert' + vegan filter")
print("=" * 60)
results = search("sweet dessert", where={"vegan": True})
for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
    print(f"\n{i+1}. {meta['name']} (vegan: {meta['vegan']})")

# --- TEST 3: Süre filtresi ile arama ---
print("\n" + "=" * 60)
print("TEST 3: 'pasta' + under 30 minutes")
print("=" * 60)
results = search("pasta", where={"total_time_min": {"$lte": 30}})
for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
    print(f"\n{i+1}. {meta['name']} - {meta['total_time_min']} min")

# --- TEST 4: Gluten-free filtre ---
print("\n" + "=" * 60)
print("TEST 4: 'bread' + gluten free filter")
print("=" * 60)
results = search("bread", where={"gluten_free": True})
for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
    print(f"\n{i+1}. {meta['name']} (gluten_free: {meta['gluten_free']})")