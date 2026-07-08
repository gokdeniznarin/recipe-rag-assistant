from fastapi import FastAPI
from pydantic import BaseModel
import chromadb
from sentence_transformers import SentenceTransformer

app = FastAPI(title="Recipe RAG Assistant API")

# Embedding modelini ve ChromaDB bağlantısını uygulama başlarken bir kere yükle
print("Loading embedding model...")
model = SentenceTransformer('all-MiniLM-L6-v2')

print("Connecting to ChromaDB...")
chroma_client = chromadb.HttpClient(host='localhost', port=8000)
collection = chroma_client.get_collection("recipes")

print(f"Ready! Collection has {collection.count()} recipes.")


class SearchRequest(BaseModel):
    query: str
    n_results: int = 5


@app.get("/")
def root():
    return {"message": "Recipe RAG Assistant API is running"}


@app.post("/api/recipes/search")
def search_recipes(request: SearchRequest):
    query_embedding = model.encode(request.query).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=request.n_results
    )

    recipes = []
    for doc, meta, recipe_id in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["ids"][0]
    ):
        recipes.append({
            "id": recipe_id,
            "name": meta["name"],
            "category": meta["category"],
            "total_time_min": meta["total_time_min"],
            "calories": meta["calories"],
            "diet_tags": {
                "gluten_free": meta["gluten_free"],
                "dairy_free": meta["dairy_free"],
                "nut_free": meta["nut_free"],
                "vegetarian": meta["vegetarian"],
                "pescatarian": meta["pescatarian"],
                "vegan": meta["vegan"],
            },
            "description": doc
        })

    return {"query": request.query, "results": recipes}