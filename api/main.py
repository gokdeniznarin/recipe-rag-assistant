from fastapi import FastAPI, Depends
import os
from pydantic import BaseModel
import chromadb
from filters import extract_filters
from llm import generate_answer, detect_ingredients_from_image
from auth import get_current_user_email
from favorites import add_favorite, get_favorites, remove_favorite
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Recipe RAG Assistant API")
# CORS: hangi sitelerin bu API'yi tarayıcıdan çağırabileceği. Geliştirmede "*"'dı;
# production'da kendi origin'lerimizle sınırlı.
#   - allow_origins: canlı frontend (Vercel production domain'i)
#   - allow_origin_regex ile ek olarak izin verilenler:
#       * Vercel'in bu projeye ait preview deploy'ları (her deploy'da host değişiyor)
#       * yerel geliştirme: localhost / 127.0.0.1 / LAN IP (herhangi bir port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://recipe-rag-assistant.vercel.app"],
    allow_origin_regex=r"https://recipe-rag-assistant[a-z0-9-]*\.vercel\.app|http://(localhost|127\.0\.0\.1|(\d{1,3}\.){3}\d{1,3})(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tarifler salt-okunur veri: bir kez ingestion ile yazılır, sonra sadece okunur.
# Bu yüzden ayrı bir ChromaDB sunucusuna değil, image'a gömülü klasöre bakıyor.
# (favorites.py hâlâ sunucuya bağlı — çalışma anında yazılan tek veri o. Firestore'a
# taşınınca chromadb servisi tamamen kalkacak; bkz. CLAUDE.md → "şekil sorunu".)
CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_data")
print(f"Opening recipes database: {CHROMA_PATH}")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
# Embedding'i ChromaDB'nin varsayılan fonksiyonu üretiyor: aynı all-MiniLM-L6-v2
# modeli, torch yerine ONNX motoruyla.
collection = chroma_client.get_collection("recipes")

print(f"Ready! Collection has {collection.count()} recipes.")


class SearchRequest(BaseModel):
    query: str
    n_results: int = 5


@app.get("/")
def root():
    return {"message": "Recipe RAG Assistant API is running"}


@app.post("/api/recipes/search")
def search_recipes(request: SearchRequest, user_email: str = Depends(get_current_user_email)):
    # 1. Kullanıcı sorgusundan filtre çıkar
    where_filter = extract_filters(request.query)

    # 2. ChromaDB'de semantic + metadata arama yap
    results = collection.query(
        query_texts=[request.query],
        n_results=request.n_results,
        where=where_filter
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

    # 3. LLM'e bulunan tarifleri ver, doğal cevap üret
    llm_answer = None
    if len(recipes) > 0:
        try:
            llm_answer = generate_answer(request.query, recipes)
        except Exception as e:
            print(f"LLM error (skipping): {e}")
            llm_answer = "AI commentary is temporarily unavailable. Here are the matching recipes."
   
        

    return {
        "query": request.query,
        "applied_filters": where_filter,
        "answer": llm_answer,
        "results": recipes
    }


@app.get("/api/auth/me")
def get_me(user_email: str = Depends(get_current_user_email)):
    return {"email": user_email}


class ImageSearchRequest(BaseModel):
    image_base64: str
    additional_text: str = ""
    n_results: int = 5


@app.post("/api/recipes/from-image")
def search_recipes_from_image(
    request: ImageSearchRequest,
    user_email: str = Depends(get_current_user_email)
):
    # 1. Fotoğraftan malzemeleri tanı
    detected_ingredients = detect_ingredients_from_image(request.image_base64)

    if len(detected_ingredients) == 0:
        return {"error": "No ingredients detected in the image"}

    # 2. Malzemeleri + (varsa) kullanıcının ek notunu birleştirip arama sorgusu oluştur
    ingredients_text = ", ".join(detected_ingredients)
    if request.additional_text.strip():
        combined_query = f"{ingredients_text}. {request.additional_text.strip()}"
    else:
        combined_query = ingredients_text

    # 3. Aynı arama akışını kullan (filtre + embedding + ChromaDB + LLM)
    where_filter = extract_filters(combined_query)

    results = collection.query(
        query_texts=[combined_query],
        n_results=request.n_results,
        where=where_filter
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

    llm_answer = None
    if len(recipes) > 0:
        try:
            llm_answer = generate_answer(combined_query, recipes)
        except Exception as e:
            print(f"LLM error (skipping): {e}")
            llm_answer = "AI commentary is temporarily unavailable. Here are the matching recipes."
    
        

    return {
        "detected_ingredients": detected_ingredients,
        "additional_text": request.additional_text,
        "combined_query": combined_query,
        "applied_filters": where_filter,
        "answer": llm_answer,
        "results": recipes
    }





@app.get("/api/recipes/{recipe_id}")
def get_recipe_detail(recipe_id: str, user_email: str = Depends(get_current_user_email)):
    results = collection.get(ids=[recipe_id])

    if len(results["ids"]) == 0:
        return {"error": "Recipe not found"}

    meta = results["metadatas"][0]

    return {
        "id": results["ids"][0],
        "name": meta["name"],
        "category": meta["category"],
        "total_time_min": meta["total_time_min"],
        "calories": meta["calories"],
        "protein_content": meta["protein_content"],
        "carbohydrate_content": meta["carbohydrate_content"],
        "fat_content": meta["fat_content"],
        "instructions": meta.get("instructions", ""),
        "diet_tags": {
            "gluten_free": meta["gluten_free"],
            "dairy_free": meta["dairy_free"],
            "nut_free": meta["nut_free"],
            "vegetarian": meta["vegetarian"],
            "pescatarian": meta["pescatarian"],
            "vegan": meta["vegan"],
        },
        "description": results["documents"][0]
    }



class FavoriteRequest(BaseModel):
    recipe_id: str


@app.post("/api/favorites/add")
def add_favorite_endpoint(request: FavoriteRequest, user_email: str = Depends(get_current_user_email)):
    try:
        add_favorite(user_email, request.recipe_id)
        return {"message": "Recipe added to favorites", "recipe_id": request.recipe_id}
    except ValueError as e:
        return {"error": str(e)}


@app.get("/api/favorites")
def list_favorites_endpoint(user_email: str = Depends(get_current_user_email)):
    favorites = get_favorites(user_email)
    return {"favorites": favorites}


@app.delete("/api/favorites/{recipe_id}")
def remove_favorite_endpoint(recipe_id: str, user_email: str = Depends(get_current_user_email)):
    try:
        remove_favorite(user_email, recipe_id)
        return {"message": "Recipe removed from favorites", "recipe_id": recipe_id}
    except ValueError as e:
        return {"error": str(e)}