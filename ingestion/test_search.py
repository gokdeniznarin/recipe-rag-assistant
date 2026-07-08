import chromadb
from sentence_transformers import SentenceTransformer

# Bağlan
model = SentenceTransformer('all-MiniLM-L6-v2')
client = chromadb.HttpClient(host='localhost', port=8000)
collection = client.get_collection("recipes")

print(f"Total recipes in collection: {collection.count()}\n")

def search(query_text, n_results=5, where=None):
    query_embedding = model.encode(query_text).tolist()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where
    )
    return results

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