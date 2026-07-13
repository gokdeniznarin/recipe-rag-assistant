from fastapi import FastAPI, Depends
from pydantic import BaseModel
import chromadb
from sentence_transformers import SentenceTransformer
from filters import extract_filters
from llm import generate_answer, detect_ingredients_from_image
from auth import create_user, get_user_by_email, verify_password, create_access_token, get_current_user_email, verify_google_token, create_or_get_google_user
from favorites import add_favorite, get_favorites, remove_favorite
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Recipe RAG Assistant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
def search_recipes(request: SearchRequest, user_email: str = Depends(get_current_user_email)):
    query_embedding = model.encode(request.query).tolist()

    # 1. Kullanıcı sorgusundan filtre çıkar
    where_filter = extract_filters(request.query)

    # 2. ChromaDB'de semantic + metadata arama yap
    results = collection.query(
        query_embeddings=[query_embedding],
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
        llm_answer = generate_answer(request.query, recipes)

    return {
        "query": request.query,
        "applied_filters": where_filter,
        "answer": llm_answer,
        "results": recipes
    }


class RegisterRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
def register(request: RegisterRequest):
    try:
        create_user(request.email, request.password)
        return {"message": "User registered successfully", "email": request.email}
    except ValueError as e:
        return {"error": str(e)}
    


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(request: LoginRequest):
    user = get_user_by_email(request.email)

    if user is None:
        return {"error": "Invalid email or password"}

    # Google-only hesaplar klasik yolla giremez
    if user["auth_provider"] == "google":
        return {"error": "This account uses Google sign-in. Please use the Google button."}

    if not verify_password(request.password, user["hashed_password"]):
        return {"error": "Invalid email or password"}

    token = create_access_token(request.email)
    return {"access_token": token, "token_type": "bearer"}


class GoogleAuthRequest(BaseModel):
    id_token: str


@app.post("/api/auth/google")
def google_auth(request: GoogleAuthRequest):
    try:
        user_info = verify_google_token(request.id_token)
        email = create_or_get_google_user(user_info["email"])
        token = create_access_token(email)
        return {"access_token": token, "token_type": "bearer"}
    except ValueError as e:
        return {"error": f"Invalid Google token: {str(e)}"}
    except Exception as e:
        return {"error": f"Authentication failed: {str(e)}"}



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
    query_embedding = model.encode(combined_query).tolist()
    where_filter = extract_filters(combined_query)

    results = collection.query(
        query_embeddings=[query_embedding],
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
        llm_answer = generate_answer(combined_query, recipes)

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